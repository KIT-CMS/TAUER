#!/usr/bin/env python3
"""
Measures ttbar/DY normalization weights (k_TT, k_DY) from the em-channel
"tt_dy_weight" categorization (shapes/special/ttbar_dy_weight_categories.py): nbtag==0 vs
nbtag>=1, crossed with pzetamissvis > -25 ("DY-like") vs <= -25 ("TT/VV-like").

Read-only w.r.t. ntuples: only opens already-produced shapes.root files (HTCondor-submitted
via condor/submit_shapes.py --special-analysis TTbarDYWeight, then
condor/submit_estimations.py --do-qcd for the QCD histograms this script also reads).

Per-region model (four regions: nbtag0_pzetahi, nbtag0_pzetalo, nbtagge1_pzetahi,
nbtagge1_pzetalo):

    data_r ~= k_TT * TT_r + k_DY * DY_r + (W_r + VV_r + QCD_r)

TT = TTT + TTL (TTJ excluded, same convention as ttbar_em_weight). DY = ZTT + ZL + ZJ
(unsplit). Sequential two-stage fit: k_TT first, from the TT-pure nbtag>=1 rows where DY is
negligible; then k_DY from the nbtag==0 rows with TT fixed at k_TT's stage-1 value. k_DY's
reported uncertainty propagates k_TT's stage-1 uncertainty through dk_DY/dk_TT. The old
joint 2x2 fit (fit_weights_joint()) is kept and reported as a cross-check.

This script only measures and reports; a human decides whether/how to apply the numbers to
shapes/selection/process_selection.py's hardcoded ratio_em.

Example:
    python3 shapes/special/calculate_ttbar_dy_weights.py \\
        --ntupletag htt_260813_22-23 \\
        --eras 2022preEE,2022postEE,2023preBPix,2023postBPix
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import ROOT

from common.sample_paths import build_shape_output_paths
from config.logging_setup_configs import setup_logging
from shapes.special.ttbar_dy_weight_categories import categories as _categories
from shapes import naming

logger = setup_logging(logger=logging.getLogger(__name__))

CHANNEL = "em"
VARIABLE = "m_vis"
REGIONS = list(_categories[CHANNEL].keys())  # single-sourced off the categorization itself
# The two rows the sequential fit actually uses per stage.
TT_ROWS = [r for r in REGIONS if r.startswith("nbtagge1")]  # stage 1: k_TT
DY_ROWS = [r for r in REGIONS if r.startswith("nbtag0")]  # stage 2: k_DY (k_TT fixed)
# The off-diagonal, more-mixed region of each pair -- decent post-fit closure
# checks (nbtag0_pzetalo is TT/VV-enriched despite being a "DY row", and
# nbtagge1_pzetahi is the most DY-contaminated "TT row").
CLOSURE_REGIONS = ["nbtag0_pzetalo", "nbtagge1_pzetahi"]

# Combine process names to sum for each physics group
_TT_PARTS = ["TTT", "TTL"]  # TTJ excluded, same as ttbar_em_weight
_DY_PARTS = ["ZTT", "ZL", "ZJ"]
_W_PARTS = ["W"]
_VV_PARTS = ["VVT", "VVL", "VVJ"]
_QCD_PARTS = ["QCD"]  # written by shapes/do_estimations.py --do-qcd
_DATA = naming.DATA


def _get_hist(rootfile, process, category, variable=VARIABLE):
    return naming.get(rootfile, variable, CHANNEL, process, category=category)


def _sum_yield(rootfile, parts, category):
    """Sum Integral()+error over a list of process histograms."""
    total, total_err2 = 0.0, 0.0
    for process in parts:
        hist = _get_hist(rootfile, process, category)
        err = np.array([0.0])
        val = hist.IntegralAndError(1, hist.GetNbinsX(), err)
        total += val
        total_err2 += err[0] ** 2
    return total, total_err2**0.5


def collect_region_yields(rootfile):
    """Returns {region: {"data": (v, e), "TT": (v, e), "DY": (v, e), "fixed": (v, e)}}."""
    out = {}
    for region in REGIONS:
        data = _get_hist(rootfile, _DATA, region)
        data_err = np.array([0.0])
        data_val = data.IntegralAndError(1, data.GetNbinsX(), data_err)
        tt = _sum_yield(rootfile, _TT_PARTS, region)
        dy = _sum_yield(rootfile, _DY_PARTS, region)
        w = _sum_yield(rootfile, _W_PARTS, region)
        vv = _sum_yield(rootfile, _VV_PARTS, region)
        qcd = _sum_yield(rootfile, _QCD_PARTS, region)
        fixed_val = w[0] + vv[0] + qcd[0]
        fixed_err = (w[1] ** 2 + vv[1] ** 2 + qcd[1] ** 2) ** 0.5
        out[region] = {
            "data": (data_val, data_err[0]),
            "TT": tt,
            "DY": dy,
            "W": w,
            "VV": vv,
            "QCD": qcd,
            "fixed": (fixed_val, fixed_err),
        }
    return out


def fit_weights_joint(region_yields):
    """
    Cross-check only (see module docstring): joint weighted least squares for
    (k_TT, k_DY) across all four regions at once, data_r - fixed_r ~=
    k_TT*TT_r + k_DY*DY_r, weighted by inverse data variance (Poisson:
    sigma_r^2 = data_r content). Returns (k_TT, k_DY, cov) with cov the 2x2
    parameter covariance matrix.
    """
    X = np.array([[region_yields[r]["TT"][0], region_yields[r]["DY"][0]] for r in REGIONS])
    y = np.array([region_yields[r]["data"][0] - region_yields[r]["fixed"][0] for r in REGIONS])
    data_vals = np.array([max(region_yields[r]["data"][0], 1.0) for r in REGIONS])  # Poisson variance, floored to avoid /0
    w = 1.0 / data_vals

    W = np.diag(w)
    XtWX = X.T @ W @ X
    XtWy = X.T @ W @ y
    cov = np.linalg.inv(XtWX)
    params = cov @ XtWy
    return params[0], params[1], cov


def _scalar_wls(x, y, w):
    """weighted least squares for a single scalar slope y ~= k*x. Returns (k, var(k))."""
    x, y, w = np.asarray(x), np.asarray(y), np.asarray(w)
    denom = np.sum(w * x**2)
    k = np.sum(w * x * y) / denom
    var = 1.0 / denom
    return k, var


def fit_weights_sequential(region_yields):
    """
    Two-stage fit: k_TT first from the TT-pure nbtag>=1 rows (TT_ROWS), then
    k_DY from the nbtag==0 rows (DY_ROWS) with TT moved into the fixed
    prediction at that k_TT value. See module docstring for the rationale.

    Returns (k_tt, k_tt_var, k_dy, k_dy_var) -- k_dy_var already includes
    k_tt's stage-1 uncertainty propagated through dk_DY/dk_TT.
    """
    # Stage 1: k_TT from nbtag>=1 rows, DY left in the (negligible) fixed background.
    x_tt = [region_yields[r]["TT"][0] for r in TT_ROWS]
    y_tt = [region_yields[r]["data"][0] - region_yields[r]["fixed"][0] - region_yields[r]["DY"][0]
            for r in TT_ROWS]
    w_tt = [1.0 / max(region_yields[r]["data"][0], 1.0) for r in TT_ROWS]
    k_tt, k_tt_var = _scalar_wls(x_tt, y_tt, w_tt)

    # Stage 2: k_DY from nbtag==0 rows, TT fixed at k_tt.
    x_dy = np.array([region_yields[r]["DY"][0] for r in DY_ROWS])
    tt_dy = np.array([region_yields[r]["TT"][0] for r in DY_ROWS])
    y_dy = np.array([
        region_yields[r]["data"][0] - region_yields[r]["fixed"][0] - k_tt * region_yields[r]["TT"][0]
        for r in DY_ROWS
    ])
    w_dy = np.array([1.0 / max(region_yields[r]["data"][0], 1.0) for r in DY_ROWS])
    k_dy, k_dy_stat_var = _scalar_wls(x_dy, y_dy, w_dy)

    # Propagate k_TT's uncertainty through the stage-2 fixed point: dk_DY/dk_TT
    # = -sum(w*DY*TT) / sum(w*DY^2) (regions are TT/DY-anticorrelated here).
    dk_dy_dk_tt = -np.sum(w_dy * x_dy * tt_dy) / np.sum(w_dy * x_dy**2)
    k_dy_var = k_dy_stat_var + (dk_dy_dk_tt ** 2) * k_tt_var

    return k_tt, k_tt_var, k_dy, k_dy_var


# Not /web/<user>/public_html/... (plot_shapes_control.py's usual home via
# run.py's PLOT mode): this script is meant to run right after
# condor/submit_estimations.py on the same condor-accessible node, and /web
# isn't mounted there -- /work is, so default the plots next to the rest of
# this ntupletag's shape output instead.
def _default_plot_dir(ntupletag, era, user, tag="tt_dy_weight"):
    return Path(f"/web/{user}/public_html/CMS_HTT/{ntupletag}/{tag}/ss-os") / era / CHANNEL

# Bottom-to-top stack order, matching plot_shapes_control.py's em/fully-classic
# convention (QCD, VV, W, TT..., DY... -- see plotting/process_ordering.py's
# ControlShapeBkgProcesses.channel_modification()), collapsed to the merged
# groups fit_weights()/collect_region_yields() actually use.
_PLOT_GROUPS = [
    ("QCD", _QCD_PARTS), ("VV", _VV_PARTS), ("W", _W_PARTS),
    ("TT", _TT_PARTS), ("DY", _DY_PARTS),
]


def plot_regions(rootfile, era, output_dir, log_y=False):
    """
    One control-style stack+ratio plot per tt_dy_weight region (REGIONS),
    grouped the same way fit_weights() sees them (merged TT/DY, no
    tau-fake-origin split) rather than the full breakdown
    plotting/plot_shapes_control.py normally draws -- these are meant to show
    exactly what goes into the k_TT/k_DY fit, region by region. Rendering
    itself is shared with that script's draw_stack_plot(), so the look
    (CMS label, legend, ratio panel, ...) matches the rest of the framework's
    control plots.
    """
    from plotting.plot_shapes_control import (
        draw_stack_plot, _th1_to_numpy, PROCESS_COLOURS, legend_label_dict,
        lumi_label, CHANNEL_LABELS, _channel_x_labels,
    )

    out_dir = Path(output_dir)
    x_label = _channel_x_labels(CHANNEL).get(VARIABLE, VARIABLE)
    top_left_base = CHANNEL_LABELS.get(CHANNEL, CHANNEL)

    for region in REGIONS:
        stack_values, stack_labels, stack_colors = [], [], []
        edges, total_err2 = None, None
        for label, parts in _PLOT_GROUPS:
            y_sum, err2_sum = None, None
            for process in parts:
                e, y, yerr = _th1_to_numpy(_get_hist(rootfile, process, region))
                edges = e
                y_sum = y if y_sum is None else y_sum + y
                err2_sum = yerr**2 if err2_sum is None else err2_sum + yerr**2
            stack_values.append(y_sum)
            stack_labels.append(legend_label_dict.get(label, label))
            stack_colors.append(PROCESS_COLOURS.get(label, "#AAAAAA"))
            total_err2 = err2_sum if total_err2 is None else total_err2 + err2_sum

        _, y_data, yerr_data = _th1_to_numpy(_get_hist(rootfile, _DATA, region))

        draw_stack_plot(
            edges=edges,
            stack_values=stack_values,
            stack_labels=stack_labels,
            stack_colors=stack_colors,
            total_mc_err=np.sqrt(total_err2),
            x_label=x_label,
            top_left_label=f"{top_left_base}, {region}",
            top_right_label=lumi_label(era),
            out_dir=out_dir,
            fname=f"{CHANNEL}_{era}_{region}_{VARIABLE}",
            y_data=y_data,
            yerr_data=yerr_data,
            log_y=log_y,
        )


def closure_check(region_yields, k_tt, k_dy):
    residuals = {}
    for region in REGIONS:
        data_val, data_err = region_yields[region]["data"]
        pred = (
            k_tt * region_yields[region]["TT"][0]
            + k_dy * region_yields[region]["DY"][0]
            + region_yields[region]["fixed"][0]
        )
        pull = (data_val - pred) / data_err if data_err > 0 else float("nan")
        residuals[region] = {
            "data": data_val, "predicted": pred,
            "residual": data_val - pred, "pull": pull,
        }
    return residuals


def measure_era(ntupletag, era, user, make_plots=True, plot_output=None, tag="tt_dy_weight"):
    paths = build_shape_output_paths(ntupletag, user=user)
    shapes_path = Path(paths.output) / tag / "ss-os" / era / CHANNEL / "shapes.root"
    if not shapes_path.exists():
        logger.warning(f"[{era}] no shapes.root at {shapes_path} -- skipping")
        return None
    rootfile = ROOT.TFile.Open(str(shapes_path))
    if not rootfile or rootfile.IsZombie():
        logger.warning(f"[{era}] could not open {shapes_path} -- skipping")
        return None
    try:
        region_yields = collect_region_yields(rootfile)
        if make_plots:
            plot_regions(rootfile, era, output_dir=plot_output or _default_plot_dir(ntupletag, era, user, tag=tag))
    except KeyError as exc:
        logger.warning(
            f"[{era}] {exc} -- did you run condor/submit_estimations.py --do-qcd "
            f"on this tt_dy_weight tree yet? skipping"
        )
        return None
    finally:
        rootfile.Close()

    k_tt, k_tt_var, k_dy, k_dy_var = fit_weights_sequential(region_yields)
    residuals = closure_check(region_yields, k_tt, k_dy)

    k_tt_joint, k_dy_joint, cov_joint = fit_weights_joint(region_yields)

    return {
        "era": era,
        "k_TT": k_tt, "k_TT_err": k_tt_var ** 0.5,
        "k_DY": k_dy, "k_DY_err": k_dy_var ** 0.5,
        "k_TT_joint": k_tt_joint, "k_TT_joint_err": cov_joint[0, 0] ** 0.5,
        "k_DY_joint": k_dy_joint, "k_DY_joint_err": cov_joint[1, 1] ** 0.5,
        "region_yields": region_yields,
        "closure": {r: residuals[r] for r in CLOSURE_REGIONS},
        "residuals_all_regions": residuals,
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag, e.g. htt_260813_22-23.")
    parser.add_argument("--eras", required=True, help="Comma-separated eras to measure, e.g. 2022preEE,2022postEE,2023preBPix,2023postBPix.")
    parser.add_argument("--user", default=getpass.getuser(), help="Grid storage username (default: current user).")
    parser.add_argument("--output-file", default=None, help="Optional path to also write results as JSON.")
    parser.add_argument(
        "--tag", default="tt_dy_weight",
        help="condor/submit_shapes.py --tag used to produce the shapes.root files being read "
             "(output/<tag>/ss-os/<era>/em/shapes.root). Default 'tt_dy_weight' matches the "
             "original m_vis-Z-peak categorization; pass 'tt_dy_weight_pzeta' for the pzetamissvis-based one.",
    )
    parser.add_argument(
        "--no-plots", action="store_true",
        help="Skip drawing the per-region control plots (drawn to --plot-output, "
             "or /work/<user>/TAUER_shapes/<ntupletag>/plots/tt_dy_weight/ss-os/<era>/em/ "
             "by default).",
    )
    parser.add_argument(
        "--plot-output", default=None,
        help="Override the output directory for the per-region control plots "
             "(default: /work/<user>/TAUER_shapes/<ntupletag>/plots/tt_dy_weight/ss-os/<era>/em/).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    eras = [e.strip() for e in args.eras.split(",") if e.strip()]
    results = {}
    for era in eras:
        result = measure_era(
            args.ntupletag, era, args.user, tag=args.tag,
            make_plots=not args.no_plots, plot_output=args.plot_output,
        )
        if result is not None:
            results[era] = result

    print(f"\nSequential fit (primary -- TT from nbtag>=1, then DY with k_TT fixed):")
    print(f"{'era':<16}{'k_TT':>12}{'+/-':>10}{'k_DY':>12}{'+/-':>10}")
    for era, r in results.items():
        print(
            f"{era:<16}{r['k_TT']:>12.6f}{r['k_TT_err']:>10.6f}"
            f"{r['k_DY']:>12.6f}{r['k_DY_err']:>10.6f}"
        )

    print(f"\nJoint fit (cross-check -- all four regions fit at once):")
    print(f"{'era':<16}{'k_TT':>12}{'+/-':>10}{'k_DY':>12}{'+/-':>10}")
    for era, r in results.items():
        print(
            f"{era:<16}{r['k_TT_joint']:>12.6f}{r['k_TT_joint_err']:>10.6f}"
            f"{r['k_DY_joint']:>12.6f}{r['k_DY_joint_err']:>10.6f}"
        )

    print("\nClosure check (mixed regions, post-fit pulls -- want |pull| ~< a few):")
    for era, r in results.items():
        for region in CLOSURE_REGIONS:
            c = r["closure"][region]
            print(
                f"  [{era}] {region:<18} data={c['data']:>10.1f}  "
                f"predicted={c['predicted']:>10.1f}  "
                f"residual={c['residual']:>+9.1f}  pull={c['pull']:>+6.2f}"
            )

    print("\n# Suggested replacement for ttbar_em_weight()'s ratio_em dict, per era")
    print("# (k_TT plays the same role as ratio_em; compare against current values before swapping in):")
    for era, r in results.items():
        print(f'# {era}: k_TT = "{r["k_TT"]:.6f}"  # +/- {r["k_TT_err"]:.6f}    k_DY = {r["k_DY"]:.6f}  # +/- {r["k_DY_err"]:.6f}')

    if args.output_file:

        def _clean(obj):
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_clean(v) for v in obj]
            if isinstance(obj, (np.floating, np.integer)):
                return float(obj)
            return obj

        with open(args.output_file, "w") as f:
            json.dump(_clean(results), f, indent=2)
        logger.info(f"Wrote results to {args.output_file}")


if __name__ == "__main__":
    main()
