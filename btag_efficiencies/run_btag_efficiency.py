#!/usr/bin/env python3
"""
Single documented entry point for the b-tag efficiency measurement.

This is what condor/submit_btag_efficiency.py wraps for cluster submission,
and what you'd run by hand for a quick local (re)run. It has two steps,
selectable via --step (run one, or "all" for both in sequence):

  preselect  -- runs TauFakeFactors/preselection.py (reused as-is; it's
                already fully config-driven, see config/generate_tff_configs.py's
                module docstring for the analogous FF-measurement case) against
                btag_efficiencies/configs/{era}/preselection_{channel}.yaml,
                for one (era, channel).
  calculate  -- runs btag_efficiencies/calculate_efficiency.py against
                btag_efficiencies/configs/{era}/btag_efficiency.yaml, for one
                era (it processes every channel listed in that config's own
                `channels:` block internally, so there is one job per era here,
                not per (era, channel)).

Example (both steps, one era/channel):

    python3 btag_efficiencies/run_btag_efficiency.py \\
        --era 2024 --channel mt --step all

The event_selection cuts these configs use are regenerated from central
config by btag_efficiencies/generate_configs.py -- run that first (or via
--regenerate-configs here) whenever config/cuts.yaml changes upstream.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TFF_ROOT = _REPO_ROOT / "TauFakeFactors"
_CONFIG_ROOT = _REPO_ROOT / "btag_efficiencies" / "configs"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--era", required=True)
    p.add_argument("--channel", default=None, help="Required for --step preselect/all.")
    p.add_argument("--step", choices=["preselect", "calculate", "all"], default="all")
    p.add_argument("--regenerate-configs", action="store_true",
                    help="Run btag_efficiencies/generate_configs.py for this era first.")
    p.add_argument("--nthreads", type=int, default=8)
    return p.parse_args()


def _run(cmd: list[str], *, need_tff_on_path: bool = False) -> None:
    print(f"[run_btag_efficiency] $ {' '.join(cmd)}")
    env = os.environ.copy()
    if need_tff_on_path:
        # preselection.py does `import helper.filters` / `import CustomLogging`
        # assuming TauFakeFactors/ itself is on sys.path (same as run.sh's
        # `PRESEL`/`FF`/`FF-CORR` modes: `PYTHONPATH=...:$PWD/TauFakeFactors`).
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(_TFF_ROOT), env.get("PYTHONPATH", "")]))
    subprocess.run(["nice", "-n", "19", *cmd], check=True, cwd=_REPO_ROOT, env=env)


def main() -> int:
    args = parse_args()

    if args.regenerate_configs:
        _run([
            sys.executable, str(_REPO_ROOT / "btag_efficiencies" / "generate_configs.py"),
            "--era", args.era,
            "--channels", args.channel or "all",
        ])

    if args.step in ("preselect", "all"):
        if not args.channel:
            raise SystemExit("--channel is required for --step preselect/all")
        presel_config = _CONFIG_ROOT / args.era / f"preselection_{args.channel}.yaml"
        if not presel_config.exists():
            raise SystemExit(f"No btag_efficiencies preselection config for era={args.era} channel={args.channel}: {presel_config}")
        _run([
            sys.executable, str(_TFF_ROOT / "preselection.py"),
            "--config-file", str(presel_config),
            "--nthreads", str(args.nthreads),
        ], need_tff_on_path=True)

    if args.step in ("calculate", "all"):
        eff_config = _CONFIG_ROOT / args.era / "btag_efficiency.yaml"
        if not eff_config.exists():
            raise SystemExit(f"No btag_efficiency.yaml for era={args.era}: {eff_config}")
        _run([
            sys.executable, str(_REPO_ROOT / "btag_efficiencies" / "calculate_efficiency.py"),
            "--config-file", str(eff_config),
        ])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
