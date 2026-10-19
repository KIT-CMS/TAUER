from ntuple_processor import dataset_from_crownoutput, Unit
from ntuple_processor.utils import Dataset
from ntuple_processor.systematics import (
    get_quantities_from_expression,
    ReplaceCut,
    ReplaceWeight,
    ReplaceCutAndAddWeight,
)
import os
import re
import shapes.naming as naming
import tau_es.energy_scales as tau_es_energy_scales
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
import logging

from common.analysis import get_signal_process_keys
from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

# Cap on how many dataset keys get validated concurrently in get_nominal_datasets()
_VALIDATION_WORKERS = 8


def _book_one_dataset(job):
    key, kwargs = job
    return key, dataset_from_crownoutput(**kwargs)


def add_process(
    analysis_unit,
    name,
    dataset,
    selections,
    categorization,
    channel,
    systematics=None,
    copy=False,
):
    """
    Add a process to the analysis unit.
    """
    if not isinstance(selections, list):
        selections = [selections]
    unitlist = []
    for category_selection, actions in categorization[channel]:
        path = f"{naming.bin_name(channel, category_selection.name)}/{_process_name(name, selections)}"
        full_selection = selections + [category_selection]
        if systematics is not None:
            unitlist.extend(Unit(dataset, full_selection, actions, systematic, path=path) for systematic in systematics)
        else:
            unitlist.append(Unit(dataset, full_selection, actions, path=path))

    analysis_unit[name] = unitlist


def _process_name(name, selections):
    # the process selection is named after the Combine process, data has none
    return naming.DATA if name == "data" else selections[-1].name


def combine_datasets(datasets):
    """One dataset over the ntuples of several (e.g. EW qqH from the qqH and VH samples), None if all are empty."""
    datasets = [dataset for dataset in datasets if dataset and dataset.ntuples]
    if len(datasets) <= 1:
        return datasets[0] if datasets else None
    quantities = {}
    for dataset in datasets:
        for shift, quants in (dataset.quantities_per_vars or {}).items():
            quantities[shift] = sorted(set(quantities.get(shift, [])) | set(quants))
    return Dataset("+".join(dataset.name for dataset in datasets), [n for dataset in datasets for n in dataset.ntuples], quantities)


def add_control_process(
    analysis_unit, name, dataset, selections, channel, binning, variables
):
    """Function used to add control plots of various variables to the analysis unit.

    Args:
        analysis_unit (dict): the dict used to book the histograms
        name (str): name of the process
        dataset (any): name of the dataset
        selections (list): list of selections to be applied
        channel (str): the channel to be used
        binning (dict): a dict containing the binning of the histogram
        variables (set): a set of variables to be used
    """

    if not isinstance(selections, list):
        selections = [selections]
    control_binning = []
    for variable in variables:
        control_binning.append(binning[channel][variable])
    analysis_unit[name] = [Unit(dataset, selections, control_binning, path=f"{channel}/{_process_name(name, selections)}")]


def book_histograms(manager, processes, datasets, systematics=None, enable_check=False, register_raw=True):
    logger.debug(f"Booking {processes}")
    logger.debug(f"Datasets: {datasets.keys()}")
    if not isinstance(processes, set):
        processes = set(processes)
    missing = processes - datasets.keys()
    if missing:
        logger.warning(f"Skipping processes with no booked units: {missing}")
    unitlist = [unit for process in processes if process in datasets for unit in datasets[process]]
    if systematics is not None:
        systematiclist = []
        for systematic in systematics:
            if isinstance(systematic, list):
                systematiclist.extend(systematic)
            else:
                systematiclist.append(systematic)
    else:
        systematiclist = None
    manager.book(
        unitlist,
        systematiclist,
        enable_check=enable_check,
        register_raw=register_raw,
    )


# Markers that delimit the friend tag inside a CROWN friend path
_FRIEND_TAG_MARKERS = ("CROWNFriend", "CROWNFriends", "CROWNMultiFriends")


def friend_tag(friend):
    """Return the CROWN friend tag of a friend directory path, or None.

    The tag is the path segment right after ``CROWNFriend``, ``CROWNFriends``
    or ``CROWNMultiFriends``, exactly as
    ``ntuple_processor/booking.py::add_tagged_friends`` derives it, e.g.::

        /common_path/CROWNFriend/selection/ntuple           -> "selection"
        root://xrootd.example/.../CROWNMultiFriends/NNclas/ -> "NNclas"

    Copes with xrootd URLs (the marker is matched on whole path segments, so
    the ``root://host//store/...`` prefix is irrelevant), trailing slashes and
    paths containing neither marker (returns None).
    """
    if not friend:
        return None
    segments = [segment for segment in str(friend).split("/") if segment]
    for marker in _FRIEND_TAG_MARKERS:
        if marker in segments:
            idx = segments.index(marker)
            if idx + 1 < len(segments):
                return segments[idx + 1]
            return None
    return None


def _normalize_tag(tag):
    """Lowercase a friend tag and drop separators/punctuation.

    ``EMQCD_weights`` -> ``emqcdweights``, so the tag hits its rule via prefix matching below.
    """
    return re.sub(r"[^a-z0-9]", "", str(tag).lower())


def _is_signal(dataset):
    return dataset.lower() in {key.lower() for key in get_signal_process_keys()}


def _keep_for_non_signal(dataset):
    return not _is_signal(dataset)


def _keep_for_nlo_reweighting(dataset):
    # Only the non-powheg susyggH signals carry NLO reweighting friends.
    return bool(re.match(r"(susygg)h", dataset.lower())) and "powheg" not in dataset.lower()


# Friend attachment rules, keyed by the *normalized* friend tag (see _normalize_tag)
_FRIEND_RULES = (
    # Same-sign/EMQCD weights: backgrounds/data only, never on signal samples.
    (("emqcdweights", "emqcdweight"), _keep_for_non_signal),
    # NLO reweighting: only non-powheg susyggH signals.
    (("nloreweighting",), _keep_for_nlo_reweighting),
)

# Friend tags we already reported as having no rule, so the debug message is
# emitted once per tag instead of once per (dataset, friend) pair.
_UNKNOWN_FRIEND_TAGS = set()


def filter_friends(dataset, friend):
    """Decide whether a friend directory should be attached to a dataset.

    Called once per (dataset, friend directory) pair, so any number of friend
    directories can be passed per run; each is judged independently, including
    two directories that normalize to the same rule. An unknown or underivable tag never raises: the friend is
    attached.
    """
    tag = friend_tag(friend)
    if tag is None:
        if friend not in _UNKNOWN_FRIEND_TAGS:
            _UNKNOWN_FRIEND_TAGS.add(friend)
            logger.debug(
                f"No CROWNFriends/CROWNMultiFriends segment in friend directory "
                f"{friend}; attaching it to all datasets."
            )
        return True
    normalized = _normalize_tag(tag)
    for prefixes, keep in _FRIEND_RULES:
        if normalized.startswith(prefixes):
            return keep(dataset)
    if tag not in _UNKNOWN_FRIEND_TAGS:
        _UNKNOWN_FRIEND_TAGS.add(tag)
        logger.debug(f"No filter rule for friend tag '{tag}'; attaching it to all datasets.")
    return True


def get_nominal_datasets(
    era,
    channel,
    friend_directories,
    files,
    directory,
    validation_tag,
    validation_db_root="validation_database",
    flat_layout=False,
    xrootd=False,
):
    from common.analysis import get_data_eras, get_mc_ntuple_era, get_samples

    # MC may need to be read from a different physical CROWN-production era
    # directory than the analysis era 
    mc_era = get_mc_ntuple_era(era)

    # (job key, dataset era, sample names): data of merged eras (DATA_ERA_MERGE,
    # e.g. 2026 into 2025) is booked as its own job from its own era directory
    # -- flat_layout inputs are already merged by the preselection -- and
    # appended to the analysis era's "data" dataset below.
    entries = [(key, era if key in ("data", "EMB") else mc_era, names)
               for key, names in files[era][channel].items()]
    if "data" in files[era][channel] and not flat_layout:
        for extra_era in get_data_eras(era)[1:]:
            extra_names = get_samples(extra_era, channel, include_signals=False).get("data", [])
            if not extra_names:
                logger.warning(f"[{era}/{channel}] no data samples configured for merged era {extra_era}")
                continue
            logger.info(f"[{era}/{channel}] merging {len(extra_names)} data samples from era {extra_era}")
            entries.append(("data", extra_era, extra_names))

    jobs = []
    for key, dataset_era, names in entries:
        friends = (
            [
                fdir
                for fdir in friend_directories[channel]
                if filter_friends(key, fdir)
            ]
            if friend_directories is not None
            else []
        )
        jobs.append((
            key,
            dict(
                dataset_name=key,
                file_names=names,
                era=dataset_era,
                channel=channel,
                folder=channel + "_nominal",
                files_base_directory=directory,
                friends_base_directories=friends,
                validate_samples=False,
                validation_tag=validation_tag,
                validation_db_root=validation_db_root,
                flat_layout=flat_layout,
                xrootd=xrootd,
            ),
        ))

    datasets = dict()
    n_workers = min(_VALIDATION_WORKERS, len(jobs), os.cpu_count() or _VALIDATION_WORKERS) or 1
    if n_workers <= 1:
        booked = [(key, dataset_from_crownoutput(**kwargs)) for key, kwargs in jobs]
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            booked = list(pool.map(_book_one_dataset, jobs))
    # a key booked more than once (merged-era data) is concatenated in order
    for key, dataset in booked:
        if key in datasets:
            datasets[key].add_to_ntuples(*dataset.ntuples)
        else:
            datasets[key] = dataset
    return datasets


def add_tauES_datasets(
    era,
    channel,
    friend_directories,
    files,
    directory,
    nominals,
    tauESshifts,
    selections,
    categorization,
    additional_emb_procS,
    validation_tag,
    validation_db_root="validation_database",
    flat_layout=False,
    xrootd=False,
    shiftstring="EMBtauESshift",
):
    for shift in tauESshifts:
        processname = tau_es_energy_scales.shift_to_procname(shift)
        logger.info(f"Adding {processname}")
        dataset = dataset_from_crownoutput(
            processname,
            files[era][channel]["EMB"],
            era,
            channel,
            channel + "_nominal",
            directory,
            [
                fdir
                for fdir in friend_directories[channel]
                if filter_friends("EMB", fdir)
            ],
            validate_samples=False,
            validation_tag=validation_tag,
            validation_db_root=validation_db_root,
            flat_layout=flat_layout,
            xrootd=xrootd,
        )
        nominals[era]["datasets"][channel][processname] = dataset
        updated_unit = []
        additional_emb_procS.add(processname)
        shiftname = f"{shiftstring}_{processname.removeprefix('emb')}"
        for category_selection, actions in categorization[channel]:
            full_selection = selections + [category_selection]
            new_selections = deepcopy(full_selection)
            new_actions = deepcopy(actions)
            list_of_quants = dataset.quantities_per_vars
            quants = set(list_of_quants[shiftname])
            if shiftname not in list_of_quants.keys():
                logger.critical(f"{shiftname} not in list_of_quants.keys()")
            else:
                for sel_obj in new_selections:
                    for cut in sel_obj.cuts:
                        for quant in quants & get_quantities_from_expression(
                            cut.expression
                        ):
                            cut.expression = re.sub(
                                rf"\b({quant})\b",
                                f"{quant}__{shiftname}",
                                cut.expression,
                        )
                            logger.debug(
                                f"Replaced {quant} in {cut.expression} ( quant: {quant}, var: {shiftname})"
                            )
                    for weight in sel_obj.weights:
                        for quant in quants & get_quantities_from_expression(
                            weight.expression
                        ):
                            weight.expression = weight.expression.replace(
                                quant,
                                "{quant}__{var}".format(quant=quant, var=shiftname),
                            )
                            logger.debug(
                                f"Replaced weight {quant} with {weight.expression} ( quant: {quant}, var: {shiftname})"
                            )
                for act in new_actions:
                    for quant in quants & get_quantities_from_expression(act.variable):
                        act.variable = act.variable.replace(
                            quant,
                            "{quant}__{var}".format(quant=act.variable, var=shiftname),
                        )
                        logger.debug(
                            f"Replaced action {quant} with {act.variable} ( quant: {quant}, var: {shiftname})"
                        )
                shift_path = f"{naming.bin_name(channel, category_selection.name)}/EMB_{tau_es_energy_scales.procname_to_shift_string(processname)}"
                updated_unit.append(Unit(dataset, new_selections, new_actions, path=shift_path))
            nominals[era]["units"][channel][processname] = updated_unit


def book_tauES_histograms(
    manager,
    additional_emb_procS,
    datasets,
    systematics,
    enable_check=False,
    shiftstring="EMBtauESshift",
):
    def replace_expression(exp, quants):
        quant_string = set(quants[shiftname])
        for quant in quant_string & get_quantities_from_expression(exp):
                exp = re.sub(
                rf"\b({exp})\b",
                f"{quant}__{shiftname}",
                exp
                )
                logger.debug(
                    f"Replaced {quant} in {exp} ( quant: {quant}, var: {shiftname}"
                )
        return exp
    for tau_es_shift in additional_emb_procS:
        logger.debug(f"Booking {tau_es_shift}")
        shiftname = f"{shiftstring}_{tau_es_shift.replace('emb', '')}"
        updated_systematics = deepcopy(systematics)
        final_systematics = []
        unitlist = datasets[tau_es_shift]
        if len(unitlist) == 0:
            continue
        quants = unitlist[0].dataset.quantities_per_vars
        for systematic in updated_systematics:
            if isinstance(systematic, list):
                systematiclist = systematic
            else:
                systematiclist = [systematic]
            for subsystematic in systematiclist:
                if isinstance(subsystematic, ReplaceCut):
                    subsystematic.cut.expression = replace_expression(
                        subsystematic.cut.expression, quants
                    )
                elif isinstance(subsystematic, ReplaceWeight):
                    subsystematic.weight.expression = replace_expression(
                        subsystematic.weight.expression, quants
                    )
                elif isinstance(subsystematic, ReplaceCutAndAddWeight):
                    subsystematic.replace_cut.cut.expression = replace_expression(
                        subsystematic.replace_cut.cut.expression, quants
                    )
                    subsystematic.add_weight.weight.expression = replace_expression(
                        subsystematic.add_weight.weight.expression, quants
                    )
                else:
                    pass
                final_systematics.append(subsystematic)
        logger.warning(f"final_systematics: {final_systematics}")
        manager.book(
            unitlist,
            final_systematics,
            enable_check=enable_check,
        )
