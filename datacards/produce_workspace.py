#!/usr/bin/env python3
"""Produce the Combine workspace (ws.root) of the datacards of datacards/produce_datacard.py.

Analysis cards: combineTool.py T2W with the analysis physics model over output_${ANALYSIS}/{channel}/{era}.
GoF cards (ANALYSIS=gof, --channels/--variable): text2workspace.py with Combine's default single-r model, next to the
card, which is what the b-only GoF test (--fixedSignalStrength=0) and single-POI Impacts expect.
"""
from __future__ import annotations

import argparse
import glob
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.cmsenv import get_fitdir, run_in_cmsenv
from config.analysis import ACTIVE_ANALYSIS
from datacards import MASS, gof_card_dir


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("eras", help="Comma-separated era list, e.g. 2022postEE,2023preBPix (a single era for gof)")
    parser.add_argument("analysis", help="Categorization scheme (matches produce_datacard.py's ANALYSIS)")
    parser.add_argument("cores", nargs="?", type=int, default=1)
    parser.add_argument("--channels", dest="channel", help="GoF only")
    parser.add_argument("--variable", help="GoF only")
    args = parser.parse_args(argv)
    if args.analysis == "gof" and not (args.channel and args.variable and "," not in args.eras):
        parser.error("ANALYSIS=gof needs a single era, --channels and --variable")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    fitdir = get_fitdir()

    if args.analysis == "gof":
        card_dir = gof_card_dir(fitdir, args.eras, args.channel, args.variable)
        cards = sorted(glob.glob(str(card_dir / "htt_*.txt")))
        if not cards:
            print(f"ERROR: no datacard htt_*.txt found in {card_dir}. Run produce_datacard.py first.", file=sys.stderr)
            return 1
        print(f"[workspace] building default single-r workspace from {cards[0]}")
        return run_in_cmsenv(["text2workspace.py", cards[0], "-m", MASS, "-o", str(card_dir / "ws.root")], check=False, unlimited_stack=True).returncode

    combine_model = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.datacards.combine_model")
    print(f"Use {args.cores} cores.")
    cmd = [
        "combineTool.py", "-M", "T2W", "-o", "ws.root",
        "-P", combine_model.PHYSICS_MODEL, *combine_model.PHYSICS_MODEL_OPTIONS,
        "-i", f"output_{args.analysis}/{{et,mt,tt,em,cmb}}/{{{args.eras}}}",
        "-m", MASS,
        "--parallel", str(args.cores),
    ]
    return run_in_cmsenv(cmd, cwd=Path(fitdir), check=False, unlimited_stack=True).returncode


if __name__ == "__main__":
    raise SystemExit(main())
