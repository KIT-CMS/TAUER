from ntuple_processor import dataset_from_crownoutput, Unit
from ntuple_processor.variations import (
    get_quantities_from_expression,
    ReplaceCut,
    ReplaceWeight,
    ReplaceCutAndAddWeight,
)
import os
import re
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
import logging

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

# Cap on how many dataset keys (DY/TT/VV/W/data/signals/...) get validated
# concurrently in get_nominal_datasets(). dataset_from_crownoutput()'s own
# per-file validation (see ntuple_processor/booking.py) is a plain sequential
# Python loop doing one remote xrootd TFile.Open per file, with no
# parallelism of its own -- this is what makes a cold validation_database
# cache (a brand new NTUPLETAG/--validation-tag) painfully slow, since it's
# entirely network-latency-bound (near-zero CPU while it waits on each
# remote open). Running one dataset key's validation per worker process
# (same fork-based multiprocessing pattern already used safely in
# xsec/build_friend_tree.py) turns that into up to _VALIDATION_WORKERS
# concurrent remote opens instead of one at a time -- a real, direct speedup
# for the first run against any given tag. Once validation_database/<tag>/
# is populated, subsequent runs hit the cache and this doesn't matter.
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
    variations=None,
    copy=False,
):
    """
    Add a process to the analysis unit.
    """
    if not isinstance(selections, list):
        selections = [selections]
    unitlist = []
    if variations is not None:
        for variation in variations:
            for category_selection, actions in categorization[channel]:
                full_selection = selections + [category_selection]
                unitlist.append(Unit(dataset, full_selection, actions, variation))
    else:
        for category_selection, actions in categorization[channel]:
            full_selection = selections + [category_selection]
            unitlist.append(Unit(dataset, full_selection, actions))

    analysis_unit[name] = unitlist


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
    analysis_unit[name] = [(Unit(dataset, selections, control_binning))]


def book_histograms(manager, processes, datasets, variations=None, enable_check=False):
    logger.debug(f"Booking {processes}")
    logger.debug(f"Datasets: {datasets.keys()}")
    if not isinstance(processes, set):
        processes = set(processes)
    missing = processes - datasets.keys()
    if missing:
        logger.warning(f"Skipping processes with no booked units: {missing}")
    unitlist = [unit for process in processes if process in datasets for unit in datasets[process]]
    if variations is not None:
        variationlist = []
        for variation in variations:
            if isinstance(variation, list):
                variationlist.extend(variation)
            else:
                variationlist.append(variation)
    else:
        variationlist = None
    manager.book(
        unitlist,
        variationlist,
        enable_check=enable_check,
    )


# Markers that delimit the friend tag inside a CROWN friend path. Mirrors
# ntuple_processor/booking.py::add_tagged_friends -- the tag is the path
# segment immediately following one of these markers. Keep in sync with
# booking.py (that file lives in a submodule and must not be edited here).
_FRIEND_TAG_MARKERS = ("CROWNFriends", "CROWNMultiFriends")


def friend_tag(friend):
    """Return the CROWN friend tag of a friend directory path, or None.

    The tag is the path segment right after ``CROWNFriends`` or
    ``CROWNMultiFriends``, exactly as
    ``ntuple_processor/booking.py::add_tagged_friends`` derives it, e.g.::

        /common_path/CROWNFriends/fastmtt/ntuple            -> "fastmtt"
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

    ``fake_factors_260618_v5`` -> ``fakefactors260618v5``, ``FakeFactors`` ->
    ``fakefactors``, so both hit the same rule via prefix matching below.
    """
    return re.sub(r"[^a-z0-9]", "", str(tag).lower())


def _is_signal(dataset):
    """The historic signal-sample regex (ggH/qqH/susybbH/susyggH/ttH/WH/ZH/VH)."""
    return bool(re.match(r"(gg|qq|susybb|susygg|tt|w|z|v)h", dataset.lower()))


def _keep_for_non_signal(dataset):
    return not _is_signal(dataset)


def _keep_for_nlo_reweighting(dataset):
    # Only the non-powheg susyggH signals carry NLO reweighting friends.
    return bool(re.match(r"(susygg)h", dataset.lower())) and "powheg" not in dataset.lower()


def _keep_for_xsec(dataset):
    # Cross-section friends are MC-only: never for data nor for embedding.
    return not re.match(r"(data|emb)", dataset.lower())


# Friend attachment rules, keyed by the *normalized* friend tag (see
# _normalize_tag) rather than by substring-searching the whole friend path --
# the real production directories are named e.g. "fake_factors_260618_v5", for
# which the old `"FakeFactors" in friend` test silently never fired.
#
# Each entry is (tuple of normalized tag prefixes, predicate(dataset) -> bool).
# The first entry whose prefix matches the normalized tag wins, so order the
# table most-specific-first. A tag matching no entry (fastmtt, selection, NN
# friends, ...) is attached to every dataset.
#
# Prefix matching is deliberate so that versioned/dated directories
# ("fake_factors_260618_v5", "ff_260618") resolve to the same rule as the bare
# name. Note "fastmtt" and "fakefactors" only share the two leading letters
# "fa", so neither the "fakefactor" nor the "ff" prefix can capture fastmtt.
# Adding a new friend type should be a one-line addition here.
_FRIEND_RULES = (
    # Fake-factor friends: backgrounds/data only, never on signal samples.
    (("fakefactors", "fakefactor", "ff"), _keep_for_non_signal),
    # Same-sign/EMQCD weights: backgrounds/data only, never on signal samples.
    (("emqcdweights", "emqcdweight"), _keep_for_non_signal),
    # NLO reweighting: only non-powheg susyggH signals.
    (("nloreweighting",), _keep_for_nlo_reweighting),
    # Cross-section friends: MC only, not for data or embedding.
    (("xsec",), _keep_for_xsec),
)

# Friend tags we already reported as having no rule, so the debug message is
# emitted once per tag instead of once per (dataset, friend) pair.
_UNKNOWN_FRIEND_TAGS = set()


def filter_friends(dataset, friend):
    """Decide whether a friend directory should be attached to a dataset.

    Called once per (dataset, friend directory) pair, so any number of friend
    directories can be passed per run; each is judged independently, including
    two directories that normalize to the same rule (e.g. fake_factors_v4 and
    fake_factors_v5). An unknown or underivable tag never raises: the friend is
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
    from config.analysis import get_mc_ntuple_era

    # MC may need to be read from a different physical CROWN-production era
    # directory than the analysis era (see MC_NTUPLE_ERA_OVERRIDE, e.g. 2026
    # borrowing 2025's un-copied MC ntuples/friends) -- data/embedding always
    # read from the real era's own directory.
    mc_era = get_mc_ntuple_era(era)

    jobs = []
    for key, names in files[era][channel].items():
        dataset_era = era if key in ("data", "EMB") else mc_era
        friends = (
            [fdir for fdir in friend_directories[channel] if filter_friends(key, fdir)]
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

    # See _VALIDATION_WORKERS docstring above: this is what actually parallelizes
    # the slow, network-bound per-file xrootd validation that dataset_from_crownoutput
    # does internally and sequentially -- one dataset key (DY/TT/VV/W/data/...) per
    # worker process instead of one at a time. Falls back to a single worker
    # (no process pool overhead) when there's nothing to gain from it.
    datasets = dict()
    n_workers = min(_VALIDATION_WORKERS, len(jobs), os.cpu_count() or _VALIDATION_WORKERS) or 1
    if n_workers <= 1:
        for key, kwargs in jobs:
            datasets[key] = dataset_from_crownoutput(**kwargs)
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            for key, dataset in pool.map(_book_one_dataset, jobs):
                datasets[key] = dataset
    return datasets


def add_tauES_datasets(
    era,
    channel,
    friend_directories,
    files,
    directory,
    nominals,
    tauESvariations,
    selections,
    categorization,
    additional_emb_procS,
    validation_tag,
    validation_db_root="validation_database",
    flat_layout=False,
    xrootd=False,
    shiftstring="EMBtauESshift",
):
    for variation in tauESvariations:
        name = str(round(variation, 2)).replace("-", "minus").replace(".", "p")
        processname = f"emb{name}"
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
        additional_emb_procS.add(f"emb{name}")
        shiftname = f"{shiftstring}_{name}"
        for category_selection, actions in categorization[channel]:
            full_selection = selections + [category_selection]
            new_selections = deepcopy(full_selection)
            new_actions = deepcopy(actions)
            list_of_quants = dataset.quantities_per_vars
            quants = set(list_of_quants[shiftname])
            if shiftname not in list_of_quants.keys():
                logger.critical(f"{shiftname} not in list_of_quants.keys()")
            else:
                # for quant in :
                for sel_obj in new_selections:
                    for cut in sel_obj.cuts:
                        # now find the intersection between quants and the expression set
                        for quant in quants & get_quantities_from_expression(
                            cut.expression
                        ):
                            # cut.expression = cut.expression.replace(
                            #     quant,
                            #     "{quant}__{var}".format(quant=quant, var=shiftname),
                            # )
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
                updated_unit.append(Unit(dataset, new_selections, new_actions))
            nominals[era]["units"][channel][processname] = updated_unit


def book_tauES_histograms(
    manager,
    additional_emb_procS,
    datasets,
    variations,
    enable_check=False,
    shiftstring="EMBtauESshift",
):
    # def replace_expression(exp, quants):
    #     for quant in quants[shiftname]:
    #         if quant in exp:
    #             exp = exp.replace(
    #                 quant,
    #                 "{quant}__{var}".format(quant=quant, var=shiftname),
    #             )
    #             logger.debug(
    #                 f"Replaced {quant} in {exp} ( quant: {quant}, var: {shiftname}"
    #             )
    #     return exp
    
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
        updated_variations = deepcopy(variations)
        final_variations = []
        unitlist = datasets[tau_es_shift]
        if len(unitlist) == 0:
            continue
        quants = unitlist[0].dataset.quantities_per_vars
        for variation in updated_variations:
            if isinstance(variation, list):
                variationlist = variation
            else:
                variationlist = [variation]
            for subvariation in variationlist:
                if isinstance(subvariation, ReplaceCut):
                    subvariation.cut.expression = replace_expression(
                        subvariation.cut.expression, quants
                    )
                elif isinstance(subvariation, ReplaceWeight):
                    subvariation.weight.expression = replace_expression(
                        subvariation.weight.expression, quants
                    )
                elif isinstance(subvariation, ReplaceCutAndAddWeight):
                    subvariation.replace_cut.cut.expression = replace_expression(
                        subvariation.replace_cut.cut.expression, quants
                    )
                    subvariation.add_weight.weight.expression = replace_expression(
                        subvariation.add_weight.weight.expression, quants
                    )
                else:
                    # logger.critical(f"Unknown variation {subvariation}")
                    # raise ValueError(f"Unknown variation {subvariation}")
                    pass
                final_variations.append(subvariation)
        logger.warning(f"final_variations: {final_variations}")
        manager.book(
            unitlist,
            final_variations,
            enable_check=enable_check,
        )
