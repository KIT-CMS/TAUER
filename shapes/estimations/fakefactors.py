from functools import partial
import logging

import shapes.naming as naming
from config.logging_setup_configs import setup_logging
from config.processes import BACKGROUNDS, GROUPS

logger = setup_logging(logger=logging.getLogger(__name__))


def fake_factor_estimation(
    rootfile,
    channel,
    category,
    variable,
    shift=None,
    is_embedding=False,
    floor_negative=True,
):
    """jetFakes from the anti-isolated region: FF-weighted data minus the FF-weighted subtracted backgrounds. The data
    take the shift too unless it is a tau energy scale one, which only moves the subtracted simulation."""
    if is_embedding:
        procs_to_subtract = ["EMB"] + [BACKGROUNDS[k].datacard for k in GROUPS["lep_fake"]]
    else:
        procs_to_subtract = [BACKGROUNDS[k].datacard for k in GROUPS["ff_subtraction"]]
    logger.info(f"Subtracting {procs_to_subtract}")

    _get = partial(naming.get, rootfile, variable, channel, category=category, region="ar")
    base_hist = _get(naming.DATA, systematic=None if shift and "scale_t" in shift else shift).Clone()
    for proc in procs_to_subtract:
        base_hist.Add(_get(proc, systematic=shift), -1)
    if floor_negative:
        for i in range(1, base_hist.GetNbinsX() + 1):
            if base_hist.GetBinContent(i) < 0:
                base_hist.SetBinContent(i, 0.0)
                base_hist.SetBinError(i, 0.0)
    return base_hist, naming.path(variable, channel, "jetFakes", category, systematic=shift)
