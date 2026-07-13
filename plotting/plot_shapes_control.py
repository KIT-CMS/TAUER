#!/usr/bin/env python
"""
Control-plot and shape comparison plotting using mplhep (CMS style).
Replaces the Dumbledraw-based plotting of smhtt_ul.
"""
import argparse
import logging
import os
from pathlib import Path


import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
import ROOT
import yaml

from config.logging_setup_configs import setup_logging
from plotting.process_ordering import ControlShapeBkgProcesses

hep.style.use(hep.style.CMS)

logger = setup_logging(logger=logging.getLogger(__name__))


# --- Color palette and legend label dictionary from smhtt_ul ---
PROCESS_COLOURS = {
    "ZTT":      "#FFCC66",
    "ZL":       "#336633",
    "ZJ":       "#99CC66",
    "TTT":      "#FFCCFF",
    "TTL":      "#CC99CC",
    "TTJ":      "#996699",
    "TT":       "#996699",
    "VVT":      "#66CCCC",
    "VVL":      "#669999",
    "VVJ":      "#336666",
    "VV":       "#336666",
    "W":        "#FF6666",
    "QCD":      "#CCCCCC",
    "jetFakes": "#B97A57",
    "jetFakesEMB": "#B97A57",
    "QCDEMB":   "#CCCCCC",
    "EMB":      "#E8E8E8",
    "ggH125":   "#FF0000",
    "qqH125":   "#0000FF",
    "VH125":    "#00CC00",
    "ttH125":   "#990099",
}

# Legend label dictionary (from smhtt_ul Dumbledraw/labels.yaml legend_label)
legend_label_dict = {
    "ZTT": "Z#rightarrow#tau#tau",
    "ZL": "Z#rightarrow ll (lep)",
    "ZJ": "Z#rightarrow ll (jet)",
    "TTT": "t#bar{t} (lep)",
    "TTL": "t#bar{t} (lep)",
    "TTJ": "t#bar{t} (jet)",
    "TT": "t#bar{t}",
    "VVT": "Diboson (lep)",
    "VVL": "Diboson (lep)",
    "VVJ": "Diboson (jet)",
    "VV": "Diboson",
    "W": "W+jets",
    "QCD": "QCD",
    "jetFakes": "jet#rightarrow#tau_{h}",
    "jetFakesEMB": "jet#rightarrow#tau_{h}",
    "QCDEMB": "QCD",
    "EMB": "Embedded",
    "ggH125": "gg#rightarrowH (125)",
    "qqH125": "qq#rightarrowH (125)",
    "VH125": "VH (125)",
    "ttH125": "ttH (125)",
}

# X label dictionary (partial, for demonstration; should be extended as needed)
x_label_dict = {
    "m_vis": "Visible di-#tau mass [GeV]",
    "pt_1": "Leading lepton p_{T} [GeV]",
    "pt_2": "Subleading lepton p_{T} [GeV]",
    "eta_1": "Leading lepton #eta",
    "eta_2": "Subleading lepton #eta",
    "mt_1": "Transverse mass m_{T} [GeV]",
}

ERA_LABELS = {
    "2022preEE":    r"2022 (pre-EE), 8.086 fb$^{-1}$",
    "2022postEE":   r"2022 (post-EE), 26.675 fb$^{-1}$",
    "2023preBPix":  r"2023 (pre-B$\mathit{Pix}$), 17.964 fb$^{-1}$",
    "2023postBPix": r"2023 (post-B$\mathit{Pix}$), 9.677 fb$^{-1}$",
    "2024":         r"2024, 109.817 fb$^{-1}$",
    "2025":         r"2025, 109.898 fb$^{-1}$",
}

CHANNEL_LABELS = {
    "et": r"$e\tau_h$",
    "mt": r"$\mu\tau_h$",
    "tt": r"$\tau_h\tau_h$",
    "em": r"$e\mu$",
}


def _th1_to_numpy(hist):
    n = hist.GetNbinsX()
    edges = np.array([hist.GetBinLowEdge(i + 1) for i in range(n)] + [hist.GetBinLowEdge(n) + hist.GetBinWidth(n)])
    y     = np.array([hist.GetBinContent(i + 1) for i in range(n)])
    yerr  = np.array([hist.GetBinError(i + 1)   for i in range(n)])
    return edges, y, yerr


def _get_hist(rootfile, dataset, channel, process, selection, variation, variable):
    # Use smhtt_ul-style key: {dataset}#{channel}-{process}-{selection}#{variation}#{variable}
    # Map process to correct ROOT key using _process_map
    from shapes.estimations.defaults import _process_map
    process_key = _process_map.get(process, process)
    # Only use {dataset}#{channel}-{process}#{variation}#{variable}
    name = f"{dataset}#{channel}{process_key}#{variation}#{variable}"
    h = rootfile.Get(name)
    if not h:
        print(f"[DEBUG] Histogram not found: {name}")
        return None
    return h.Clone()


def plot_control(
    rootfile: ROOT.TFile,
    channel: str,
    era: str,
    category: str,
    variable: str,
    process_config: ControlShapeBkgProcesses,
    output_dir: str,
    log_y: bool = False,
    blinded: bool = False,
):
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(7, 8), gridspec_kw={"height_ratios": [3, 1]}, sharex=True
    )

    bkg_hists  = {}
    sig_hists  = {}
    data_hist  = None

    # ── Collect background histograms ────────────────────────────────────────
    from shapes.estimations.defaults import _name_string, _process_map, _dataset_map

    bkg_processes = process_config()

    for proc in bkg_processes:
        if proc not in _process_map:
            continue
        ds   = _dataset_map.get(proc, proc)
        psel = "-" + _process_map[proc]
        sel  = ("-" + category) if category else ""
        h = _get_hist(rootfile, ds, channel, psel, sel, "Nominal", variable)
        if h:
            bkg_hists[proc] = h

    for sig_proc in ["ggH125", "qqH125"]:
        if sig_proc not in _process_map:
            continue
        ds   = _dataset_map.get(sig_proc, sig_proc)
        psel = "-" + _process_map[sig_proc]
        sel  = ("-" + category) if category else ""
        h = _get_hist(rootfile, ds, channel, psel, sel, "Nominal", variable)
        if h:
            sig_hists[sig_proc] = h

    # data
    data_key = f"data#{channel}-data{('-' + category) if category else ''}#Nominal#{variable}"
    data_h_raw = rootfile.Get(data_key)
    if data_h_raw and not blinded:
        data_hist = data_h_raw.Clone()

    if not bkg_hists:
        logger.warning(f"No backgrounds found for {channel}/{category}/{variable}. Skipping.")
        plt.close(fig)
        return

    # ── Stack backgrounds ────────────────────────────────────────────────────
    stack_order = [p for p in bkg_processes if p in bkg_hists]
    edges, _, _ = _th1_to_numpy(list(bkg_hists.values())[0])
    x_centers   = 0.5 * (edges[:-1] + edges[1:])

    stack_values = []

    stack_labels = []
    stack_colors = []
    for proc in stack_order:
        _, y, _ = _th1_to_numpy(bkg_hists[proc])
        stack_values.append(y)
        stack_labels.append(legend_label_dict.get(proc, proc))
        stack_colors.append(PROCESS_COLOURS.get(proc, "#AAAAAA"))


    hep.histplot(
        stack_values, edges,
        stack=True, histtype="fill",
        label=stack_labels, color=stack_colors,
        ax=ax_top,
    )

    # total MC uncertainty band
    total_mc = sum(stack_values)
    total_mc_err = np.sqrt(sum(
        np.array([bkg_hists[p].GetBinError(i + 1) ** 2 for i in range(len(x_centers))])
        for p in stack_order
    ))
    ax_top.bar(
        x_centers, 2 * total_mc_err, bottom=total_mc - total_mc_err,
        width=edges[1:] - edges[:-1], color="gray", alpha=0.35,
        hatch="///", linewidth=0, label="Stat. unc.",
    )

    # signals (scaled ×50)
    SIGNAL_SCALE = 50
    for sig, h in sig_hists.items():
        _, y_sig, _ = _th1_to_numpy(h)
        col = PROCESS_COLOURS.get(sig, "#FF0000")
        sig_label = legend_label_dict.get(sig, sig) + f" (×{SIGNAL_SCALE})"
        hep.histplot(
            y_sig * SIGNAL_SCALE, edges,
            histtype="step", linewidth=2, color=col,
            label=sig_label, ax=ax_top,
        )

    # data
    if data_hist:
        _, y_data, yerr_data = _th1_to_numpy(data_hist)
        ax_top.errorbar(
            x_centers, y_data, yerr=yerr_data,
            fmt="ko", markersize=4, linewidth=1.2, label="Data", zorder=10,
        )

    # ── Ratio panel ──────────────────────────────────────────────────────────
    if data_hist and total_mc.sum() > 0:
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio      = np.where(total_mc > 0, y_data / total_mc, 0.0)
            ratio_err  = np.where(total_mc > 0, yerr_data / total_mc, 0.0)
            mc_unc_rel = np.where(total_mc > 0, total_mc_err / total_mc, 0.0)
        ax_bot.errorbar(x_centers, ratio, yerr=ratio_err, fmt="ko", markersize=3, linewidth=1)
        ax_bot.bar(
            x_centers, 2 * mc_unc_rel, bottom=1.0 - mc_unc_rel,
            width=edges[1:] - edges[:-1], color="gray", alpha=0.35, hatch="///", linewidth=0,
        )
    ax_bot.axhline(1.0, color="black", linewidth=0.8)
    ax_bot.set_ylim(0.5, 1.5)
    ax_bot.set_ylabel("Data/MC")

    # ── Axes decoration ──────────────────────────────────────────────────────

    if log_y:
        ax_top.set_yscale("log")
        ax_top.set_ylim(bottom=0.1)
    else:
        ax_top.set_ylim(bottom=0)
    ax_top.set_ylabel("Events / bin", fontsize=16)
    ax_bot.set_xlabel(x_label_dict.get(variable, variable), fontsize=16)
    ax_top.legend(loc="upper right", ncol=2, fontsize=12, framealpha=0.7, handlelength=2.0, borderaxespad=0.8, labelspacing=0.4)


    hep.cms.label(
        ax=ax_top,
        label="Work in progress",
        data=bool(data_hist),
        lumi=ERA_LABELS.get(era, era),
        loc=0,
        fontsize=14,
    )
    ax_top.text(
        0.02, 0.96,
        f"{CHANNEL_LABELS.get(channel, channel)}, {category or 'inclusive'}",
        transform=ax_top.transAxes, va="top", fontsize=14,
    )


    # Save main stack plot
    fig.tight_layout()
    fname = f"{channel}_{era}_{category or 'inc'}_{variable}"
    for ext in ("png", "pdf"):
        out = Path(output_dir) / ext
        out.mkdir(parents=True, exist_ok=True)
        fig.savefig(out / f"{fname}.{ext}", bbox_inches="tight", dpi=150)
    logger.info(f"Saved plot: {fname}")
    plt.close(fig)

    # --- Save overlay plots for each process ---
    for highlight_proc in stack_order:
        fig_ol, (ax_top_ol, ax_bot_ol) = plt.subplots(
            2, 1, figsize=(7, 8), gridspec_kw={"height_ratios": [3, 1]}, sharex=True
        )
        # Stack as before
        hep.histplot(
            stack_values, edges,
            stack=True, histtype="fill",
            label=stack_labels, color=stack_colors,
            ax=ax_top_ol,
        )
        # Highlight the selected process
        idx = stack_order.index(highlight_proc)
        _, y_highlight, _ = _th1_to_numpy(bkg_hists[highlight_proc])
        ax_top_ol.step(
            x_centers, y_highlight, where="mid",
            color="red", linewidth=2.5, label=f"{legend_label_dict.get(highlight_proc, highlight_proc)} (highlighted)"
        )
        # MC unc band
        ax_top_ol.bar(
            x_centers, 2 * total_mc_err, bottom=total_mc - total_mc_err,
            width=edges[1:] - edges[:-1], color="gray", alpha=0.35,
            hatch="///", linewidth=0, label="Stat. unc.",
        )
        # Signals
        for sig, h in sig_hists.items():
            _, y_sig, _ = _th1_to_numpy(h)
            col = PROCESS_COLOURS.get(sig, "#FF0000")
            sig_label = legend_label_dict.get(sig, sig) + f" (×{SIGNAL_SCALE})"
            hep.histplot(
                y_sig * SIGNAL_SCALE, edges,
                histtype="step", linewidth=2, color=col,
                label=sig_label, ax=ax_top_ol,
            )
        # Data
        if data_hist:
            _, y_data, yerr_data = _th1_to_numpy(data_hist)
            ax_top_ol.errorbar(
                x_centers, y_data, yerr=yerr_data,
                fmt="ko", markersize=4, linewidth=1.2, label="Data", zorder=10,
            )
        # Ratio panel
        if data_hist and total_mc.sum() > 0:
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio      = np.where(total_mc > 0, y_data / total_mc, 0.0)
                ratio_err  = np.where(total_mc > 0, yerr_data / total_mc, 0.0)
                mc_unc_rel = np.where(total_mc > 0, total_mc_err / total_mc, 0.0)
            ax_bot_ol.errorbar(x_centers, ratio, yerr=ratio_err, fmt="ko", markersize=3, linewidth=1)
            ax_bot_ol.bar(
                x_centers, 2 * mc_unc_rel, bottom=1.0 - mc_unc_rel,
                width=edges[1:] - edges[:-1], color="gray", alpha=0.35, hatch="///", linewidth=0,
            )
        ax_bot_ol.axhline(1.0, color="black", linewidth=0.8)
        ax_bot_ol.set_ylim(0.5, 1.5)
        ax_bot_ol.set_ylabel("Data/MC")
        # Decorations
        if log_y:
            ax_top_ol.set_yscale("log")
            ax_top_ol.set_ylim(bottom=0.1)
        else:
            ax_top_ol.set_ylim(bottom=0)
        ax_top_ol.set_ylabel("Events / bin", fontsize=16)
        ax_bot_ol.set_xlabel(x_label_dict.get(variable, variable), fontsize=16)
        ax_top_ol.legend(loc="upper right", ncol=2, fontsize=12, framealpha=0.7, handlelength=2.0, borderaxespad=0.8, labelspacing=0.4)
        hep.cms.label(
            ax=ax_top_ol,
            label="Work in progress",
            data=bool(data_hist),
            lumi=ERA_LABELS.get(era, era),
            loc=0,
            fontsize=14,
        )
        ax_top_ol.text(
            0.02, 0.96,
            f"{CHANNEL_LABELS.get(channel, channel)}, {category or 'inclusive'}",
            transform=ax_top_ol.transAxes, va="top", fontsize=14,
        )
        # Save overlay plot
        fig_ol.tight_layout()
        fname_ol = f"{channel}_{era}_{category or 'inc'}_{variable}_oplot_{highlight_proc}"
        for ext in ("png", "pdf"):
            out = Path(output_dir) / ext
            out.mkdir(parents=True, exist_ok=True)
            fig_ol.savefig(out / f"{fname_ol}.{ext}", bbox_inches="tight", dpi=150)
        logger.info(f"Saved overlay plot: {fname_ol}")
        plt.close(fig_ol)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Plot control shapes for TauHarvest.")
    parser.add_argument("--input",    required=True, type=str, help="Input ROOT shapes file.")
    parser.add_argument("--output",   required=True, type=str, help="Output directory.")
    parser.add_argument("--era",      required=True, type=str, help="Era.")
    parser.add_argument(
        "--channels", default=["et", "mt", "tt"],
        type=lambda s: s.split(","),
    )
    parser.add_argument(
        "--variables", default=["m_vis"],
        type=lambda s: s.split(","),
    )
    parser.add_argument("--log-y",   action="store_true")
    parser.add_argument("--blinded", action="store_true")
    parser.add_argument(
        "--embedding",    action="store_true",
        help="Use embedding for ZTT estimate."
    )
    parser.add_argument(
        "--fake-factor",  action="store_true",
        help="Use fake factor for jet fakes."
    )
    return parser.parse_args()


def main(args):
    rootfile = ROOT.TFile(args.input, "read")
    if rootfile.IsZombie():
        raise RuntimeError(f"Cannot open {args.input}")

    # Load variables.yaml and get all variables except flags
    with open(os.path.join(os.path.dirname(__file__), '../config/variables.yaml')) as f:
        variables_yaml = yaml.safe_load(f)
    all_vars = set(variables_yaml.get('output_features', []))
    flag_vars = set(variables_yaml.get('flags', []))
    plot_vars = sorted(all_vars - flag_vars)

    for channel in args.channels:
        proc_config = ControlShapeBkgProcesses(
            embedding=args.embedding,
            fake_factor=args.fake_factor,
            nlo=False,
            channel=channel,
            selection_option="CR",
        )
        # Infer available categories from file keys
        categories = set()
        for key in rootfile.GetListOfKeys():
            parts = key.GetName().split("#")
            if len(parts) < 2:
                continue
            sel = parts[1]
            if sel.startswith(channel + "-"):
                cat = sel[len(channel) + 1:]
                # strip process suffix
                cat_parts = cat.split("-")
                if len(cat_parts) > 1:
                    categories.add(cat_parts[-1])

        if not categories:
            categories = {""}  # run with no category suffix

        for category in sorted(categories):
            for variable in plot_vars:
                plot_control(
                    rootfile=rootfile,
                    channel=channel,
                    era=args.era,
                    category=category,
                    variable=variable,
                    process_config=proc_config,
                    output_dir=args.output,
                    log_y=args.log_y,
                    blinded=args.blinded,
                )
    rootfile.Close()


if __name__ == "__main__":
    args = parse_arguments()
    logger = setup_logging(logger=logging.getLogger(__name__))
    main(args)
