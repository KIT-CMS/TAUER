#!/usr/bin/env python3
"""Run a real Combine Goodness-of-Fit (GoF) test end-to-end.

Python control-script replacement for the former datacards/run_gof.sh
(Phase 6d; that script itself dates to Phase 4, see STATUS.md "## Phase 4").
Same positional/optional arguments as the bash version.

Ties together the existing datacard/workspace scripts and drives the standard
GoF workflow (adapted from smhtt_ul/gof_tests.sh's GOF mode, house-ruled to
TauKITFlow's combine_datacards/ layout -- no MorphingSMRun2Legacy binary):

  1. place SYNCED_FILE (a shapes/convert_to_synced_shapes.py --gof output,
     containing a "${CHANNEL}_${VARIABLE}" TDirectory) where make_datacards
     expects it;
  2. produce_gof_datacard.py  -> Combine datacard;
  3. produce_gof_workspace.py -> default single-r workspace (ws.root);
  4. combine -M GoodnessOfFit on real data (observed test statistic);
  5. the same, throwing NTOYS toys (PARALLEL seeds), b-only (r=0);
  6. combineTool.py -M CollectGoodnessOfFit -> gof.json;
  7. print the observed statistic and the toy-based p-value; plotGof.py for
     the KS/AD algos.

ALGO: saturated (default) | KS | AD. NTOYS: total toys (default 300).
Requires a valid grid environment only if the datacard has to be rebuilt; the
GoF fits themselves are local (CMSSW/Combine, no xrootd).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.cmsenv import REPO_ROOT, get_fitdir, run_in_cmsenv

DEFAULT_NTUPLE_TAG = "htt_260602_2024-25_v5"
MASS = "125"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a real Combine Goodness-of-Fit (GoF) test end-to-end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("era")
    parser.add_argument("channel")
    parser.add_argument("variable")
    parser.add_argument("synced_file", type=Path)
    parser.add_argument("algo", nargs="?", default="saturated", choices=["saturated", "KS", "AD"])
    parser.add_argument("ntoys", nargs="?", type=int, default=300)
    parser.add_argument("ntuple_tag", nargs="?", default=DEFAULT_NTUPLE_TAG)
    parser.add_argument("use_asimov", nargs="?", default="0", choices=["0", "1"])
    parser.add_argument("parallel", nargs="?", type=int, default=10)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    era, channel, variable = args.era, args.channel, args.variable
    job_id = f"{era}_{channel}_{variable}"

    if not args.synced_file.is_file():
        print(f"ERROR: synced shape file not found: {args.synced_file}", file=sys.stderr)
        return 1

    fitdir = Path(get_fitdir())
    shapes_dir = fitdir / "output" / "shapes"
    shapes_dir.mkdir(parents=True, exist_ok=True)
    dest = shapes_dir / f"{era}-{channel}-{args.ntuple_tag}-{variable}.root"
    print(f"[run_gof] placing synced file: {args.synced_file} -> {dest}")
    shutil.copyfile(args.synced_file, dest)

    # --- Build datacard + workspace ---
    datacard_cmd = [
        sys.executable,
        str(REPO_ROOT / "datacards" / "produce_gof_datacard.py"),
        era,
        channel,
        variable,
        args.ntuple_tag,
    ]
    if args.use_asimov == "1":
        datacard_cmd.append("--use-asimov")
    subprocess.run(datacard_cmd, check=True)

    subprocess.run(
        [sys.executable, str(REPO_ROOT / "datacards" / "produce_gof_workspace.py"), era, channel, variable],
        check=True,
    )

    workspace = fitdir / "output" / "datacards" / f"{era}-{channel}-{variable}-gof" / channel / era / "ws.root"
    if not workspace.is_file():
        print(f"ERROR: workspace not built: {workspace}", file=sys.stderr)
        return 1

    # --- Run GoF in a dedicated working directory (combine litters cwd) ---
    gof_dir = fitdir / "output" / "gof" / job_id
    gof_dir.mkdir(parents=True, exist_ok=True)

    print(f"[run_gof] === observed GoF ({args.algo}) on real data ===")
    obs_cmd = [
        "combine",
        "-M",
        "GoodnessOfFit",
        "-n",
        f".{job_id}",
        f"--algo={args.algo}",
        "-m",
        MASS,
        "-d",
        str(workspace),
        "--fixedSignalStrength=0",
        "-v1",
    ]
    if args.algo != "saturated":
        obs_cmd.append("--plots")
    run_in_cmsenv(obs_cmd, cwd=gof_dir, unlimited_stack=True)

    print(f"[run_gof] === throwing {args.ntoys} toys over {args.parallel} seeds ===")
    toys_opt = ["--toysFreq"] if args.algo == "saturated" else []
    per = (args.ntoys + args.parallel - 1) // args.parallel
    toy_files = []
    procs = []
    logs = []
    for i in range(args.parallel):
        seed = 1230 + i
        log_path = gof_dir / f"toys_{seed}.log"
        logs.append(log_path)
        toy_cmd = [
            "combine",
            "-M",
            "GoodnessOfFit",
            "-n",
            f".{job_id}",
            f"--algo={args.algo}",
            "-m",
            MASS,
            "-d",
            str(workspace),
            "-s",
            str(seed),
            "-t",
            str(per),
            *toys_opt,
            "--fixedSignalStrength=0",
        ]
        log_fh = open(log_path, "w")
        proc = run_in_cmsenv(
            toy_cmd, cwd=gof_dir, unlimited_stack=True, background=True, stdout=log_fh, stderr=subprocess.STDOUT
        )
        procs.append((proc, log_fh))
        toy_files.append(f"higgsCombine.{job_id}.GoodnessOfFit.mH{MASS}.{seed}.root")
    for proc, log_fh in procs:
        proc.wait()
        log_fh.close()

    print("[run_gof] === collect ===")
    obs_file = f"higgsCombine.{job_id}.GoodnessOfFit.mH{MASS}.root"
    gof_json = gof_dir / f"gof_{args.algo}.json"
    run_in_cmsenv(
        [
            "combineTool.py",
            "-M",
            "CollectGoodnessOfFit",
            "--input",
            obs_file,
            *toy_files,
            "--output",
            str(gof_json),
        ],
        cwd=gof_dir,
        unlimited_stack=True,
    )

    # --- p-value / summary ---
    _print_gof_summary(gof_json, args.algo)

    if args.algo != "saturated":
        run_in_cmsenv(
            [
                "plotGof.py",
                "--statistic",
                args.algo,
                "--mass",
                f"{MASS}.0",
                "--output",
                f"gof_{args.algo}",
                str(gof_json),
            ],
            cwd=gof_dir,
            unlimited_stack=True,
            check=False,
        )

    print(f"[run_gof] done. Outputs under {gof_dir}")
    return 0


def _print_gof_summary(json_path: Path, algo: str) -> None:
    d = json.loads(json_path.read_text())
    key = next(iter(d.keys()))
    e = d[key]
    obs = e.get("obs", e.get("observed"))
    if isinstance(obs, list):
        obs = obs[0]
    toys = e.get("toy", e.get("toys", []))
    n = len(toys)
    p = (sum(1 for t in toys if t >= obs) / n) if n else float("nan")
    print("=" * 60)
    print(f"GoF result ({algo})  mass={key}")
    print(f"  observed test statistic : {obs:.4f}")
    print(f"  n_toys                  : {n}")
    print(f"  p-value (frac toys>=obs): {p:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
