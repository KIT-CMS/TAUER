#!/usr/bin/env python
"""
Control-plot and shape comparison plotting using mplhep (CMS style).
Replaces the Dumbledraw-based plotting of smhtt_ul, matched visually
against the smhtt_ul reference (Dumbledraw/styles.py, colors.yaml, labels.yaml).
"""
import argparse
import logging
import os
from pathlib import Path


import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import mplhep as hep
import numpy as np
import ROOT
import yaml

from config.analysis import RUN2_ERAS, RUN3_ERAS, get_center_of_mass, get_luminosity
from config.logging_setup_configs import setup_logging
from plotting.process_ordering import ControlShapeBkgProcesses

hep.style.use(hep.style.CMS)

# The default CMS style is tuned for stand-alone 10x10in figures. Our canvas
# is smaller and has two stacked panels, so the stock font/linewidths render
# wildly oversized (tick numbers dwarfing the frame, spines ~2.5x thicker
# than the tick marks themselves) -- rescale everything down together so
# text, ticks and the frame stay proportionate to the smhtt_ul (ROOT/Dumbledraw)
# reference plots this is meant to match.
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


# --- Color palette, straight from smhtt_ul's Dumbledraw/colors.yaml, so the
# stack fill colours are identical to the reference plots. ---
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
    "jetFakes": "#94a4a2",
    "jetFakesEMB": "#94a4a2",
    "QCDEMB":   "#b9ac70",
    "EMB":      "#ffa90e",
    "ggH125":   "#5790fc",
    "qqH125":   "#bd1f01",
    "VH125":    "#e76300",
    "ttH125":   "#832db6",
}

# Legend labels, transcribed from smhtt_ul's Dumbledraw/labels.yaml
# legend_label block into matplotlib mathtext (ROOT TLatex's "#rightarrow"/
# "#bar{}" markup is not understood by matplotlib and was rendering as
# literal text, which is why labels used to overlap/overflow the legend box).
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
    "jetFakes": r"Jet$\rightarrow\tau_h$",
    "jetFakesEMB": r"Jet$\rightarrow\tau_h$",
    "QCDEMB": "QCD multijet",
    "EMB": r"$\tau$ embedded",
    "ggH125": r"gg$\rightarrow$H (125)",
    "qqH125": r"qq$\rightarrow$H (125)",
    "VH125": "VH (125)",
    "ttH125": "ttH (125)",
}

_JET1 = r"\text{Jet}_1"
_JET2 = r"\text{Jet}_2"

# X-axis labels. smhtt_ul's labels.yaml doesn't cover most of TauKITFlow's
# newer jet-lepton delta variables (deltaEta_1j1, deltaR_12jj, ...), so these
# are written fresh in matplotlib mathtext, following the same naming
# conventions (leading/subleading jet, di-jet, lepton legs) as the entries
# smhtt_ul does define for shared variables (jpt_1, mjj, pt_ttjj, ...).
_COMMON_X_LABELS = {
    "jpt_1": r"Leading jet $p_T$ [GeV]",
    "jpt_2": r"Subleading jet $p_T$ [GeV]",
    "jeta_1": r"Leading jet $\eta$",
    "jeta_2": r"Subleading jet $\eta$",
    "deltaEta_jj": r"$\Delta\eta(\mathrm{jet}_1,\mathrm{jet}_2)$",
    "deltaR_jj": r"$\Delta R(\mathrm{jet}_1,\mathrm{jet}_2)$",
    "deltaEta_12j1": r"$\Delta\eta(\ell_1\ell_2,\mathrm{jet}_1)$",
    "deltaEta_12j2": r"$\Delta\eta(\ell_1\ell_2,\mathrm{jet}_2)$",
    "deltaEta_12jj": r"$\Delta\eta(\ell_1\ell_2,\mathrm{jet}_1\mathrm{jet}_2)$",
    "deltaR_12j1": r"$\Delta R(\ell_1\ell_2,\mathrm{jet}_1)$",
    "deltaR_12j2": r"$\Delta R(\ell_1\ell_2,\mathrm{jet}_2)$",
    "deltaR_12jj": r"$\Delta R(\ell_1\ell_2,\mathrm{jet}_1\mathrm{jet}_2)$",
    "deltaEta_1j1": r"$\Delta\eta(\ell_1,\mathrm{jet}_1)$",
    "deltaEta_1j2": r"$\Delta\eta(\ell_1,\mathrm{jet}_2)$",
    "deltaEta_2j1": r"$\Delta\eta(\ell_2,\mathrm{jet}_1)$",
    "deltaEta_2j2": r"$\Delta\eta(\ell_2,\mathrm{jet}_2)$",
    "deltaR_1j1": r"$\Delta R(\ell_1,\mathrm{jet}_1)$",
    "deltaR_1j2": r"$\Delta R(\ell_1,\mathrm{jet}_2)$",
    "deltaR_2j1": r"$\Delta R(\ell_2,\mathrm{jet}_1)$",
    "deltaR_2j2": r"$\Delta R(\ell_2,\mathrm{jet}_2)$",
    "deltaEta_ditaupair": r"$\Delta\eta(\ell_1,\ell_2)$",
    "deltaR_ditaupair": r"$\Delta R(\ell_1,\ell_2)$",
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
    "q_1": r"Leading lepton charge",
    "q_2": r"Subleading lepton charge",
    "iso_1": r"Leading lepton isolation",
    "iso_2": r"Subleading lepton isolation",
}

# Per-channel leading/subleading lepton naming, mirroring smhtt_ul's
# channel-specific x_label_dict blocks (mm/em/mt/et/tt use "Muon"/"Electron"/
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
        "mt_1": r"Transverse mass $m_T(\ell_1, \slash{E}_T)$ [GeV]",
        "mt_2": r"Transverse mass $m_T(\ell_2, \slash{E}_T)$ [GeV]",
        "tau_decaymode_1": f"{lep1_tex} decay mode",
        "tau_decaymode_2": f"{lep2_tex} decay mode",
    })
    return labels


# Display text for the "year" part of the CMS lumi label. Covers both Run2
# (ported from smhtt_ul's Dumbledraw DrawLumi() era branch, plotting/
# plot_shapes_control.py there) and Run3. The numeric lumi (fb^-1) and
# center-of-mass energy (TeV) come from config.analysis.get_luminosity() /
# get_center_of_mass() -- single-sourced from config/samples.yaml, not
# duplicated here.
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
    """'8.08 fb$^{-1}$ (2022 preEE, 13.6 TeV)', matching smhtt_ul's DrawLumi() string."""
    if era not in RUN2_ERAS and era not in RUN3_ERAS:
        logger.warning(f"Era {era!r} not in RUN2_ERAS/RUN3_ERAS; using it verbatim in the lumi label.")
        return era
    com = get_center_of_mass(era)
    com_str = str(int(com)) if com == int(com) else str(com)
    return f"{get_luminosity(era):.2f} fb$^{{-1}}$ ({ERA_YEAR_LABEL.get(era, era)}, {com_str} TeV)"


CHANNEL_LABELS = {
    "et": r"$e\tau_h$",
    "mt": r"$\mu\tau_h$",
    "tt": r"$\tau_h\tau_h$",
    "em": r"$e\mu$",
}

# (dataset, process-selection) for the data-driven QCD estimates written by
# shapes/estimations/qcd.py:qcd_estimation() -- not in _process_map/_dataset_map
# since those only cover the raw MC samples from produce_shapes.py.
# "QCD" (is_embedding=False) is what --do-qcd (run.py's default when no FF
# friend-tree directory is configured) produces; "QCDEMB" is its embedding
# counterpart (is_embedding=True), included here for completeness.
_QCD_SS_OS_ESTIMATION_KEYS = {
    "QCD": ("QCDMC", "QCDMC"),
    "QCDEMB": ("QCD", "QCD"),
}

# Stage-0 signal datasets (dataset name in the shapes file, keyed by the
# process-selection suffix) and the display scale factor for each -- one
# fixed number per production mode so every non-empty signal is visible on
# the same linear axis as the backgrounds, following smhtt_ul's own choices
# (Dumbledraw/plot_shapes_control.py: 10x ggH, 100x qqH, 10000x VH, 1000x ttH
# -- roughly inverse to each mode's cross-section, so all four land at a
# similar height on the plot).
_SIGNAL_DATASETS = {
    "ggH125": "ggH",
    "qqH125": "qqH",
    "VH125": "VH",
    "ttH125": "ttH",
}
_SIGNAL_SCALES = {
    "ggH125": 10,
    "qqH125": 100,
    "VH125": 10000,
    "ttH125": 1000,
}


def _th1_to_numpy(hist):
    n = hist.GetNbinsX()
    edges = np.array([hist.GetBinLowEdge(i + 1) for i in range(n)] + [hist.GetBinLowEdge(n) + hist.GetBinWidth(n)])
    y     = np.array([hist.GetBinContent(i + 1) for i in range(n)])
    yerr  = np.array([hist.GetBinError(i + 1)   for i in range(n)])
    return edges, y, yerr


def _get_hist(rootfile, dataset, channel, process_selection, variation, variable):
    # smhtt_ul-style key: {dataset}#{channel}{-process_selection}#{variation}#{variable}
    # (see Dumbledraw/rootfile_parser_ntuple_processor_inputshapes.py:get()).
    # There is no separate "category" dimension in these control-plot shapes:
    # the ROOT file only splits by channel, background/data selection and
    # systematic variation.
    name = f"{dataset}#{channel}{process_selection}#{variation}#{variable}"
    h = rootfile.Get(name)
    if not h:
        logger.debug(f"Histogram not found: {name}")
        return None
    return h.Clone()


def plot_control(
    rootfile: ROOT.TFile,
    channel: str,
    era: str,
    variable: str,
    process_config: ControlShapeBkgProcesses,
    output_dir: str,
    log_y: bool = False,
    blinded: bool = False,
):
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(6.6, 6.6), gridspec_kw={"height_ratios": [4, 1.2], "hspace": 0.03}, sharex=True
    )

    bkg_hists  = {}
    sig_hists  = {}
    data_hist  = None

    # ── Collect background histograms ────────────────────────────────────────
    from shapes.estimations.defaults import _process_map, _dataset_map

    bkg_processes = process_config()

    for proc in bkg_processes:
        if proc in _QCD_SS_OS_ESTIMATION_KEYS:
            # "QCD" only shows up in ControlShapeBkgProcesses.FULLY_CLASSIC, i.e.
            # exactly the default case (no --fake-factor, no --embedding). shapes/
            # do_estimations.py already covers that default with the same-sign/
            # opposite-sign data-driven QCD estimate (shapes/estimations/qcd.py:
            # qcd_estimation(), run via `--do-qcd` -- run.py's mode_shapes() picks
            # that over `--do-ff` whenever no FF friend-tree directory is
            # configured). That estimation writes its output under its own
            # "QCDMC"/"QCD" dataset+selection labels rather than through
            # _process_map/_dataset_map, so it needs its own lookup here.
            ds, sel = _QCD_SS_OS_ESTIMATION_KEYS[proc]
            h = _get_hist(rootfile, ds, channel, "-" + sel, "Nominal", variable)
        elif proc in _process_map:
            ds = _dataset_map.get(proc, proc)
            h = _get_hist(rootfile, ds, channel, "-" + _process_map[proc], "Nominal", variable)
        else:
            continue
        if h:
            bkg_hists[proc] = h

    # Per-production-mode (not split into STXS stage-1.2 bins) signal shapes.
    # _process_map only carries "qqH125" (and the VH_as_qqH125 merge used for
    # datacards); the other three are simply plain datasets in the shapes
    # file under their own name (see e.g. "ggH#mt-ggH125#Nominal#...",
    # confirmed present in output/*-shapes.root), so look those up directly
    # rather than only checking _process_map.
    for sig_proc, dataset in _SIGNAL_DATASETS.items():
        h = _get_hist(rootfile, dataset, channel, "-" + sig_proc, "Nominal", variable)
        if h and h.Integral() > 0:
            sig_hists[sig_proc] = h

    # data (no process-selection suffix at all -- see _process_map["data"] == "data",
    # which rootfile_parser_ntuple_processor_inputshapes.get() maps to category="")
    if not blinded:
        data_h_raw = _get_hist(rootfile, "data", channel, "", "Nominal", variable)
        if data_h_raw:
            data_hist = data_h_raw

    if not bkg_hists:
        logger.warning(f"No backgrounds found for {channel}/{variable}. Skipping.")
        plt.close(fig)
        return

    # ── Stack backgrounds ────────────────────────────────────────────────────
    stack_order = [p for p in bkg_processes if p in bkg_hists]
    edges, _, _ = _th1_to_numpy(list(bkg_hists.values())[0])
    x_centers   = 0.5 * (edges[:-1] + edges[1:])
    bin_widths  = edges[1:] - edges[:-1]

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
        edgecolor="black", linewidth=0.4,
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
        width=bin_widths, color="gray", alpha=0.4,
        hatch="////", linewidth=0, label="Bkg. stat. unc.",
    )

    # signals, one fixed scale factor per production mode (see _SIGNAL_SCALES)
    for sig, h in sig_hists.items():
        _, y_sig, _ = _th1_to_numpy(h)
        col = PROCESS_COLOURS.get(sig, "#FF0000")
        scale = _SIGNAL_SCALES.get(sig, 1)
        sig_label = f"{scale}" + r"$\times$" + legend_label_dict.get(sig, sig)
        hep.histplot(
            y_sig * scale, edges,
            histtype="step", linewidth=1.8, color=col,
            label=sig_label, ax=ax_top,
        )

    # data. Same marker size in both panels (smhtt_ul draws "data_obs" with
    # one consistent marker style everywhere it appears).
    DATA_MARKERSIZE = 3.2
    y_data = None
    if data_hist:
        _, y_data, yerr_data = _th1_to_numpy(data_hist)
        ax_top.errorbar(
            x_centers, y_data, yerr=yerr_data,
            fmt="ko", markersize=DATA_MARKERSIZE, linewidth=1.2, label="Observed", zorder=10,
        )

    # ── Ratio panel ──────────────────────────────────────────────────────────
    if data_hist is not None and total_mc.sum() > 0:
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio      = np.where(total_mc > 0, y_data / total_mc, 0.0)
            ratio_err  = np.where(total_mc > 0, yerr_data / total_mc, 0.0)
            mc_unc_rel = np.where(total_mc > 0, total_mc_err / total_mc, 0.0)
        ax_bot.errorbar(x_centers, ratio, yerr=ratio_err, fmt="ko", markersize=DATA_MARKERSIZE, linewidth=1)
        ax_bot.bar(
            x_centers, 2 * mc_unc_rel, bottom=1.0 - mc_unc_rel,
            width=bin_widths, color="gray", alpha=0.4, hatch="////", linewidth=0,
        )
    ax_bot.axhline(1.0, color="black", linewidth=0.8)
    ax_bot.set_ylim(0.5, 1.5)
    ax_bot.set_yticks([0.6, 0.8, 1.0, 1.2, 1.4])
    ax_bot.grid(axis="y", linestyle=":", linewidth=0.6, color="gray")
    # hep.style.CMS sets yaxis.labellocation="top" globally (so "N_events" on
    # the main panel sits near the top, HEP convention) -- override it back
    # to centered just for this small ratio panel, where a top-anchored label
    # reads as off-center.
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
        # Matplotlib repositions the "x10^n" offset text on every draw to sit
        # right above the y-axis, next to the tick numbers -- not above the
        # "N_events" title, which sits further left/outside the axes (it's
        # rotated 90 deg alongside the tick labels). Force a draw to let the
        # formatter compute the offset string and to get the title's actual
        # on-screen position, then hide the auto-placed text and draw our own
        # directly above "N_events" instead.
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

    ax_bot.set_xlabel(_channel_x_labels(channel).get(variable, variable), fontsize=15)

    # Some variables (e.g. pt_1 with a lepton-pT selection cut) are booked
    # over a wider binning than where any background/data actually lands,
    # leaving a stretch of fully-empty bins at one or both ends of the frame.
    # Crop the x-axis to the first/last bin with any content instead of
    # always showing the full booked range.
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

    # Above-frame row: channel label (left) and lumi/era string (right) --
    # smhtt_ul's DrawChannelCategoryLabel()/DrawLumi(), both drawn just above
    # the top axis line rather than inside it. Flush to the corners now that
    # the y-axis "x10^n" offset text (above) no longer shares this row.
    ax_top.text(
        0.0, 1.012, CHANNEL_LABELS.get(channel, channel),
        transform=ax_top.transAxes, va="bottom", ha="left", fontsize=15,
    )
    ax_top.text(
        1.0, 1.012, lumi_label(era),
        transform=ax_top.transAxes, va="bottom", ha="right", fontsize=15,
    )

    # Inside-frame CMS label block, top-left -- smhtt_ul's DrawCMS(), bold
    # "Private Work" with the italic "(CMS data/simulation)" subtext below it.
    ax_top.text(
        0.03, 0.945, "Private Work", transform=ax_top.transAxes,
        va="top", ha="left", fontsize=15, fontweight="bold",
    )
    ax_top.text(
        0.03, 0.885, "(CMS data/simulation)", transform=ax_top.transAxes,
        va="top", ha="left", fontsize=12, fontstyle="italic",
    )

    # Save. No fig.tight_layout(): the shared-x/gridspec_kw layout above plus
    # the above-axes transAxes text triggers matplotlib's "not compatible with
    # tight_layout" warning; savefig(bbox_inches="tight") already crops the
    # figure to its actual content without it.
    fname = f"{channel}_{era}_{variable}"
    out = Path(output_dir) / era / channel
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(out / f"{fname}.{ext}", bbox_inches="tight", dpi=150)
    logger.info(f"Saved plot: {fname}")
    plt.close(fig)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Plot control shapes for TauKITFlow.")
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
        for variable in plot_vars:
            plot_control(
                rootfile=rootfile,
                channel=channel,
                era=args.era,
                variable=variable,
                process_config=proc_config,
                output_dir=args.output,
                log_y=args.log_y,
                blinded=args.blinded,
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
