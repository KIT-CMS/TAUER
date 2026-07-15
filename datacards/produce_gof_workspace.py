#!/usr/bin/env python3
"""Produce a goodness-of-fit / impacts workspace for Combine.

Python control-script replacement for the former datacards/produce_gof_workspace.sh
(Phase 6d). Same positional arguments (ERA CHANNEL VARIABLE [CORES]) as the
bash version.

Builds ws.root next to the GoF datacard produced by produce_gof_datacard.py,
i.e. at ${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/${CHANNEL}/${ERA}/ws.root.

Phase 4 change: uses Combine's *default* physics model (a single signal
strength `r` scaling all Higgs processes) rather than the multiSignalModel
(r_ggH/r_qqH) the pre-Phase-4 scaffolding used. A single POI is what both the
GoF test (`--fixedSignalStrength=0` == r=0, background-only) and single-POI
Impacts (`combineTool.py -M Impacts`) expect; a multiSignalModel workspace
breaks `--fixedSignalStrength` and needs an explicit --redefineSignalPOIs for
Impacts. For a one-bin `gof` category there is no ggH/qqH separation to gain
from two POIs anyway.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.cmsenv import get_fitdir, run_in_cmsenv


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Produce a goodness-of-fit / impacts workspace for Combine.",
    )
    parser.add_argument("era")
    parser.add_argument("channel")
    parser.add_argument("variable")
    parser.add_argument("cores", nargs="?", type=int, default=1)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    fitdir = get_fitdir()
    # make_datacards.py writes {output-folder}/{channel}/{era}/{bin}.txt
    input_dir = Path(fitdir) / "output" / "datacards" / f"{args.era}-{args.channel}-{args.variable}-gof" / args.channel / args.era

    candidates = sorted(glob.glob(str(input_dir / "htt_*.txt")))
    if not candidates:
        print(f"ERROR: no datacard htt_*.txt found in {input_dir}. Run produce_gof_datacard.py first.", file=sys.stderr)
        return 1
    card = candidates[0]

    print(f"[GoF workspace] building default single-r workspace from {card}")
    ws_path = input_dir / "ws.root"
    result = run_in_cmsenv(
        ["text2workspace.py", card, "-m", "125", "-o", str(ws_path)],
        check=False,
        unlimited_stack=True,
    )
    if result.returncode != 0:
        return result.returncode
    print(f"[GoF workspace] wrote {ws_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
