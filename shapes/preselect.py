#!/usr/bin/env python
"""
shapes/preselect.py — Prepare preselected ntuples for TauKITFlow shape production.

Backgrounds / data:
  TauFakeFactors preselection.py (run with --all-columns) already applied the
  event selection and computed a ``presel_weight`` column.  This script
  reorganises its flat output into the CROWN-compatible directory structure
  that ntuple_processor expects:

    TFF output:  {tff_dir}/{era}/{channel}/{process}_{gen_mode}.root
    CROWN style: {output_dir}/{era}/{process}_{gen_mode}/{channel}/{process}_{gen_mode}.root

  Reorganisation is done via symbolic links — no data is copied.

Signals:
  Signal samples are not part of the TFF config.  For each signal sample
  the TFF event-selection cuts are applied to the CROWN ntuples and a
  ``presel_weight`` column is computed (lumi × generator × tau-ID SFs ×
  lepton SFs × Z/Top pt reweighting where applicable).  All branches are
  saved, including systematic variations.

Usage
-----
  python shapes/preselect.py \\
      --era 2022postEE --channel mt \\
      --tff-dir /ceph/.../CMS_FF/<tag>/preselection \\
      --directory /ceph/.../CROWNRun/ \\
      --xsec-friends /store/.../xsec/ \\
      --output-dir /ceph/.../presel/ \\
      --nthreads 4
"""
import argparse
import glob
import logging
import os

import ROOT

ROOT.gROOT.SetBatch(True)

from config.analysis import (
    SIGNAL_SAMPLES as signal_files,
    get_luminosity,
    get_mc_weights,
    get_preselection_cuts,
)
from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

_TOP_PT_PROCESSES = {"ttbar", "ST"}
_Z_PT_PROCESSES   = {"DYjets"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_weight_expr(mc_weights: dict, process: str, era: str) -> str:
    """
    Build a C++ presel_weight expression for *signal* samples.

    Mirrors TFF mc_weights but replaces TFF-internal generator/lumi keys with
    CROWN xsec-friend columns so it works outside of TFF's helper library.
    """
    lumi = get_luminosity(era) * 1000.0  # config/samples.yaml stores fb^-1; presel_weight needs pb^-1
    parts = []
    for key, expr in mc_weights.items():
        if key == "generator":
            parts.append(
                "numberGeneratedEventsWeight"
                " * crossSectionPerEventWeight"
                " * (1.0 / negative_events_fraction)"
                " * (((genWeight < 0) * (-1)) + ((genWeight >= 0) * 1))"
            )
        elif key == "lumi":
            parts.append(str(lumi))
        elif key == "Z_pt_reweighting":
            if process in _Z_PT_PROCESSES and isinstance(expr, str) and expr.strip():
                parts.append(f"({expr})")
        elif key == "Top_pt_reweighting":
            if process in _TOP_PT_PROCESSES and isinstance(expr, str) and expr.strip():
                parts.append(f"({expr})")
        elif isinstance(expr, str) and expr.strip():
            parts.append(f"({expr})")
    return " * ".join(parts) if parts else "1.0"


# ---------------------------------------------------------------------------
# Background reorganisation (symlinks)
# ---------------------------------------------------------------------------

def reorganise_tff_backgrounds(tff_dir: str, output_dir: str, era: str, channel: str) -> None:
    """
    Create CROWN-compatible symlinks for all TFF preselection output files.

    TFF saves one ROOT file per process+gen_mode in a flat directory:
        {tff_dir}/{era}/{channel}/{process}_{gen_mode}.root

    We expose each file as:
        {output_dir}/{era}/{process}_{gen_mode}/{channel}/{process}_{gen_mode}.root
    """
    src_dir = os.path.join(tff_dir, era, channel)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(
            f"TFF preselection output not found: {src_dir}\n"
            f"Did you run 'python3 run.py PRESEL --all-columns'?"
        )

    root_files = [f for f in os.listdir(src_dir) if f.endswith(".root")]
    if not root_files:
        logger.warning(f"No .root files found in {src_dir}")
        return

    for fname in root_files:
        sample_name = os.path.splitext(fname)[0]  # e.g. "DYjets_J"
        src_path = os.path.abspath(os.path.join(src_dir, fname))
        dest_dir = os.path.join(output_dir, era, sample_name, channel)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, fname)
        if os.path.islink(dest_path) or os.path.exists(dest_path):
            os.unlink(dest_path)
        os.symlink(src_path, dest_path)
        logger.info(f"Symlinked [{sample_name}] {src_path} -> {dest_path}")

        # Warn if the TFF file has very few columns (was not run with --all-columns)
        try:
            f = ROOT.TFile.Open(src_path)
            t = f.Get("ntuple") if f and not f.IsZombie() else None
            if t:
                ncols = t.GetListOfBranches().GetEntries()
                if ncols < 100:
                    logger.warning(
                        f"  {fname} has only {ncols} columns — looks like TFF was "
                        f"not run with --all-columns.  Systematic variations will be missing."
                    )
            if f:
                f.Close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Signal processing
# ---------------------------------------------------------------------------

def process_signal_sample(
    *,
    sample: str,
    era: str,
    channel: str,
    directory: str,
    xsec_friends: str,
    output_dir: str,
    event_selection: dict,
    mc_weights: dict,
    process: str,
    nthreads: int,
) -> None:
    """Apply TFF event selection to a signal sample and save ALL columns."""

    ntuple_glob = os.path.join(directory, era, sample, channel, "*.root")
    ntuple_files = sorted(glob.glob(ntuple_glob))
    if not ntuple_files:
        logger.warning(f"No ntuple files for signal {sample}: {ntuple_glob}")
        return

    chain = ROOT.TChain("ntuple")
    for f in ntuple_files:
        chain.Add(f)

    if xsec_friends:
        xsec_glob = os.path.join(xsec_friends, era, sample, channel, "*.root")
        xsec_files = sorted(glob.glob(xsec_glob))
        if xsec_files:
            fchain = ROOT.TChain("ntuple")
            for f in xsec_files:
                fchain.Add(f)
            chain.AddFriend(fchain)
        else:
            logger.warning(f"No xsec friend files for signal {sample}: {xsec_glob}")

    ROOT.ROOT.EnableImplicitMT(nthreads)
    rdf = ROOT.RDataFrame(chain)

    if rdf.Count().GetValue() == 0:
        logger.warning(f"Empty ntuple for signal {sample}, skipping.")
        return

    # Apply TFF event selection
    for cut_name, cut_expr in event_selection.items():
        rdf = rdf.Filter(f"({cut_expr})", f"presel:{cut_name}")

    # Compute presel_weight using TFF mc_weights (adapted for CROWN xsec columns)
    w_expr = _build_weight_expr(mc_weights, process, era)
    rdf = rdf.Define("presel_weight", w_expr)

    if rdf.Count().GetValue() == 0:
        logger.info(f"No events left after presel for signal {sample}, skipping.")
        return

    # Save ALL columns (including presel_weight and systematic branches)
    out_dir = os.path.join(output_dir, era, sample, channel)
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "ntuple.root")

    # Strip "ntuple." friend prefix from column names for clean output
    raw_cols = [str(c) for c in rdf.GetColumnNames()]
    seen: set[str] = set()
    cols: list[str] = []
    for c in raw_cols:
        clean = c.replace("ntuple.", "")
        if clean not in seen:
            seen.add(clean)
            cols.append(c)

    n_events = rdf.Count().GetValue()
    logger.info(f"Saving {n_events} signal events [{sample}] → {out_file}")
    rdf.Snapshot("ntuple", out_file, cols)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Prepare preselected ntuples for shape production.\n"
            "Backgrounds: reorganises TFF preselection output via symlinks.\n"
            "Signals:     applies TFF event selection to CROWN ntuples."
        )
    )
    parser.add_argument("--era",          required=True,  help="CMS era (e.g. 2022postEE).")
    parser.add_argument("--channel",      required=True,  help="Channel (et, mt, tt).")
    parser.add_argument("--tff-dir",      required=True,
                        help="TFF preselection output base dir "
                             "(the 'preselection' subdirectory of TFF output_path, "
                             "e.g. /ceph/.../CMS_FF/<tag>/preselection).")
    parser.add_argument("--output-dir",   required=True,  help="CROWN-compatible output base directory.")
    parser.add_argument("--directory",    default=None,   help="CROWN ntuple base dir (needed for signals).")
    parser.add_argument("--xsec-friends", default=None,   help="xsec friends base dir (needed for signals).")
    parser.add_argument("--nthreads",     default=4, type=int, help="ROOT implicit MT threads (signals only).")
    parser.add_argument("--skip-signals", action="store_true",
                        help="Skip signal processing (only reorganise TFF backgrounds).")
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Backgrounds: symlink TFF output into CROWN structure ───────────────────
    logger.info(f"[{args.era}/{args.channel}] Reorganising TFF preselection output from {args.tff_dir}")
    reorganise_tff_backgrounds(
        tff_dir=args.tff_dir,
        output_dir=args.output_dir,
        era=args.era,
        channel=args.channel,
    )

    # ── Signals: process from CROWN ntuples ────────────────────────────────────
    if args.skip_signals:
        return

    era_signals = signal_files.get(args.era, {})
    if not era_signals:
        logger.info(f"No signals defined for era {args.era}, nothing to do.")
        return

    if not args.directory:
        logger.error("--directory is required for signal processing.")
        raise SystemExit(1)

    event_selection: dict = get_preselection_cuts(args.era, args.channel)
    mc_weights: dict      = get_mc_weights(args.era, args.channel)

    for sig_key, sig_samples in era_signals.items():
        for sample in sig_samples:
            logger.info(f"[{args.era}/{args.channel}] Signal {sig_key}/{sample}")
            process_signal_sample(
                sample=sample,
                era=args.era,
                channel=args.channel,
                directory=args.directory,
                xsec_friends=args.xsec_friends or "",
                output_dir=args.output_dir,
                event_selection=event_selection,
                mc_weights=mc_weights,
                process=sig_key,
                nthreads=args.nthreads,
            )


if __name__ == "__main__":
    main()
