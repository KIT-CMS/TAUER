from functools import partial
import logging
from .defaults import _name_string, _process_map, _dataset_map

from config.logging_setup_configs import setup_logging
from config.processes import BACKGROUNDS, GROUPS

logger = setup_logging(logger=logging.getLogger(__name__))


def fake_factor_estimation(
    rootfile,
    channel,
    selection,
    variable,
    systematic="Nominal",
    is_embedding=False,
    special="",
    doTauES=False,
    floor_negative=True,
):

    if is_embedding:
        if doTauES:
            procs_to_subtract = [special, "ZL", "TTL", "VVL"]
        else:
            procs_to_subtract = ["EMB"] + [BACKGROUNDS[k].datacard for k in GROUPS["lep_fake"]]
    else:
        procs_to_subtract = [BACKGROUNDS[k].datacard for k in GROUPS["ff_subtraction"]]

    logger.info(f"Subtracting {procs_to_subtract}")

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
        systematic="anti_iso" if "scale_t" in systematic else systematic,
    )
    logger.debug(f"Trying to get object {_string}")
    base_hist = rootfile.Get(_string).Clone()
    for proc in procs_to_subtract:
        _string = _common_name_string(
            dataset=_dataset_map[proc],
            process="-" + _process_map[proc],
            systematic=systematic,
        )
        logger.debug(f"Trying to get object {_string}")
        base_hist.Add(rootfile.Get(_string), -1)
    proc_name = "jetFakes" if is_embedding else "jetFakesMC"
    if doTauES:
        proc_name = "jetFakes{}".format(special)
    if systematic in ["anti_iso"]:
        ff_systematic = "Nominal"
    else:
        ff_systematic = systematic.replace("anti_iso_", "")
    systematic_name = (
        base_hist.GetName()
        .replace("data", proc_name)
        .replace(
            systematic if "scale_t" not in systematic else "anti_iso",
            ff_systematic,
        )
        .replace("#" + channel, "#" + "-".join([channel, proc_name]), 1)
    )
    base_hist.SetName(systematic_name)
    base_hist.SetTitle(systematic_name)
    if floor_negative:
        for i in range(1, base_hist.GetNbinsX() + 1):
            if base_hist.GetBinContent(i) < 0:
                base_hist.SetBinContent(i, 0.0)
                base_hist.SetBinError(i, 0.0)
    logger.debug("Finished estimation of shape %s.", systematic_name)
    return base_hist
