import logging
from functools import partial
from .defaults import _name_string, _process_map, _dataset_map
from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def replace_negative_entries_and_renormalize(histogram, tolerance):
    # This function is taken from https://github.com/KIT-CMS/shape-producer/blob/beddc4a43e2e326018d804e58d612d8688ec33b6/shape_producer/histogram.py#L189

    # Find negative entries and calculate norm.
    norm_all = 0.0
    norm_positive = 0.0
    for i_bin in range(1, histogram.GetNbinsX() + 1):
        this_bin = histogram.GetBinContent(i_bin)
        if this_bin < 0.0:
            histogram.SetBinContent(i_bin, 0.0)
        else:
            norm_positive += this_bin
        norm_all += this_bin

    if norm_all == 0.0 and norm_positive != 0.0:
        logger.fatal(
            "Aborted renormalization because initial normalization is zero, but positive normalization not. . Check histogram %s",
            histogram.GetName(),
        )
        raise Exception

    if norm_all < 0.0:
        logger.fatal(
            "Aborted renormalization because initial normalization is negative: %f. Check histogram %s ",
            norm_all,
            histogram.GetName(),
        )
        raise Exception

    if abs(norm_all - norm_positive) > tolerance * norm_all:
        logger.warning(
            "Renormalization failed because the normalization changed by %f, which is above the tolerance %f. Check histogram %s",
            abs(norm_all - norm_positive),
            tolerance * norm_all,
            histogram.GetName(),
        )

    # Renormalize histogram if negative entries are found
    if norm_all != norm_positive:
        if norm_positive == 0.0:
            logger.fatal(
                "Renormalization failed because all bins have negative entries."
            )
            raise Exception
        for i_bin in range(1, histogram.GetNbinsX() + 1):
            this_bin = histogram.GetBinContent(i_bin)
            histogram.SetBinContent(i_bin, this_bin * norm_all / norm_positive)

    return histogram


def qcd_estimation(
    rootfile,
    channel,
    selection,
    variable,
    variation="Nominal",
    is_embedding=True,
    is_nlo=False,
    extrapolation_factor=1.2,
    sub_scale=1.0,
):
    logger.debug("Parameters for qcd estimation")
    logger.debug("channel: %s", channel)
    logger.debug("selection: %s", selection)
    logger.debug("variable: %s", variable)
    logger.debug("variation: %s", variation)
    logger.debug("is_embedding: %s", is_embedding)
    logger.debug("extrapolation_factor: %s", extrapolation_factor)
    logger.debug("sub_scale: %s", sub_scale)

    # Found a bug with ZJ/ZJ_NLO in the previous solution. This fixes it.
    LO_NLO_PROCESSES = {"ZTT": "ZTT", "W": "W", "ZL": "ZL", "ZJ": "ZJ"}

    procs_to_subtract = ["W"]  # all cases have at least this
    procs_to_subtract.extend(["EMB"] if is_embedding else ["ZTT", "TTT", "VVT"])  # EMB or MC

    if channel in {"et", "mt", "tt"}:  # semi-leptonic and fully-hadronic
        procs_to_subtract.extend(["ZL", "ZJ", "TTL", "TTJ", "VVL", "VVJ"])
    else:  # fully-leptonic - a bunch of extra cases... TODO: can this be removed?
        if "em" in channel:
            procs_to_subtract.extend(["ZL", "TTL", "VVL"])
        elif channel in {"mm", "ee"} and not is_embedding:
            procs_to_subtract = ["ZL", "W", "VVL", "TTL"]  # caution: replaced! no EMB or EMB MC equivalent

    if is_nlo:
        for lo, nlo in LO_NLO_PROCESSES.items():
            if lo in procs_to_subtract:
                procs_to_subtract.remove(lo)
                procs_to_subtract.append(nlo)

    _common_name_string = partial(
        _name_string.format,
        channel=channel,
        variable=variable,
        variation="same_sign" if "subtrMC" in variation else variation,
        selection="-" + selection if selection != "" else "",
    )

    _string = _common_name_string(dataset="data", process="")
    logger.debug(f"Trying to get object {_string}")
    base_hist = rootfile.Get(_string).Clone()
    for proc in procs_to_subtract:
        _string = _common_name_string(dataset=_dataset_map[proc], process="-" + _process_map[proc])
        logger.debug(f"Trying to get object {_string}")
        base_hist.Add(rootfile.Get(_string), -sub_scale)

    proc_name = "QCD" if is_embedding else "QCDMC"
    if is_nlo:
        proc_name = "_".join([proc_name, "NLO"])
    if variation in ["same_sign"]:
        qcd_variation = "Nominal"
    else:
        qcd_variation = variation.replace("same_sign_", "")
    logger.debug(f"Use extrapolation_factor factor with value {extrapolation_factor} to scale from ss to os region.")
    if base_hist.Integral() > 0.0:
        base_hist.Scale(extrapolation_factor)
    else:
        logger.warning(f"No data in same-sign region for histogram {base_hist.GetName()}. Setting extrapolation factor to 0.0")
        base_hist.Scale(0.0)
    variation_name = (
        base_hist.GetName()
        .replace("data", proc_name)
        .replace(variation if "subtrMC" not in variation else "same_sign", qcd_variation)
        .replace(channel, "-".join([channel, proc_name]), 1)
    )
    base_hist.SetName(variation_name)
    base_hist.SetTitle(variation_name)
    replace_negative_entries_and_renormalize(base_hist, tolerance=100.05)
    return base_hist
