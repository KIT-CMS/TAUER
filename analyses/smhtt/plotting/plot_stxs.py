#!/usr/bin/env python
import argparse
import logging
import os
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import mplhep as hep
import ROOT

from config.analysis import get_data_eras, get_era_luminosity, get_luminosity
from config.logging_setup_configs import setup_logging
from plotting.plot_shapes_control import (
    CHANNEL_LABELS,
    PROCESS_COLOURS,
    legend_label_dict,
    lumi_label,
    _get_hist,
    _th1_to_numpy,
)

SIGNAL_COLORS = {
    "ggH_htt125": "#5790fc",
    "qqH_htt125": "#bd1f01",
    "VH_htt125": "#e76300",
    "ttH_htt125": "#5c1a8a",
}
SIGNAL_LABELS = {
    "ggH_htt125": r"gg$\rightarrow$H (125)",
    "qqH_htt125": r"qq$\rightarrow$H (125)",
    "VH_htt125": "VH (125)",
    "ttH_htt125": "ttH (125)",
}
CONTROL_SIGNALS = tuple(SIGNAL_COLORS)
SIGNAL_SCALES = {
    "ggH_htt125": 10,
    "qqH_htt125": 100,
    "VH_htt125": 1000,
    "ttH_htt125": 1000,
}

hep.style.use(hep.style.CMS)
plt.rcParams.update({
    "font.size": 15,
    "axes.linewidth": 1.1,
    "xtick.major.width": 1.1,
    "ytick.major.width": 1.1,
    "xtick.minor.width": 0.9,
    "ytick.minor.width": 0.9,
    "xtick.major.size": 6.0,
    "ytick.major.size": 6.0,
    "xtick.minor.size": 3.0,
    "ytick.minor.size": 3.0,
    "xtick.labelsize": 13,
    "ytick.labelsize": 13,
    "legend.fontsize": 10.5,
})

logger = setup_logging(logger=logging.getLogger(__name__))

HTXS_VARIABLES = [
    "HTXS_stage1_2_fine_cat_pTjet30GeV",
]

HTXS_X_LABEL = "HTXS stage-1.2 bin"

PROCESS_X_RANGE = {
    "ggH_htt125": [(99, 130)],
    "qqH_htt125": [(199, 227)],
    "VH_htt125": [(299, 316), (399, 416)],
    "ttH_htt125": [(599, 610)],
}

REAL_ERAS = ["2022preEE", "2022postEE", "2023preBPix", "2023postBPix", "2024", "2025"]

PROXY_ERA_SOURCE = {"2026": "2025"}

DEFAULT_ERAS = REAL_ERAS + list(PROXY_ERA_SOURCE.keys())


def era_source(era: str) -> str:
    return PROXY_ERA_SOURCE.get(era, era)


def era_scale(era: str, variant: str) -> float:
    if era not in PROXY_ERA_SOURCE:
        return 1.0
    if variant == "scaled":
        return get_luminosity(era) / get_luminosity(PROXY_ERA_SOURCE[era])
    return 1.0


def era_lumi_text(era: str, variant: str) -> str:
    if era not in PROXY_ERA_SOURCE:
        return lumi_label(era)
    source = PROXY_ERA_SOURCE[era]
    if variant == "scaled":
        return f"{get_luminosity(era):.2f} fb$^{{-1}}$ ({era}, {source} MC lumi-scaled)"
    return f"{source} MC (unscaled event counts, labeled {era})"


def inclusive_lumi_text(eras: list, variant: str) -> str:
    if variant == "scaled":
        data_eras = {d for e in eras for d in get_data_eras(e)}
        total_lumi = sum(get_era_luminosity(e) for e in data_eras)
        return f"{total_lumi:.2f} fb$^{{-1}}$ (Inclusive)"
    return "Inclusive eras, unscaled event counts"


def collect_signal_hists(rootfile, channel, variable, scale=1.0):
    hists = {}
    for sig_proc in CONTROL_SIGNALS:
        h = _get_hist(rootfile, sig_proc, channel, variable)
        if h and h.Integral() > 0:
            h = h.Clone()
            h.SetDirectory(0)
            if scale != 1.0:
                h.Scale(scale)
            hists[sig_proc] = h
    return hists


def add_hist_dicts(dict_list):
    result = {}
    for d in dict_list:
        for proc, h in d.items():
            if proc not in result:
                result[proc] = h.Clone()
                result[proc].SetDirectory(0)
            else:
                result[proc].Add(h)
    return result


def render_stxs(sig_proc, h, output_stub, title_left, lumi_text, log_y=True):
    if h is None:
        return False

    edges, y, yerr = _th1_to_numpy(h)
    centers = 0.5 * (edges[:-1] + edges[1:])

    segments = PROCESS_X_RANGE.get(sig_proc, [(edges[0], edges[-1])])
    widths = [hi - lo for lo, hi in segments]
    max_val = max(
        (y[(centers >= lo) & (centers <= hi)].max(initial=0.0) for lo, hi in segments),
        default=0.0,
    )

    fig, axes = plt.subplots(
        1, len(segments), figsize=(7.0, 6.0), sharey=True,
        gridspec_kw={"width_ratios": widths, "wspace": 0.06},
    )
    if len(segments) == 1:
        axes = [axes]

    for ax, (x_lo, x_hi) in zip(axes, segments):
        ax.errorbar(
            centers, y, yerr=yerr,
            fmt="o", markersize=5.0, elinewidth=1.3, capsize=2.5,
            color=PROCESS_COLOURS.get(sig_proc, "#FF0000"),
            label=legend_label_dict.get(sig_proc, sig_proc),
        )
        ax.set_xlim(x_lo, x_hi)
        if log_y:
            ax.set_yscale("log")

    axes[0].set_ylabel(r"$N_{\mathrm{events}}$", fontsize=15)
    fig.supxlabel(HTXS_X_LABEL, fontsize=15, y=0.02)

    if log_y:
        axes[0].set_ylim(1e-1, max_val * 30 if max_val > 0 else 1e2)
    else:
        axes[0].set_ylim(0, max_val * 1.4 if max_val > 0 else 1.0)
        axes[0].yaxis.set_major_locator(mticker.MaxNLocator(nbins=5))

    if len(segments) > 1:
        for left_ax, right_ax in zip(axes[:-1], axes[1:]):
            left_ax.spines["right"].set_visible(False)
            right_ax.spines["left"].set_visible(False)
            right_ax.tick_params(left=False)
            d = 0.012
            kwargs = dict(transform=left_ax.transAxes, color="k", clip_on=False, linewidth=1.0)
            left_ax.plot([1 - d, 1 + d], [-d, d], **kwargs)
            left_ax.plot([1 - d, 1 + d], [1 - d, 1 + d], **kwargs)
            kwargs.update(transform=right_ax.transAxes)
            right_ax.plot([-d, d], [-d, d], **kwargs)
            right_ax.plot([-d, d], [1 - d, 1 + d], **kwargs)

    axes[-1].legend(
        loc="upper right", ncol=1, fontsize=11, framealpha=0.0,
        handlelength=1.4, borderaxespad=0.6, labelspacing=0.35,
    )

    axes[0].text(
        0.0, 1.012, title_left,
        transform=axes[0].transAxes, va="bottom", ha="left", fontsize=15,
    )
    axes[-1].text(
        1.0, 1.012, lumi_text,
        transform=axes[-1].transAxes, va="bottom", ha="right", fontsize=15,
    )
    axes[0].text(
        0.03, 0.945, "Private work (CMS simulation)", transform=axes[0].transAxes,
        va="top", ha="left", fontsize=15, fontstyle="italic",
    )

    output_stub.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(f"{output_stub}.{ext}", bbox_inches="tight", dpi=150)
    logger.info(f"Saved plot: {output_stub.name}")
    plt.close(fig)
    return True


def parse_arguments():
    parser = argparse.ArgumentParser(description="Plot STXS stage-1.2 signal yields for TAUER.")
    parser.add_argument(
        "--input-dir", required=True, type=str,
        help="Base directory holding <era>/<channel>/shapes.root STXS control-shapes "
             "(as produced by produce_shapes.py --control-plots --control-plot-set "
             "HTXS_stage1_2_cat_pTjet25GeV ...).",
    )
    parser.add_argument("--output-dir", required=True, type=str, help="Output plot directory.")
    parser.add_argument(
        "--eras", default=DEFAULT_ERAS, type=lambda s: s.split(","),
        help=f"Comma-separated list of eras to plot (default: {','.join(DEFAULT_ERAS)}).",
    )
    parser.add_argument(
        "--channels", default=["et", "mt", "tt", "em"],
        type=lambda s: s.split(","),
    )
    parser.add_argument(
        "--variables", default=HTXS_VARIABLES,
        type=lambda s: s.split(","),
    )
    parser.add_argument("--log-y", action="store_true", default=True)
    return parser.parse_args()


def main(args):
    rootfile_cache = {}

    def get_rootfile(source_era, channel):
        key = (source_era, channel)
        if key not in rootfile_cache:
            infile = Path(args.input_dir) / source_era / channel / "shapes.root"
            if not infile.exists():
                logger.warning(f"Missing shapes file: {infile}.")
                rootfile_cache[key] = None
            else:
                rf = ROOT.TFile(str(infile), "read")
                rootfile_cache[key] = None if rf.IsZombie() else rf
        return rootfile_cache[key]

    out_base = Path(args.output_dir)

    for variable in args.variables:
        for variant in ("scaled", "raw"):
            variant_suffix = "" if variant == "scaled" else "_raw"

            # Collect per-era, per-channel histogram dicts.
            per_era_channel = {}
            for era in args.eras:
                source = era_source(era)
                scale = era_scale(era, variant)
                per_channel = {}
                for channel in args.channels:
                    rf = get_rootfile(source, channel)
                    if rf is None:
                        continue
                    hists = collect_signal_hists(rf, channel, variable, scale=scale)
                    if hists:
                        per_channel[channel] = hists
                if per_channel:
                    per_era_channel[era] = per_channel

            # (1) per-era, per-channel
            for era, per_channel in per_era_channel.items():
                lumi_text = era_lumi_text(era, variant)
                era_dir = f"{era}{variant_suffix}"
                for channel, hists in per_channel.items():
                    for sig_proc, h in hists.items():
                        stub = out_base / era_dir / channel / f"{channel}_{era}_{sig_proc}_{variable}{variant_suffix}"
                        render_stxs(sig_proc, h, stub, CHANNEL_LABELS.get(channel, channel), lumi_text, log_y=args.log_y)

            sum_eras = [e for e in per_era_channel if e in REAL_ERAS]
            if variant == "scaled" and "2026" in per_era_channel:
                sum_eras.append("2026")

            if sum_eras:
                lumi_text = inclusive_lumi_text(sum_eras, variant)
                incl_dir = f"inclusive_eras{variant_suffix}"

                # (3) inclusive-eras, per-channel
                for channel in args.channels:
                    dicts = [per_era_channel[e][channel] for e in sum_eras if channel in per_era_channel[e]]
                    if not dicts:
                        continue
                    combined = add_hist_dicts(dicts)
                    for sig_proc, h in combined.items():
                        stub = out_base / incl_dir / channel / f"{channel}_inclusive_{sig_proc}_{variable}{variant_suffix}"
                        render_stxs(sig_proc, h, stub, CHANNEL_LABELS.get(channel, channel), lumi_text, log_y=args.log_y)

    for rf in rootfile_cache.values():
        if rf is not None:
            rf.Close()


if __name__ == "__main__":
    os.nice(19)
    args = parse_arguments()
    logger = setup_logging(logger=logging.getLogger(__name__))
    main(args)
