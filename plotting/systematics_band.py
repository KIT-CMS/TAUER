"""
Total shape-systematic uncertainty band for control plots.

Reuses datacards/systematics.py's own declarative list of shape
systematics (name/process-type/channel).

This gives a PRE-FIT band: the quadrature sum of each shape systematic's
symmetrized (Up-Down)/2 shift, source-by-source. A source shared by several
processes (e.g. CMS_scale_j affects all of processes.mc together) is summed
coherently across those processes FIRST (one shift, correlated), then
different sources are added in quadrature (treated as uncorrelated with each
other) -- so this is not simply "quadrature-sum every process x every
source" but a proper per-source correlated-then-quadrature combination. It
is NOT a post-fit uncertainty: it ignores the fit's pulls/constraints and
correlations between systematics the way `combine` would apply them, so treat
it as an upper-bound-ish sanity-check band for control plots, not a
substitute for a real post-fit band.
"""
import logging
from typing import Callable, Dict, Optional, Tuple

import numpy as np
import ROOT

from datacards.systematics import add_systematics
from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def shape_systematic_uncertainty(
    rootfile: "ROOT.TFile",
    channel: str,
    era: str,
    variable: str,
    bkg_hists: Dict[str, "ROOT.TH1"],
    proc_selectors: Dict[str, Tuple[str, str]],
    n_bins: int,
    category: str = "",
    get_hist: Optional[Callable] = None,
) -> Tuple[np.ndarray, bool]:
    if get_hist is None:
        from plotting.plot_shapes_control import _get_hist as get_hist

    record = []
    add_systematics(cb=None, era=era, record=record, shape_systematics=True)

    total_sq = np.zeros(n_bins)
    found_any_overall = False
    for name, syst_type, procs, chans in record:
        if syst_type != "shape" or channel not in chans:
            continue

        delta = np.zeros(n_bins)
        found_any = False
        for proc in procs:
            if proc not in bkg_hists or proc not in proc_selectors:
                continue
            dataset, selection = proc_selectors[proc]
            h_up = get_hist(rootfile, dataset, channel, "-" + selection, f"{name}Up", variable, category=category)
            h_down = get_hist(rootfile, dataset, channel, "-" + selection, f"{name}Down", variable, category=category)
            if h_up is None or h_down is None:
                continue
            found_any = True
            delta += np.array(
                [h_up.GetBinContent(i + 1) - h_down.GetBinContent(i + 1) for i in range(n_bins)]
            ) / 2.0

        if found_any:
            total_sq += delta ** 2
            found_any_overall = True
        else:
            logger.debug(
                f"No shape found for systematic {name!r} in {channel}/{variable} "
                f"(category={category!r}) -- skipping (not yet produced, or none of its "
                f"processes are plotted here)."
            )

    return np.sqrt(total_sq), found_any_overall
