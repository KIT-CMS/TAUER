#!/usr/bin/env python3
"""
Run the tauES measurement fit against a datacard built by
tau_es/make_taues_datacard.py.

Python replacement for smhtt_ul's ``embeddded_tauES_ul2018.sh`` DATACARD/FIT/
POSTFIT bash modes (per the framework-wide "prefer Python control scripts"
decision already applied elsewhere in this rework -- see STATUS.md's law/
condor decisions). Combine/CombineHarvester/CMSSW themselves stay external
dependencies, reached via ``utils/setup_cmssw.sh`` -- this script only
``subprocess.run()``s the same real external binaries
(``text2workspace.py``/``combineTool.py -M T2W``, ``combine -M MultiDimFit``)
the bash version did; no C++/bash orchestration logic is reimplemented here
beyond translating the fixed argument lists into Python.

Two subcommands:
  workspace  -- text2workspace.py (via combineTool.py -M T2W) on a datacard
                produced by make_taues_datacard.py.
  fit        -- combine -M MultiDimFit with taues as the (only, by default)
                floated POI, matching the reference script's --redefineSignalPOIs
                taues,r / --setParameterRanges usage (r is only meaningful if
                a genuine signal-strength POI exists in the card in addition
                to taues; pass --with-r to include it, matching the reference
                script's default of always including it -- kept optional here
                since this measurement's datacard has no independent Higgs
                signal-strength process, only the EMB taues-morphed template,
                so --redefineSignalPOIs taues alone is the more physically
                correct default for this port. Documented, not silently
                changed: the reference script always fit taues+r; this port
                defaults to taues-only and lets --with-r reproduce the
                original behavior exactly.)

Both subcommands wrap real external binaries via subprocess -- there is no
"pure Python fit" to have here; the calculation is the Combine minimization
itself, run via the genuine external binary, exactly like
combine_datacards/make_datacards.py's ``run_combine_cards`` already does for
combineCards.py.
"""
import argparse
import logging
import os
import shutil
import subprocess

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def _run(cmd, logger, **kwargs):
    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(["nice", "-n", "19", *cmd], **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (rc={result.returncode}): {' '.join(cmd)}")
    return result


def cmd_workspace(args):
    combine_tool = shutil.which("combineTool.py")
    if combine_tool is None:
        raise RuntimeError("combineTool.py not found in PATH -- source utils/setup_cmssw.sh first.")
    os.makedirs(os.path.dirname(args.workspace) or ".", exist_ok=True)
    cmd = [
        combine_tool, "-M", "T2W",
        "-i", args.datacard,
        "-o", os.path.basename(args.workspace),
        "--parallel", str(args.parallel),
        "--X-no-check-norm",
    ]
    _run(cmd, logger, cwd=os.path.dirname(args.workspace) or ".")
    logger.info(f"Workspace written: {args.workspace}")


def cmd_fit(args):
    combine = shutil.which("combine")
    if combine is None:
        raise RuntimeError("combine not found in PATH -- source utils/setup_cmssw.sh first.")

    pois = "taues,r" if args.with_r else "taues"
    ranges = f"taues={args.taues_min},{args.taues_max}"
    set_params = f"taues={args.taues_init}"
    if args.with_r:
        ranges += ":r=0.8,1.2"
        set_params += ",r=1.0"

    workdir = os.path.dirname(args.workspace) or "."

    initial_fit_cmd = [
        combine, "-M", "MultiDimFit", "-n", f"_initialFit_{args.tag}",
        "--algo", "singles", "--redefineSignalPOIs", pois,
        "--setParameterRanges", ranges,
        "--robustFit", "1", "-m", "0", "-d", args.workspace,
        "--setParameters", set_params,
        "--setRobustFitAlgo=Minuit2", "--setRobustFitStrategy=0", "--setRobustFitTolerance=0.2",
        "--X-rtd", "FITTER_NEW_CROSSING_ALGO", "--X-rtd", "FITTER_NEVER_GIVE_UP", "--X-rtd", "FITTER_BOUND",
        "--cminFallbackAlgo", "Minuit2,0:0.1", "--cminFallbackAlgo", "Minuit,0:0.1",
    ]
    _run(initial_fit_cmd, logger, cwd=workdir)

    combine_tool = shutil.which("combineTool.py")
    if combine_tool is None:
        raise RuntimeError("combineTool.py not found in PATH -- source utils/setup_cmssw.sh first.")
    scan_cmd = [
        combine_tool, "-M", "MultiDimFit", "-d", args.workspace,
        "--algo", "grid", "--X-rtd", "MINIMIZER_analytic", "--cminDefaultMinimizerStrategy", "0",
        "-P", "taues", "-m", "0", "--redefineSignalPOIs", pois,
        "--setParameterRanges", ranges, "--floatOtherPOIs", "1",
        "--points", str(args.points), "--robustFit", "1",
        "--setRobustFitAlgo=Minuit2", "--setRobustFitStrategy=0", "--setRobustFitTolerance=0.2",
        "--X-rtd", "FITTER_NEW_CROSSING_ALGO", "--X-rtd", "FITTER_NEVER_GIVE_UP", "--X-rtd", "FITTER_BOUND",
        "--cminFallbackAlgo", "Minuit2,0:0.1", "--cminFallbackAlgo", "Minuit,0:0.1",
        "-n", args.tag,
    ]
    _run(scan_cmd, logger, cwd=workdir)

    result_file = os.path.join(workdir, f"higgsCombine{args.tag}.MultiDimFit.mH0.root")
    logger.info(f"Fit scan output: {result_file}")
    return result_file


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    ws = sub.add_parser("workspace", help="Build a RooWorkspace from a tauES datacard (T2W).")
    ws.add_argument("--datacard", required=True, help="Datacard folder (as written by make_taues_datacard.py's --output-folder).")
    ws.add_argument("--workspace", required=True, help="Output workspace.root path.")
    ws.add_argument("--parallel", type=int, default=4)

    fit = sub.add_parser("fit", help="Run the taues MultiDimFit scan.")
    fit.add_argument("--workspace", required=True)
    fit.add_argument("--tag", default="taues")
    fit.add_argument("--taues-min", type=float, default=-2.5)
    fit.add_argument("--taues-max", type=float, default=1.6)
    fit.add_argument("--taues-init", type=float, default=-1.0)
    fit.add_argument("--points", type=int, default=30)
    fit.add_argument("--with-r", action="store_true",
                      help="Also float a signal-strength POI 'r' alongside taues, matching the "
                           "reference smhtt_ul script's default (--redefineSignalPOIs taues,r). "
                           "Off by default here -- see module docstring.")

    return p.parse_args()


def main():
    args = parse_args()
    if args.command == "workspace":
        cmd_workspace(args)
    elif args.command == "fit":
        cmd_fit(args)


if __name__ == "__main__":
    main()
