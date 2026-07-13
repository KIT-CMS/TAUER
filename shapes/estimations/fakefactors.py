from copy import deepcopy
from functools import partial
import logging
import ROOT
from .defaults import _name_string, _process_map, _dataset_map

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def fake_factor_estimation(
    rootfile,
    channel,
    selection,
    variable,
    variation="Nominal",
    is_embedding=False,
    sub_scale=1.0,
    special="",
    doTauES=False,
    selection_option="CR",
):

    if is_embedding:
        if doTauES:
            procs_to_subtract = [special, "ZL", "TTL", "VVL"]
        else:
            procs_to_subtract = ["EMB", "ZL", "TTL", "VVL"]
    else:
        procs_to_subtract = ["ZTT", "ZL", "TTT", "TTL", "VVT", "VVL"]

    if selection_option == "CR":
        logger.info(f"CR selection, subtracting {procs_to_subtract}")
    elif "DR;ff" in selection_option:
        _QCD = "QCD" if is_embedding else "QCDMC"
        ff_processes_covered_by_mc = ['ZJ', 'VVJ', 'TTJ', 'W', _QCD]

        ff_processes_covered_by_mc.remove(_QCD)
        logger.warning(
            """
                Current implementation will not consider QCD due to the lack of a proper 
                QCD estimation in same_sign_anti_iso region.
            """
        )

        if "qcd" in selection_option:
            try:  # in case _QCD will be at some point in the future in ff_processes_covered_by_mc
                ff_processes_covered_by_mc.remove(_QCD)
            except ValueError:
                pass
            logger.info(f"DR;ff;qcd selection, adding for subtraction {ff_processes_covered_by_mc}")
        elif "wjet" in selection_option:
            ff_processes_covered_by_mc.remove("W")
            logger.info(f"DR;ff;wjet selection, adding for subtraction {ff_processes_covered_by_mc}")
        elif "ttbar" in selection_option:
            ff_processes_covered_by_mc.remove("TTJ")
            logger.info(f"DR;ff;ttbar selection, adding for subtraction {ff_processes_covered_by_mc}")
        else:
            msg = f"Unknown selection option for fake factor estimation: {selection_option}"
            logger.error(msg)
            raise ValueError(msg)

        procs_to_subtract += ff_processes_covered_by_mc
        logger.info(f"DR;ff selection, subtracting {procs_to_subtract}")

        processes_in_root_file = set([str(key.GetName()).split("#")[0] for key in rootfile.GetListOfKeys()])

        if _QCD in processes_in_root_file and _QCD in procs_to_subtract:
            logger.info("QCD process found in root file, will be used for fake factor estimation.")
            global _dataset_map, _process_map
            _dataset_map = deepcopy(_dataset_map)
            _process_map = deepcopy(_process_map)
            _dataset_map[_QCD] = _QCD
            _process_map[_QCD] = _QCD

    else:
        msg = f"Unknown selection option for fake factor estimation: {selection_option}"
        logger.error(msg)
        raise ValueError(msg)

    if special == "TauES":
        logger.debug("TauES special selection")

    _common_name_string = partial(
        _name_string.format,
        channel=channel,
        variable=variable,
        selection="-" + selection if selection != "" else "",
    )

    _string = _common_name_string(
        dataset="data",
        process="",
        variation="anti_iso" if "scale_t" in variation or "sub_syst" in variation else variation,
    )
    logger.debug(f"Trying to get object {_string}")
    base_hist = rootfile.Get(_string).Clone()
    for proc in procs_to_subtract:
        if "anti_iso_CMS_scale_t_emb" in variation and proc != "EMB":
            _string = _common_name_string(
                dataset=_dataset_map[proc],
                process="-" + _process_map[proc],
                variation=variation.replace("anti_iso_CMS_scale_t_emb", "anti_iso_CMS_scale_t") if not "sub_syst" in variation else "anti_iso",
            )

        else:
            _string = _common_name_string(
                dataset=_dataset_map[proc],
                process="-" + _process_map[proc],
                variation=variation if not "sub_syst" in variation else "anti_iso",
            )
        logger.debug(f"Trying to get object {_string}")
        base_hist.Add(rootfile.Get(_string), -sub_scale)
    proc_name = "jetFakes" if is_embedding else "jetFakesMC"
    if doTauES:
        proc_name = "jetFakes{}".format(special)
    if variation in ["anti_iso"]:
        ff_variation = "Nominal"
    else:
        ff_variation = variation.replace("anti_iso_", "")
    variation_name = (
        base_hist.GetName()
        .replace("data", proc_name)
        .replace(
            variation if "scale_t" not in variation and "sub_syst" not in variation else "anti_iso",
            ff_variation,
        )
        .replace("#" + channel, "#" + "-".join([channel, proc_name]), 1)
    )
    base_hist.SetName(variation_name)
    base_hist.SetTitle(variation_name)
    logger.debug("Finished estimation of shape %s.", variation_name)
    return base_hist
