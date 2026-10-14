#!/usr/bin/env python
"""
Control-plot and shape comparison plotting using mplhep (CMS style).
"""
import argparse
import importlib
import logging
import os
from pathlib import Path


import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import mplhep as hep
import numpy as np
import ROOT
import yaml

from config.analysis import ACTIVE_ANALYSIS, RUN2_ERAS, RUN3_ERAS, get_center_of_mass, get_data_eras, get_luminosity
from config.logging_setup_configs import setup_logging
from plotting.process_ordering import ControlShapeBkgProcesses
from plotting.systematics_band import shape_systematic_uncertainty
from shapes import naming

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


# --- Color palette for stack fill colours ---
PROCESS_COLOURS = {
    "ZTT":      "#ffa90e",
    "ZL":       "#3f90da",
    "ZJ":       "#9abbd9",
    "TTT":      "#a963d1",
    "TTL":      "#832db6",
    "TTJ":      "#c59ade",
    "TT":       "#832db6",
    "VVT":      "#69c7bc",
    "VVL":      "#27ad9e",
    "VVJ":      "#92dadd",
    "VV":       "#92dadd",
    "W":        "#e76300",
    "QCD":      "#b9ac70",
    # Merged DY (ZTT+ZL+ZJ, unsplit); reuses ZTT's colour.
    "DY":       "#ffa90e",
    "jetFakes": "#94a4a2",
    "jetFakesEMB": "#94a4a2",
    "QCDEMB":   "#b9ac70",
    "EMB":      "#ffa90e",
}

# Legend labels, as matplotlib mathtext
legend_label_dict = {
    "ZTT": r"Z$\rightarrow\tau\tau$",
    "ZL": r"Z$\rightarrow$ll",
    "ZJ": r"Z$\rightarrow$ll (jet$\rightarrow\tau_h$)",
    "TTT": r"t$\bar{t}$ ($\tau\tau$)",
    "TTL": r"t$\bar{t}$ (l$\tau$)",
    "TTJ": r"t$\bar{t}$ (jet$\rightarrow\tau_h$)",
    "TT": r"t$\bar{t}$",
    "VVT": r"Diboson ($\tau\tau$)",
    "VVL": r"Diboson (l$\tau$)",
    "VVJ": r"Diboson (jet$\rightarrow\tau_h$)",
    "VV": "Diboson",
    "W": "W+jets",
    "QCD": "QCD multijet",
    "DY": r"Z/$\gamma^*\rightarrow$ll",
    "jetFakes": r"Jet$\rightarrow\tau_h$",
    "jetFakesEMB": r"Jet$\rightarrow\tau_h$",
    "QCDEMB": "QCD multijet",
    "EMB": r"$\tau$ embedded",
}

_JET1 = r"\text{Jet}_1"
_JET2 = r"\text{Jet}_2"

_COMMON_X_LABELS = {
    "jpt_1": r"Leading jet $p_T$ [GeV]",
    "jpt_2": r"Subleading jet $p_T$ [GeV]",
    "jeta_1": r"Leading jet $\eta$",
    "jeta_2": r"Subleading jet $\eta$",
    "deltaEta_jj": r"$\Delta\eta(\mathrm{jet}_1,\mathrm{jet}_2)$",
    "deltaR_jj": r"$\Delta R(\mathrm{jet}_1,\mathrm{jet}_2)$",
    "deltaEta_12jj": r"$\Delta\eta(\ell_1\ell_2,\mathrm{jet}_1\mathrm{jet}_2)$",
    "deltaR_12jj": r"$\Delta R(\ell_1\ell_2,\mathrm{jet}_1\mathrm{jet}_2)$",
    "m_vis": r"Visible di-$\tau$ mass [GeV]",
    "pt_vis": r"Visible di-$\tau$ $p_T$ [GeV]",
    "mjj": r"Di-jet mass $m_{jj}$ [GeV]",
    "pt_dijet": r"Di-jet $p_T$ [GeV]",
    "mt_tot": r"Total transverse mass $m_T^{tot}$ [GeV]",
    "pt_tt": r"$p_T(\tau\tau)$ [GeV]",
    "pt_ttjj": r"$p_T(\tau\tau + \mathrm{di-jet})$ [GeV]",
    "puppimet": r"Missing transverse energy [GeV]",
    "nbtag": "Number of b-tagged jets",
    "njets": "Number of jets",
}

# Per-channel leading/subleading lepton naming (mm/em/mt/et/tt use "Muon"/"Electron"/
# "Hadronic Tau" depending on slot).
_CHANNEL_LEPTONS = {
    "mt": (r"Muon", r"\tau_h"),
    "et": (r"Electron", r"\tau_h"),
    "tt": (r"Leading $\tau_h$", r"Subleading $\tau_h$"),
    "em": (r"Electron", r"Muon"),
    "mm": (r"Leading muon", r"Subleading muon"),
    "ee": (r"Leading electron", r"Subleading electron"),
}


def _channel_x_labels(channel: str) -> dict:
    lep1, lep2 = _CHANNEL_LEPTONS.get(channel, (r"\ell_1", r"\ell_2"))
    lep1_tex = lep1 if lep1.startswith(("Muon", "Electron", "Leading", "Subleading")) else f"${lep1}$"
    lep2_tex = lep2 if lep2.startswith(("Muon", "Electron", "Leading", "Subleading")) else f"${lep2}$"
    labels = dict(_COMMON_X_LABELS)
    labels.update({
        "pt_1": f"{lep1_tex} $p_T$ [GeV]",
        "pt_2": f"{lep2_tex} $p_T$ [GeV]",
        "eta_1": f"{lep1_tex} $\\eta$",
        "eta_2": f"{lep2_tex} $\\eta$",
        "mass_1": f"{lep1_tex} mass [GeV]",
        "mass_2": f"{lep2_tex} mass [GeV]",
        "mt_1": f"Transverse mass $m_T$({lep1_tex}, $\\slash{{E}}_T$) [GeV]",
        "mt_2": f"Transverse mass $m_T$({lep2_tex}, $\\slash{{E}}_T$) [GeV]",
        "tau_decaymode_1": f"{lep1_tex} decay mode",
        "tau_decaymode_2": f"{lep2_tex} decay mode",
        "q_1": f"{lep1_tex} charge",
        "q_2": f"{lep2_tex} charge",
        "iso_1": f"{lep1_tex} isolation",
        "iso_2": f"{lep2_tex} isolation",
        "deltaEta_ditaupair": f"$\\Delta\\eta$({lep1_tex}, {lep2_tex})",
        "deltaR_ditaupair": f"$\\Delta R$({lep1_tex}, {lep2_tex})",
        "deltaEta_1j1": f"$\\Delta\\eta$({lep1_tex}, $\\mathrm{{jet}}_1$)",
        "deltaEta_1j2": f"$\\Delta\\eta$({lep1_tex}, $\\mathrm{{jet}}_2$)",
        "deltaEta_2j1": f"$\\Delta\\eta$({lep2_tex}, $\\mathrm{{jet}}_1$)",
        "deltaEta_2j2": f"$\\Delta\\eta$({lep2_tex}, $\\mathrm{{jet}}_2$)",
        "deltaR_1j1": f"$\\Delta R$({lep1_tex}, $\\mathrm{{jet}}_1$)",
        "deltaR_1j2": f"$\\Delta R$({lep1_tex}, $\\mathrm{{jet}}_2$)",
        "deltaR_2j1": f"$\\Delta R$({lep2_tex}, $\\mathrm{{jet}}_1$)",
        "deltaR_2j2": f"$\\Delta R$({lep2_tex}, $\\mathrm{{jet}}_2$)",
    })
    return labels


ERA_YEAR_LABEL = {
    "2016preVFP":   "2016 preVFP",
    "2016postVFP":  "2016 postVFP",
    "2017":         "2017",
    "2018":         "2018",
    "2022preEE":    "2022 preEE",
    "2022postEE":   "2022 postEE",
    "2023preBPix":  "2023 preBPix",
    "2023postBPix": "2023 postBPix",
    "2024":         "2024",
    "2025":         "2025",
    "2026":         "2026",
}


def lumi_label(era: str) -> str:
    """e.g. '8.08 fb$^{-1}$ (2022 preEE, 13.6 TeV)'."""
    if era not in RUN2_ERAS and era not in RUN3_ERAS:
        logger.warning(f"Era {era!r} not in RUN2_ERAS/RUN3_ERAS; using it verbatim in the lumi label.")
        return era
    com = get_center_of_mass(era)
    com_str = str(int(com)) if com == int(com) else str(com)
    # merged data eras (DATA_ERA_MERGE) show up as "2025+2026" with the summed lumi
    year = "+".join(ERA_YEAR_LABEL.get(e, e) for e in get_data_eras(era))
    return f"{get_luminosity(era):.2f} fb$^{{-1}}$ ({year}, {com_str} TeV)"


CHANNEL_LABELS = {
    "et": r"$e\tau_h$",
    "mt": r"$\mu\tau_h$",
    "tt": r"$\tau_h\tau_h$",
    "em": r"$e\mu$",
}

# plotted process -> histogram process, the embedding estimates are the same jetFakes/QCD histograms
HISTOGRAM_PROCESSES = {"QCDEMB": "QCD", "jetFakesEMB": "jetFakes"}


def _th1_to_numpy(hist):
    n = hist.GetNbinsX()
    edges = np.array([hist.GetBinLowEdge(i + 1) for i in range(n)] + [hist.GetBinLowEdge(n) + hist.GetBinWidth(n)])
    y     = np.array([hist.GetBinContent(i + 1) for i in range(n)])
    yerr  = np.array([hist.GetBinError(i + 1)   for i in range(n)])
    return edges, y, yerr


def _get_hist(rootfile, process, channel, variable, category="", systematic=None):
    h = rootfile.Get(naming.path(variable, channel, HISTOGRAM_PROCESSES.get(process, process), category or None, systematic=systematic))
    if not h:
        logger.debug(f"Histogram not found: {variable}/{channel}/{process} (category={category!r}, systematic={systematic})")
        return None
    return h.Clone()


def draw_stack_plot(
    edges: np.ndarray,
    stack_values: list,
    stack_labels: list,
    stack_colors: list,
    total_mc_err: np.ndarray,
    x_label: str,
    top_left_label: str,
    top_right_label: str,
    out_dir: str,
    fname: str,
    y_data: np.ndarray = None,
    yerr_data: np.ndarray = None,
    extra_steps: list = None,
    log_y: bool = False,
    mc_err_label: str = "Bkg. stat. unc.",
):
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(6.6, 6.6), gridspec_kw={"height_ratios": [4, 1.2], "hspace": 0.03}, sharex=True
    )

    x_centers  = 0.5 * (edges[:-1] + edges[1:])
    bin_widths = edges[1:] - edges[:-1]

    hep.histplot(
        stack_values, edges,
        stack=True, histtype="fill",
        label=stack_labels, color=stack_colors,
        edgecolor="black", linewidth=0.4,
        ax=ax_top,
    )

    # total MC uncertainty band
    total_mc = sum(stack_values)
    ax_top.bar(
        x_centers, 2 * total_mc_err, bottom=total_mc - total_mc_err,
        width=bin_widths, color="gray", alpha=0.25,
        hatch="//", edgecolor="#999999", linewidth=0, label=mc_err_label,
    )

    # extra step histograms (e.g. signals), one fixed scale factor per curve
    for step in extra_steps or []:
        hep.histplot(
            step["y"], edges,
            histtype="step", linewidth=1.8, color=step["color"],
            label=step["label"], ax=ax_top,
        )

    # data. Same marker size in both panels.
    DATA_MARKERSIZE = 3.2
    if y_data is not None:
        ax_top.errorbar(
            x_centers, y_data, yerr=yerr_data,
            fmt="ko", markersize=DATA_MARKERSIZE, linewidth=1.2, label="Observed", zorder=10,
        )

    # ── Ratio panel ──────────────────────────────────────────────────────────
    if y_data is not None and total_mc.sum() > 0:
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio      = np.where(total_mc > 0, y_data / total_mc, 0.0)
            ratio_err  = np.where(total_mc > 0, yerr_data / total_mc, 0.0)
            mc_unc_rel = np.where(total_mc > 0, total_mc_err / total_mc, 0.0)
        ax_bot.errorbar(x_centers, ratio, yerr=ratio_err, fmt="ko", markersize=DATA_MARKERSIZE, linewidth=1)
        ax_bot.bar(
            x_centers, 2 * mc_unc_rel, bottom=1.0 - mc_unc_rel,
            width=bin_widths, color="gray", alpha=0.25,
            hatch="//", edgecolor="#999999", linewidth=0,
        )
    ax_bot.axhline(1.0, color="black", linewidth=0.8)
    ax_bot.set_ylim(0.5, 1.5)
    ax_bot.set_yticks([0.6, 0.8, 1.0, 1.2, 1.4])
    ax_bot.grid(axis="y", linestyle=":", linewidth=0.6, color="gray")
    ax_bot.set_ylabel("Data/MC", fontsize=14, loc="center")

    # ── Axes decoration ──────────────────────────────────────────────────────
    max_stack = total_mc.max() if len(total_mc) else 0.0
    max_data  = y_data.max() if y_data is not None and len(y_data) else 0.0
    max_val   = max(max_stack, max_data, 1e-9)

    ax_top.set_ylabel(r"$N_{\mathrm{events}}$", fontsize=15)

    if log_y:
        ax_top.set_yscale("log")
        ax_top.set_ylim(0.1, max_val * 300)
    else:
        ax_top.set_ylim(0, max_val * 1.8)
        ax_top.yaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=True))
        ax_top.ticklabel_format(axis="y", style="sci", scilimits=(0, 3))
        ax_top.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5))
        fig.canvas.draw()
        offset_str = ax_top.yaxis.get_offset_text().get_text()
        ax_top.yaxis.get_offset_text().set_visible(False)
        if offset_str:
            label_bbox = ax_top.yaxis.label.get_window_extent(renderer=fig.canvas.get_renderer())
            label_x_axes = ax_top.transAxes.inverted().transform(
                ((label_bbox.x0 + label_bbox.x1) / 2, 0)
            )[0]
            ax_top.text(
                label_x_axes, 1.012, offset_str, transform=ax_top.transAxes,
                va="bottom", ha="center", fontsize=13,
            )

    ax_bot.set_xlabel(x_label, fontsize=15)

    # Crop the x-axis to the first/last bin with any content
    has_content = total_mc > 0
    if y_data is not None:
        has_content = has_content | (y_data > 0)
    if has_content.any():
        first_bin = np.argmax(has_content)
        last_bin  = len(has_content) - 1 - np.argmax(has_content[::-1])
        ax_top.set_xlim(edges[first_bin], edges[last_bin + 1])
    else:
        ax_top.set_xlim(edges[0], edges[-1])

    ax_top.legend(
        loc="upper right", ncol=2, fontsize=10, framealpha=0.0,
        handlelength=1.4, columnspacing=1.0, borderaxespad=0.6, labelspacing=0.35,
    )

    ax_top.text(
        0.0, 1.012, top_left_label,
        transform=ax_top.transAxes, va="bottom", ha="left", fontsize=15,
    )
    ax_top.text(
        1.0, 1.012, top_right_label,
        transform=ax_top.transAxes, va="bottom", ha="right", fontsize=15,
    )

    ax_top.text(
        0.03, 0.945, "Private work (CMS data)", transform=ax_top.transAxes,
        va="top", ha="left", fontsize=11, fontstyle="italic",
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(out / f"{fname}.{ext}", bbox_inches="tight", dpi=150)
    logger.info(f"Saved plot: {fname}")
    plt.close(fig)


try:
    _analysis_plot = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.plotting.plot_stxs")
except ModuleNotFoundError:
    _analysis_plot = None
PROCESS_COLOURS.update(getattr(_analysis_plot, "SIGNAL_COLORS", {}))
legend_label_dict.update(getattr(_analysis_plot, "SIGNAL_LABELS", {}))
_SIGNALS = getattr(_analysis_plot, "CONTROL_SIGNALS", ())
_SIGNAL_SCALES = getattr(_analysis_plot, "SIGNAL_SCALES", {})


def plot_control(
    rootfile: ROOT.TFile,
    channel: str,
    era: str,
    variable: str,
    process_config: ControlShapeBkgProcesses,
    output_dir: str,
    log_y: bool = False,
    blinded: bool = False,
    category: str = "",
    show_signal: bool = True,
    include_systematics: bool = True,
):
    bkg_hists  = {}
    sig_hists  = {}
    data_hist  = None

    # ── Collect background histograms ────────────────────────────────────────
    bkg_processes = process_config()

    for proc in bkg_processes:
        h = _get_hist(rootfile, proc, channel, variable, category=category)
        if h:
            bkg_hists[proc] = h

    if show_signal:
        for sig_proc in _SIGNALS:
            h = _get_hist(rootfile, sig_proc, channel, variable, category=category)
            if h and h.Integral() > 0:
                sig_hists[sig_proc] = h

    if not blinded:
        data_hist = _get_hist(rootfile, naming.DATA, channel, variable, category=category)

    if not bkg_hists:
        where = f"{channel}/{category}/{variable}" if category else f"{channel}/{variable}"
        logger.warning(f"No backgrounds found for {where}. Skipping.")
        return

    # ── Stack backgrounds ────────────────────────────────────────────────────
    stack_order = [p for p in bkg_processes if p in bkg_hists]
    edges, _, _ = _th1_to_numpy(list(bkg_hists.values())[0])

    stack_values = []
    stack_labels = []
    stack_colors = []
    for proc in stack_order:
        _, y, _ = _th1_to_numpy(bkg_hists[proc])
        stack_values.append(y)
        stack_labels.append(legend_label_dict.get(proc, proc))
        stack_colors.append(PROCESS_COLOURS.get(proc, "#AAAAAA"))

    n_bins = len(stack_values[0])
    stat_err = np.sqrt(sum(
        np.array([bkg_hists[p].GetBinError(i + 1) ** 2 for i in range(n_bins)])
        for p in stack_order
    ))

    if include_systematics:
        shape_err, found_systematics = shape_systematic_uncertainty(
            rootfile=rootfile,
            channel=channel,
            era=era,
            variable=variable,
            bkg_hists=bkg_hists,
            n_bins=n_bins,
            category=category,
        )
        total_mc_err = np.sqrt(stat_err ** 2 + shape_err ** 2)
        if found_systematics:
            mc_err_label = "Bkg. unc. (stat" + r" $\oplus$" + " syst.)"
        else:
            logger.warning(
                f"--no-systematics not set, but no shape-systematics were found "
                f"for {channel}/{variable} (category={category!r}) -- input shapes were likely "
                f"produced with --skip-systematics. Labeling the band as stat-only."
            )
            mc_err_label = "Bkg. stat. unc."
    else:
        total_mc_err = stat_err
        mc_err_label = "Bkg. stat. unc."

    extra_steps = []
    for sig, h in sig_hists.items():
        _, y_sig, _ = _th1_to_numpy(h)
        scale = _SIGNAL_SCALES.get(sig, 1)
        extra_steps.append({
            "y": y_sig * scale,
            "color": PROCESS_COLOURS.get(sig, "#FF0000"),
            "label": f"{scale}" + r"$\times$" + legend_label_dict.get(sig, sig),
        })

    y_data, yerr_data = None, None
    if data_hist:
        _, y_data, yerr_data = _th1_to_numpy(data_hist)

    draw_stack_plot(
        edges=edges,
        stack_values=stack_values,
        stack_labels=stack_labels,
        stack_colors=stack_colors,
        total_mc_err=total_mc_err,
        x_label=_channel_x_labels(channel).get(variable, variable),
        top_left_label=CHANNEL_LABELS.get(channel, channel) + (f" ({category})" if category else ""),
        top_right_label=lumi_label(era),
        out_dir=Path(output_dir) / channel / category if category else Path(output_dir) / channel,
        fname=f"Run{era}_{channel}__{variable}",
        y_data=y_data,
        yerr_data=yerr_data,
        extra_steps=extra_steps,
        log_y=log_y,
        mc_err_label=mc_err_label,
    )


def parse_arguments():
    parser = argparse.ArgumentParser(description="Plot control shapes for TAUER.")
    parser.add_argument("--input-file", required=True, type=str, help="Input ROOT shapes file.")
    parser.add_argument("--output-dir", required=True, type=str, help="Output directory.")
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
    parser.add_argument(
        "--no-signal", dest="show_signal", action="store_false",
        help="Don't overlay signal step histograms (default: shown)."
    )
    parser.add_argument(
        "--no-systematics", dest="include_systematics", action="store_false",
        help="Don't fold shape systematics into the background uncertainty band (default: "
             "included, quadrature-summed with MC stat. unc. -- see plotting/systematics_band.py "
             "for the pre-fit-only caveat). Falls back to stat.-only if unset."
    )
    parser.add_argument(
        "--categories", default=None,
        type=lambda s: s.split(","),
        help="Comma-separated category names to plot, one output subdirectory per category "
             "(e.g. 'njets0,njets1,njets2p' for --special-analysis NjetsControl shapes -- see "
             "shapes/special/njets_control_categories.py's _regions). Default: no category "
             "dimension, i.e. plain control-plot shapes (matches every prior invocation)."
    )
    return parser.parse_args()


def main(args):
    # Checked before plotting anything, so a --process-selection batch that's still
    # partially running/failed fails loudly instead of silently missing a process. No-op
    # for an unsplit run (no expected_processes.json manifest).
    from common.shapes_merge import missing_processes

    missing = missing_processes(Path(args.input_file))
    if missing:
        raise RuntimeError(
            f"{args.input_file} is missing shapes for process(es) {missing} -- "
            f"condor/submit_shapes.py --process-selection split this batch into one job per "
            f"process and not all of them have completed/merged yet. Check condor_q for "
            f"still-running or failed jobs, then re-run shapes/do_estimations.py (or "
            f"condor/submit_estimations.py) once every job has finished so it can merge them, "
            f"before plotting. This applies to both the ss-os and ff shapes trees -- if you're "
            f"plotting the ff tree, make sure its ss-os sibling is complete too (ff reuse "
            f"depends on it, see condor/submit_shapes.py's --process-selection help)."
        )

    rootfile = ROOT.TFile(args.input_file, "read")
    if rootfile.IsZombie():
        raise RuntimeError(f"Cannot open {args.input_file}")

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
            channel=channel,
        )
        for category in (args.categories or [""]):
            for variable in plot_vars:
                plot_control(
                    rootfile=rootfile,
                    channel=channel,
                    era=args.era,
                    variable=variable,
                    process_config=proc_config,
                    output_dir=args.output_dir,
                    log_y=args.log_y,
                    blinded=args.blinded,
                    category=category,
                    show_signal=args.show_signal,
                    include_systematics=args.include_systematics,
                )
    rootfile.Close()


if __name__ == "__main__":
    # Self-nice regardless of invocation method (run.py already wraps this in
    # `nice -n 19`, but this also covers direct invocation). Safe to call even
    # when already niced (os.nice() clamps at the max of 19).
    os.nice(19)
    args = parse_arguments()
    logger = setup_logging(logger=logging.getLogger(__name__))
    main(args)
