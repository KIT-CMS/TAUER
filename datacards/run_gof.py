#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.environment import REPO_ROOT, get_fitdir, run_in_cmsenv
from datacards import MASS, THEORY_NUISANCES, gof_card_dir


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a real Combine Goodness-of-Fit (GoF) test end-to-end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("era", help="Comma-separated eras combine the single era/channel GoF cards of the same variable (made first).")
    parser.add_argument("channel", help="Comma-separated channels, as era.")
    parser.add_argument("variable")
    parser.add_argument("shapes", type=Path, help="shapes.root of run.py SHAPES for this era and channel, holding <variable>/<channel>/<process>")
    parser.add_argument("algo", nargs="?", default="saturated", choices=["saturated", "KS", "AD"])
    parser.add_argument("ntoys", nargs="?", type=int, default=300)
    parser.add_argument("use_asimov", nargs="?", default="0", choices=["0", "1"])
    parser.add_argument("parallel", nargs="?", type=int, default=10)
    parser.add_argument("--postfit", action="store_true", help="Also run the b-only fit (signal and theory frozen) and write the pre-/post-fit shapes and pulls.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    era, channel, variable = args.era, args.channel, args.variable
    eras, channels = era.split(","), channel.split(",")
    combined = len(eras) * len(channels) > 1
    job_id = f"{'cmb' if len(eras) > 1 else era}_{'cmb' if len(channels) > 1 else channel}_{variable}"
    fitdir = Path(get_fitdir())

    if combined:
        card_dir = fitdir / "output" / "datacards" / f"{job_id}-gof"
        card_dir.mkdir(parents=True, exist_ok=True)
        cards = [f"{c}_{e}={sorted(gof_card_dir(fitdir, e, c, variable).glob('CMS_*.txt'))[0]}" for e in eras for c in channels]
        run_in_cmsenv(["sh", "-c", f"combineCards.py {' '.join(cards)} > combined.txt"], cwd=card_dir)
        run_in_cmsenv(["text2workspace.py", "combined.txt", "-o", "ws.root", "-m", MASS], cwd=card_dir, unlimited_stack=True)
        workspace, card = card_dir / "ws.root", card_dir / "combined.txt"
    else:
        if not args.shapes.is_file():
            print(f"ERROR: shapes file not found: {args.shapes}", file=sys.stderr)
            return 1
        workspace, card = build_single_card(args, fitdir)
        if workspace is None:
            return 1

    return run_gof(args, job_id, workspace, card, fitdir)


def build_single_card(args, fitdir):
    """Datacard and workspace of one era/channel/variable, (None, None) if the workspace was not built."""
    era, channel, variable = args.era, args.channel, args.variable
    datacard_cmd = [
        sys.executable,
        str(REPO_ROOT / "datacards" / "produce_datacard.py"),
        era,
        channel,
        "gof",
        str(args.shapes),
        f"--variable={variable}",
    ]
    if args.use_asimov == "1":
        datacard_cmd.append("--use-asimov")
    subprocess.run(datacard_cmd, check=True)

    subprocess.run(
        [sys.executable, str(REPO_ROOT / "datacards" / "produce_workspace.py"), era, "gof", f"--channels={channel}", f"--variable={variable}"],
        check=True,
    )

    workspace = gof_card_dir(fitdir, era, channel, variable) / "ws.root"
    if not workspace.is_file():
        print(f"ERROR: workspace not built: {workspace}", file=sys.stderr)
        return None, None
    return workspace, sorted(gof_card_dir(fitdir, era, channel, variable).glob("CMS_*.txt"))[0]


def run_gof(args, job_id, workspace, card, fitdir):
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
        *([f"--freezeParameters={THEORY_NUISANCES}"] if THEORY_NUISANCES else []),
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
            *([f"--freezeParameters={THEORY_NUISANCES}"] if THEORY_NUISANCES else []),
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

    # the p-value plot of the toys, for every algorithm (saturated included, as in smhtt_ul's gof_tests.sh)
    run_in_cmsenv(
        ["plotGof.py", "--statistic", args.algo, "--mass", f"{MASS}.0", "--output", f"gof_{args.algo}", str(gof_json)],
        cwd=gof_dir, unlimited_stack=True, check=False,
    )

    if args.postfit:
        print("[run_gof] === b-only post-fit ===")
        run_in_cmsenv(
            ["combine", "-M", "FitDiagnostics", "-m", MASS, "-d", str(workspace), "-n", f".{job_id}", "--setParameters", "r=0",
             f"--freezeParameters={','.join(filter(None, ['r', THEORY_NUISANCES]))}", "--robustFit", "1", "--robustHesse", "1",
             "--cminDefaultMinimizerStrategy", "0", "--X-rtd", "MINIMIZER_analytic"],
            cwd=gof_dir, unlimited_stack=True,
        )
        fit = f"fitDiagnostics.{job_id}.root"
        diff_nuisances = "$CMSSW_BASE/src/HiggsAnalysis/CombinedLimit/test/diffNuisances.py"
        run_in_cmsenv(["sh", "-c", f"python3 {diff_nuisances} {fit} -a -f html > nuisances.html"], cwd=gof_dir, check=False)
        run_in_cmsenv(
            ["PostFitShapesFromWorkspace", "-m", MASS, "-w", str(workspace), "-d", str(card), "--output", f"{job_id}-shapes.root",
             "-f", f"{fit}:fit_b", "--postfit", "--skip-proc-errs"],
            cwd=gof_dir, unlimited_stack=True,
        )

    print(f"[run_gof] done. Outputs under {gof_dir}")
    return 0


def gof_pvalue(json_path: Path) -> tuple:
    """(observed test statistic, number of toys, p-value = fraction of toys >= observed) of a CollectGoodnessOfFit json."""
    e = next(iter(json.loads(Path(json_path).read_text()).values()))
    obs = e.get("obs", e.get("observed"))
    obs = obs[0] if isinstance(obs, list) else obs
    toys = e.get("toy", e.get("toys", []))
    return obs, len(toys), (sum(1 for t in toys if t >= obs) / len(toys)) if toys else float("nan")


def _print_gof_summary(json_path: Path, algo: str) -> None:
    obs, n, p = gof_pvalue(json_path)
    print("=" * 60)
    print(f"GoF result ({algo})")
    print(f"  observed test statistic : {obs:.4f}")
    print(f"  n_toys                  : {n}")
    print(f"  p-value (frac toys>=obs): {p:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
