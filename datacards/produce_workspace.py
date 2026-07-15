#!/usr/bin/env python3
"""Produce SM H->tautau workspace (RooWorkspace) for Combine.

Python control-script replacement for the former datacards/produce_workspace.sh
(Phase 6d). Same positional arguments (ERA[,ERA...] ANALYSIS [CORES]) as the
bash version.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.cmsenv import get_fitdir, run_in_cmsenv


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Produce SM H->tautau workspace (RooWorkspace) for Combine.",
    )
    parser.add_argument("eras", help="Comma-separated era list, e.g. 2022postEE or 2022postEE,2023preBPix")
    parser.add_argument("analysis", help="Categorization scheme (matches produce_datacard.py's ANALYSIS)")
    parser.add_argument("cores", nargs="?", type=int, default=1)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    era_list = [e for e in args.eras.split(",") if e]

    print(f"Use {args.cores} cores.")
    fitdir = get_fitdir()

    # combine_datacards/make_datacards.py (Phase 2d) writes
    # output_${ANALYSIS}/{channel}/{era}/*.txt (channel outer, era inner) --
    # see datacards/produce_datacard.py.
    input_dirs = f"output_{args.analysis}/{{et,mt,tt,em,cmb}}/{{{','.join(era_list)}}}"

    cmd = [
        "combineTool.py",
        "-M",
        "T2W",
        "-o",
        "ws.root",
        "-P",
        "HiggsAnalysis.CombinedLimit.PhysicsModel:multiSignalModel",
        "--PO",
        '"map=^.*/ggH125$:r_ggH[1,0,5]"',
        "--PO",
        '"map=^.*/qqH125$:r_qqH[1,0,5]"',
        "-i",
        input_dirs,
        "-m",
        "125",
        "--parallel",
        str(args.cores),
    ]
    result = run_in_cmsenv(cmd, cwd=Path(fitdir), check=False, unlimited_stack=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
