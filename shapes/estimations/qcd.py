import logging
from functools import partial
import shapes.naming as naming
from CustomLogging import setup_logging

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
    category,
    variable,
    shift=None,
    is_embedding=True,
    extrapolation_factor=1.2,
    sub_scale=1.0,
):
    """QCD from the same-sign region: data minus the subtracted backgrounds, scaled to opposite sign. The subtrMC shifts
    vary the subtraction of the nominal inputs."""
    logger.debug(f"QCD estimation for {channel} {category} {variable} {shift}, embedding {is_embedding}, "
                 f"extrapolation factor {extrapolation_factor}, subtraction scale {sub_scale}")

    procs_to_subtract = ["W"]  # all cases have at least this
    procs_to_subtract.extend(["EMB"] if is_embedding else ["ZTT", "TTT", "VVT"])  # EMB or MC

    if channel in {"et", "mt", "tt"}:  # semi-leptonic and fully-hadronic
        procs_to_subtract.extend(["ZL", "ZJ", "TTL", "TTJ", "VVL", "VVJ"])
    else:  # fully-leptonic - a bunch of extra cases... TODO: can this be removed?
        if "em" in channel:
            procs_to_subtract.extend(["ZL", "TTL", "VVL"])
        elif channel in {"mm", "ee"} and not is_embedding:
            procs_to_subtract = ["ZL", "W", "VVL", "TTL"]  # caution: replaced! no EMB or EMB MC equivalent

    input_shift = None if shift and "subtrMC" in shift else shift
    _get = partial(naming.get, rootfile, variable, channel, category=category, region="ss", systematic=input_shift)
    base_hist = _get(naming.DATA).Clone()
    for proc in procs_to_subtract:
        base_hist.Add(_get(proc), -sub_scale)

    logger.debug(f"Use extrapolation_factor factor with value {extrapolation_factor} to scale from ss to os region.")
    if base_hist.Integral() > 0.0:
        base_hist.Scale(extrapolation_factor)
    else:
        logger.warning(f"No data in same-sign region for histogram {base_hist.GetName()}. Setting extrapolation factor to 0.0")
        base_hist.Scale(0.0)
    replace_negative_entries_and_renormalize(base_hist, tolerance=100.05)
    return base_hist, naming.path(variable, channel, "QCD", category, systematic=shift)
