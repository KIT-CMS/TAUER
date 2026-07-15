#!/usr/bin/env python3
"""
Build a Combine datacard for the tauES measurement (continuous ``taues``
RooMorphing fit), from a synced tauES shape file
(shapes/convert_to_synced_shapes.py --special TauES output).

This is a Python port -- via CombineHarvester's Python bindings, the same
approach Phase 2d used for combine_datacards/make_datacards.py -- of
smhtt_ul's tauES measurement datacard-construction step. The original is a
compiled CMSSW binary, ``MorphingSMRun2Legacy_tauES.cpp``. It is NOT on
smhtt_ul's ``tauID_SFs_dev`` branch (the branch this task named) -- that
branch's ``embeddded_tauES_ul2018.sh`` (MODE=DATACARD) calls
``$CMSSW_BASE/bin/slc7_amd64_gcc700/MorphingTauES_UL``, a binary whose source
was not found on any branch actually checked out locally, nor on
``tauID_SFs_dev``. The equivalent, buildable source -- structurally almost
identical (same taues RooRealVar range, same categories, same systematics
list) -- was found on CombineHarvester/SMRun2Legacy's remote branch
``origin/tauES`` (``bin/MorphingSMRun2Legacy_tauES.cpp``, a sibling of the
``bin/MorphingSMRun2Legacy.cpp`` that Phase 2d already found deleted/replaced
by ``run3_htt``'s pure-Python ``make_datacards.py``). This module is the same
kind of replacement, applied to the tauES-specific binary instead. See
STATUS.md ("## Phase 6b") for the discovery record.

What's ported faithfully (same physics, same naming):
- The ``taues`` RooRealVar range (default -2.5 to 1.6, matching the C++
  default -- overridable via --taues-range).
- The per-shift-point EMB signal-process list (``energy_scales`` in the
  C++), now generated from tau_es/energy_scales.py's canonical 100-point
  list instead of a hand-copied ~44-point subset -- see the module docstring
  there. A subset can still be requested via --shift-min/--shift-max/--shift-step
  for compatibility with the C++'s coarser default grid (recommended for a
  first fit -- 100 morphing templates is more than the coarse original used
  and will cost more RooFit build time for likely no measurement-precision
  benefit; --shift-min -2.4 --shift-max 1.6 reproduces the original's range).
- The background process list (``ZL``, ``TTL``, ``VVL``, ``jetFakes``) and
  the lnN/shape systematics block (lumi, embnorm, vvlXsec, zlXsec, ttlXsec,
  CMS_mFakeTau, per-pT-bin CMS_eff_emb_t, emb_t, CMS_eff_m, CMS_3ProngEff,
  CMS_1ProngPi0Eff, jetFakes shape stats/syst) -- all copied over 1:1 from
  the C++, with $CHANNEL/$ERA left as CombineHarvester wildcards (this
  measurement uses CombineHarvester's own AddSyst infra directly, unlike
  combine_datacards/systematics.py which had to hand-resolve those wildcards
  -- see that module's docstring for why. There's no such conflict here
  because these systematic names were never duplicated in
  shapes/selection/variations.py in the first place: they're specific to
  this measurement, not the main SM H->tautau analysis).

What's deliberately NOT ported / left as a follow-up:
- The C++'s hardcoded single-bin category ``{chn}_m_vis`` (i.e. the DM0/DM1/
  DM10_11/Inclusive split defined in taues_measurement_binning.py / used by
  shape production is collapsed to one bin in the reference C++ too -- its
  own FIT-mode shell code only ever fits "Inclusive"). This port keeps that
  as the default (--categories Inclusive) but, unlike the C++, also supports
  building one bin per DM category (--categories DM0,DM1,DM10_11,Inclusive)
  since taues_measurement_binning.py already defines all four and the synced
  shape file has all four available -- an extension, not a behavior change
  to the default.
- BuildRooMorphing is not exposed on the ``CombineHarvester.CombineTools.ch``
  Python module the rest of this repo uses (confirmed: `hasattr(ch,
  "BuildRooMorphing")` is False) -- it lives in the separate CombinePdfs
  library. Reached here via `ROOT.gSystem.Load("libCombineHarvesterCombinePdfs")`
  + `ROOT.ch.BuildRooMorphing(...)`, confirmed callable this way (see
  STATUS.md Phase 6b validation).
"""
import argparse
import glob
import logging
import os

from config.logging_setup_configs import setup_logging
from combine_datacards.tools import (
    fix_negative_bins,
    filter_zero_yield_processes,
    filter_zero_yield_systs,
    replace_with_asimov,
)
from tau_es.energy_scales import shift_values, procname_to_shift_string, shift_to_procname
from config.shapes.taues_measurement_binning import categories as taues_categories

BACKGROUND_PROCESSES = ["ZL", "TTL", "VVL", "jetFakes"]
SIGNAL_PROCESSES = ["EMB"]
TAU_ID_PT_BINS = ["30-35", "35-40", "40-500", "500-1000", "1000-inf"]

ERA_TAG = {
    "2016preVFP": "Run2016", "2016postVFP": "Run2016",
    "2017": "Run2017", "2018": "Run2018",
}


def csv(value):
    return [v.strip() for v in value.split(",") if v.strip()]


def _load_taues_systematic_shapes(cb, ch, ROOT, root_file, channel, logger):
    """Local counterpart of combine_datacards.tools.load_systematic_shapes,
    needed because that function hardcodes the main analysis's no-underscore
    Higgs mass-token convention ("$PROCESS$MASS", e.g. "ggH_htt125"), while
    the tauES measurement's synced shape file names signal templates
    "EMB_<shift>" with an underscore before the shift/mass token (matching
    the reference C++'s own "$BIN/$PROCESS_$MASS" ExtractShapes rule -- see
    make_taues_datacard's module docstring). Same filter-then-extract
    pattern: drop any shape systematic without a matching Up/Down histogram
    in the file (logged, not silently), then re-extract only what remains."""
    tfile = ROOT.TFile.Open(root_file, "READ")

    def has_shapes(s):
        mass, process = s.mass(), s.process()
        process = f"{process}_{mass}" if mass and mass != "*" else process
        base = f"{s.bin()}/{process}_{s.name()}"
        return bool(tfile.Get(base + "Up")) and bool(tfile.Get(base + "Down"))

    def filter_missing(s):
        if s.channel() != channel or s.type() != "shape":
            return False
        if not has_shapes(s):
            logger.warning(f"Removing systematic {s.name()} on {s.process()} with missing shape")
            return True
        return False

    cb.FilterSysts(filter_missing)
    tfile.Close()

    scope = cb.cp().channel([channel])
    scope.cp().backgrounds().ExtractShapes(root_file, "$BIN/$PROCESS", "$BIN/$PROCESS_$SYSTEMATIC")
    scope.cp().signals().ExtractShapes(root_file, "$BIN/$PROCESS_$MASS", "$BIN/$PROCESS_$MASS_$SYSTEMATIC")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--era", default="2018", help="Run2 era with tauES/embedding support (2018 today, see STATUS.md Phase 2a).")
    p.add_argument("--channel", default="mt", help="Only mt is supported today (Phase 2a scope).")
    p.add_argument("--categories", type=csv, default=["Inclusive"],
                    help="Comma-separated subset of taues_measurement_binning.py's categories "
                         "(DM0, DM1, DM10_11, Inclusive). Default matches the reference C++'s "
                         "FIT-mode default (Inclusive only).")
    p.add_argument("--input-file", required=True,
                    help="Synced tauES shape ROOT file, e.g. "
                         "shapes/convert_to_synced_shapes.py --special TauES output "
                         "(htt_mt.inputs-sm-Run<era>-ML.root or equivalent).")
    p.add_argument("--output-folder", default="output_taues_cards")
    p.add_argument("--real-data", action="store_true", help="Use data_obs instead of an Asimov dataset.")
    p.add_argument("--shift-min", type=float, default=None, help="Override tau_es.energy_scales.SHIFT_MIN for the morphing template grid.")
    p.add_argument("--shift-max", type=float, default=None, help="Override tau_es.energy_scales.SHIFT_MAX for the morphing template grid.")
    p.add_argument("--shift-step", type=float, default=None, help="Override tau_es.energy_scales.SHIFT_STEP for the morphing template grid.")
    p.add_argument("--taues-min", type=float, default=-2.5)
    p.add_argument("--taues-max", type=float, default=1.6)
    p.add_argument("--taues-init", type=float, default=-1.0)
    p.add_argument("--bbb", action="store_true", help="Add autoMCStats (bin-by-bin) uncertainties.")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def _shift_procnames(args):
    if args.shift_min is None and args.shift_max is None and args.shift_step is None:
        values = shift_values()
    else:
        from tau_es import energy_scales as es
        lo = args.shift_min if args.shift_min is not None else es.SHIFT_MIN
        hi = args.shift_max if args.shift_max is not None else es.SHIFT_MAX
        step = args.shift_step if args.shift_step is not None else es.SHIFT_STEP
        n_steps = round((hi - lo) / step)
        values = [round(lo + step * i, 1) for i in range(n_steps + 1) if round(lo + step * i, 1) != 0.0]
    return values, [procname_to_shift_string(shift_to_procname(v)) for v in values]


def build_datacard(args, logger):
    import ROOT
    ROOT.gSystem.Load("libCombineHarvesterCombinePdfs")
    import CombineHarvester.CombineTools.ch as ch

    if args.channel != "mt":
        raise ValueError("tau_es/make_taues_datacard.py only supports channel='mt' today (Phase 2a scope).")
    if args.era not in ERA_TAG:
        raise ValueError(f"Unsupported era {args.era!r}; supported: {sorted(ERA_TAG)}")
    if args.channel not in taues_categories:
        raise ValueError(f"No tauES categorization for channel {args.channel!r} in taues_measurement_binning.py")

    unknown = set(args.categories) - set(taues_categories[args.channel])
    if unknown:
        raise ValueError(f"Unknown categories {sorted(unknown)}; available: {sorted(taues_categories[args.channel])}")

    shift_vals, shift_strings = _shift_procnames(args)
    logger.info(f"Using {len(shift_vals)} tauES morphing template points spanning {shift_vals[0]} to {shift_vals[-1]}.")

    era_tag = ERA_TAG[args.era]
    bins = [(i + 1, f"{args.channel}_{cat}") for i, cat in enumerate(args.categories)]

    cb = ch.CombineHarvester()
    cb.AddObservations(["*"], ["htt"], [era_tag], [args.channel], bins)
    cb.AddProcesses(["*"], ["htt"], [era_tag], [args.channel], BACKGROUND_PROCESSES, bins, False)
    cb.AddProcesses(shift_strings, ["htt"], [era_tag], [args.channel], SIGNAL_PROCESSES, bins, True)

    # --- Nominal extraction FIRST, systematics registered/loaded after. ---
    # ExtractShapes(..., syst_rule) immediately tries to resolve every shape
    # systematic already registered on `cb` at call time -- so the AddSyst()
    # calls below must come after this nominal pass, and shape systematics
    # must be (re-)loaded via combine_datacards.tools.load_systematic_shapes
    # (which filters out any that have no matching histogram in the file
    # before extracting, exactly like combine_datacards/make_datacards.py's
    # own two-pass ExtractShapes/AddSystematics/load_systematic_shapes
    # ordering -- see that module for the identical pattern applied to the
    # main analysis).
    logger.info(f"Extracting nominal shapes from {args.input_file}")
    cb.cp().channel([args.channel]).backgrounds().ExtractShapes(
        args.input_file, "$BIN/$PROCESS", "$BIN/$PROCESS_$SYSTEMATIC")
    cb.cp().channel([args.channel]).process(SIGNAL_PROCESSES).ExtractShapes(
        args.input_file, "$BIN/$PROCESS_$MASS", "$BIN/$PROCESS_$MASS_$SYSTEMATIC")

    # --- Systematics (ported 1:1 from MorphingSMRun2Legacy_tauES.cpp) ---
    lumi_unc = 1.023 if args.era == "2017" else 1.025
    cb.cp().process(["ZL", "TTL", "VVL"]).AddSyst(cb, "lumi", "lnN", ch.SystMap()(lumi_unc))
    cb.cp().process(["EMB"]).AddSyst(cb, "embnorm", "lnN", ch.SystMap()(1.04))
    cb.cp().process(["VVL"]).AddSyst(cb, "vvlXsec", "lnN", ch.SystMap()(1.05))
    cb.cp().process(["ZL"]).AddSyst(cb, "zlXsec", "lnN", ch.SystMap()(1.04))
    cb.cp().process(["TTL"]).AddSyst(cb, "ttlXsec", "lnN", ch.SystMap()(1.06))
    cb.cp().channel(["mt"]).process(["ZL"]).AddSyst(cb, "CMS_mFakeTau_$ERA", "lnN", ch.SystMap()(1.25))
    for pt_bin in TAU_ID_PT_BINS:
        cb.cp().process(["EMB"]).AddSyst(cb, f"CMS_eff_emb_t_{pt_bin}_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["EMB"]).AddSyst(cb, "emb_t_$CHANNEL_$ERA", "lnN", ch.SystMap()(1.01))
    cb.cp().process(["ZL", "TTL", "VVL", "EMB"]).AddSyst(cb, "CMS_eff_m", "lnN", ch.SystMap()(1.02))
    cb.cp().process(["EMB"]).AddSyst(cb, "CMS_3ProngEff_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["EMB"]).AddSyst(cb, "CMS_1ProngPi0Eff_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["jetFakes"]).AddSyst(cb, "CMS_ff_qcd_njet0_$CHANNEL_stat_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["jetFakes"]).AddSyst(cb, "CMS_ff_qcd_njet1_$CHANNEL_stat_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["jetFakes"]).AddSyst(cb, "CMS_ff_w_njet0_$CHANNEL_stat_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["jetFakes"]).AddSyst(cb, "CMS_ff_w_njet1_$CHANNEL_stat_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["jetFakes"]).AddSyst(cb, "CMS_ff_tt_njet1_stat_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["jetFakes"]).AddSyst(cb, "CMS_ff_qcd_mt_syst_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["jetFakes"]).AddSyst(cb, "CMS_ff_w_syst_$ERA", "shape", ch.SystMap()(1.0))
    cb.cp().process(["jetFakes"]).AddSyst(cb, "CMS_ff_tt_syst_$ERA", "shape", ch.SystMap()(1.0))

    if not args.real_data:
        replace_with_asimov(cb)

    fix_negative_bins(cb)
    filter_zero_yield_processes(cb)

    logger.info("Loading shape systematics (missing ones dropped with a warning)...")
    _load_taues_systematic_shapes(cb, ch, ROOT, args.input_file, args.channel, logger)
    filter_zero_yield_systs(cb)

    ch.SetStandardBinNames(cb, "$ANALYSIS_$CHANNEL_$BINID_$ERA")

    # --- RooMorphing: the actual "tauES calculation" -- build a continuous
    # `taues` template morph across the discrete shift-point EMB templates,
    # exactly what makes this a shape-fit measurement rather than a plain
    # counting/shape-nuisance datacard. ---
    taues = ROOT.RooRealVar("taues", "taues", args.taues_init, args.taues_min, args.taues_max)
    ws = ROOT.RooWorkspace("htt", "htt")
    for bin_name in cb.cp().bin_set():
        for process in cb.cp().bin([bin_name]).signals().process_set():
            # Trailing `file` arg omitted (defaults to nullptr in C++) --
            # cppyy cannot convert Python None to TFile* for this overload.
            ROOT.ch.BuildRooMorphing(ws, cb, bin_name, process, taues, "norm", True, True, False)
    ws.var("taues").setVal(args.taues_init)

    cb.AddWorkspace(ws)
    cb.cp().process(["EMB"]).ExtractPdfs(cb, "htt", "$BIN_$PROCESS_morph")

    if args.bbb:
        logger.info("Adding AutoMCStats...")
        cb.SetAutoMCStats(cb, 0.0)

    os.makedirs(args.output_folder, exist_ok=True)
    writer = ch.CardWriter(
        os.path.join(args.output_folder, "$BIN.txt"),
        os.path.join(args.output_folder, f"common/htt_input_{args.era}.root"),
    )
    # Real bug found + fixed during Phase 6b validation: backgrounds here are
    # added with a wildcard mass ("*", via AddProcesses(["*"], ...)), same as
    # the reference C++. Without telling CardWriter to NOT treat "*" as a
    # real mass identifier, it silently writes zero cards (every object
    # appears to have mass "*", which CardWriter's default wildcard handling
    # skips) -- reproduced: the exact same code minus this line wrote an
    # empty output folder with no error. The reference C++ already calls
    # this (`writer.SetWildcardMasses({})`); missing here was the actual bug.
    writer.SetWildcardMasses([])
    writer.WriteCards("", cb)

    if args.bbb:
        for card in glob.glob(os.path.join(args.output_folder, "*.txt")):
            with open(card, "r", encoding="utf-8") as handle:
                lines = [line for line in handle if "autoMCStats" not in line]
            lines.append(" * autoMCStats 0.0\n")
            with open(card, "w", encoding="utf-8") as handle:
                handle.writelines(lines)

    logger.info(f"Done: era={args.era} channel={args.channel} categories={args.categories} -> {args.output_folder}")
    return cb


def main():
    args = parse_args()
    logger = setup_logging(logger=logging.getLogger(__name__), level=getattr(logging, args.log_level.upper()))
    logger.info(f"Starting tauES datacard generation with arguments: {args}")
    build_datacard(args, logger)


if __name__ == "__main__":
    main()
