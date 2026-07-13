from ntuple_processor import dataset_from_crownoutput, Unit
from ntuple_processor.variations import (
    get_quantities_from_expression,
    ReplaceCut,
    ReplaceWeight,
    ReplaceCutAndAddWeight,
    ReplaceVariable,
)
import re
from copy import deepcopy
import logging
import itertools

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

# def add_process(analysis_unit, name, dataset, selections, categorization, channel):
#     """
#     Add a process to the analysis unit.
#     """
#     if not isinstance(selections, list):
#         selections = [selections]
#     unitlist = []
#     for category_selection, actions in categorization[channel]:
#         full_selection = selections + [category_selection]
#         unitlist.append(Unit(dataset, full_selection, actions))

#     analysis_unit[name] = unitlist


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
    unitlist = [unit for process in processes for unit in datasets[process]]
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


def filter_friends(dataset, friend):
    # Add fake factor friends only for backgrounds.
    if re.match("(gg|qq|susybb|susygg|tt|w|z|v)h", dataset.lower()):
        if "FakeFactors" in friend or "EMQCDWeights" in friend:
            return False
    # Add NLOReweighting friends only for ggh signals.
    if "NLOReweighting" in friend:
        if re.match("(susygg)h", dataset.lower()) and not "powheg" in dataset.lower():
            pass
        else:
            return False
    elif re.match("data", dataset.lower()):
        if "xsec" in friend:
            return False
    elif re.match("emb", dataset.lower()):
        if "xsec" in friend:
            return False
    return True


def get_nominal_datasets(
    era, channel, friend_directories, files, directory, validation_tag, xrootd=False
):
    datasets = dict()
    if friend_directories is not None:
        for key, names in files[era][channel].items():
            datasets[key] = dataset_from_crownoutput(
                key,
                names,
                era,
                channel,
                channel + "_nominal",
                directory,
                [
                    fdir
                    for fdir in friend_directories[channel]
                    if filter_friends(key, fdir)
                ],
                validate_samples=False,
                validation_tag=validation_tag,
                xrootd=xrootd,
            )
    else:
        for key, names in files[era][channel].items():
            datasets[key] = dataset_from_crownoutput(
                key,
                names,
                era,
                channel,
                channel + "_nominal",
                directory,
                [],
                validate_samples=False,
                validation_tag=validation_tag,
                xrootd=xrootd,
            )
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
