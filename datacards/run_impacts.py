#!/usr/bin/env python3
"""Run a real Combine Impacts (nuisance-ranking) workflow end-to-end.

Python control-script replacement for the former datacards/run_impacts.sh
(Phase 6d; that script itself dates to Phase 4, see STATUS.md "## Phase 4").
Same positional/optional arguments as the bash version.

Expects the datacard/workspace to already exist at
    ${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/${CHANNEL}/${ERA}/ws.root
(i.e. run datacards/run_gof.py -- or at minimum produce_gof_datacard.py +
produce_gof_workspace.py -- first; this script does not rebuild the
workspace, only reuses it, since Impacts and GoF are almost always run
back-to-back against the same card).

Standard combineTool.py -M Impacts pipeline (adapted from
smhtt_ul/fitting/impacts.sh, house-ruled to TauKITFlow's default single-r
workspace -- no --redefineSignalPOIs needed since there's exactly one POI):
  1. --doInitialFit   (best-fit r + its uncertainty)
  2. --doFits         (one fit per nuisance parameter, --parallel-wide)
  3. -o impacts.json  (collect)
  4. plotImpacts.py   (ranked tornado plot)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.cmsenv import get_fitdir, run_in_cmsenv

MASS = "125"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a real Combine Impacts (nuisance-ranking) workflow end-to-end.",
    )
    parser.add_argument("era")
    parser.add_argument("channel")
    parser.add_argument("variable")
    parser.add_argument("parallel", nargs="?", type=int, default=10)
    parser.add_argument("ntuple_tag", nargs="?", default=None, help="Unused by the Impacts steps themselves; accepted for CLI-compat with the old bash script.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    era, channel, variable = args.era, args.channel, args.variable
    job_id = f"{era}_{channel}_{variable}"

    fitdir = Path(get_fitdir())
    workspace = fitdir / "output" / "datacards" / f"{era}-{channel}-{variable}-gof" / channel / era / "ws.root"
    if not workspace.is_file():
        print(
            f"ERROR: workspace not found: {workspace}. Run produce_gof_datacard.py + "
            "produce_gof_workspace.py (or run_gof.py) first.",
            file=sys.stderr,
        )
        return 1

    impacts_dir = fitdir / "output" / "impacts" / job_id
    impacts_dir.mkdir(parents=True, exist_ok=True)

    print("[run_impacts] === step 1/4: doInitialFit ===")
    t0 = time.monotonic()
    run_in_cmsenv(
        [
            "combineTool.py",
            "-M",
            "Impacts",
            "-d",
            str(workspace),
            "-m",
            MASS,
            "--X-rtd",
            "MINIMIZER_analytic",
            "--cminDefaultMinimizerStrategy",
            "0",
            "--doInitialFit",
            "--robustFit",
            "1",
            "--parallel",
            str(args.parallel),
        ],
        cwd=impacts_dir,
        unlimited_stack=True,
    )
    print(f"[run_impacts]     ({time.monotonic() - t0:.1f}s)")

    print("[run_impacts] === step 2/4: doFits (per-nuisance) ===")
    t0 = time.monotonic()
    run_in_cmsenv(
        [
            "combineTool.py",
            "-M",
            "Impacts",
            "-d",
            str(workspace),
            "-m",
            MASS,
            "--X-rtd",
            "MINIMIZER_analytic",
            "--cminDefaultMinimizerStrategy",
            "0",
            "--robustFit",
            "1",
            "--doFits",
            "--parallel",
            str(args.parallel),
        ],
        cwd=impacts_dir,
        unlimited_stack=True,
    )
    print(f"[run_impacts]     ({time.monotonic() - t0:.1f}s)")

    print("[run_impacts] === step 3/4: collect -> impacts.json ===")
    impacts_json = impacts_dir / f"impacts_{job_id}.json"
    run_in_cmsenv(
        ["combineTool.py", "-M", "Impacts", "-d", str(workspace), "-m", MASS, "-o", str(impacts_json)],
        cwd=impacts_dir,
        unlimited_stack=True,
    )

    print("[run_impacts] === step 4/4: plotImpacts ===")
    run_in_cmsenv(
        ["plotImpacts.py", "-i", str(impacts_json), "-o", f"impacts_{job_id}"],
        cwd=impacts_dir,
        unlimited_stack=True,
    )

    print("[run_impacts] === summary: top-ranked nuisances ===")
    _print_impacts_summary(impacts_json)

    print(f"[run_impacts] done. Outputs under {impacts_dir}")
    return 0


def _print_impacts_summary(json_path: Path) -> None:
    d = json.loads(json_path.read_text())
    poi = d["POIs"][0]["name"]
    rows = []
    for p in d["params"]:
        imp = p.get("impact_" + poi, p.get("impact"))
        rows.append((abs(imp), imp, p["name"]))
    rows.sort(reverse=True)
    print(f"POI: {poi}")
    print(f"{'rank':<5}{'impact':>10}   nuisance")
    for i, (_absimp, imp, name) in enumerate(rows[:15], 1):
        print(f"{i:<5}{imp:>10.4f}   {name}")
    print(f"... {len(rows)} nuisances total")


if __name__ == "__main__":
    raise SystemExit(main())
