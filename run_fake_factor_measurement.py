#!/usr/bin/env python3
"""
Single, documented entry point for TauFakeFactors' fake-factor measurement
step, run end-to-end for a given era/channels.

Before this script, running the FF measurement meant knowing to invoke four
separate run.py modes by hand, in the right order (GEN-TFF-CONFIGS, PRESEL,
FF, FF-CORR) -- easy to run out of order or skip a step, and nothing tied
them together as "one step of the pipeline". This script chains them:

    1. config/generate_tff_configs.py   -- regenerate TauFakeFactors'
       per-channel preselection_{ch}.yaml event_selection/mc_weights from
       TauKITFlow's central config/cuts.yaml + config/weights.yaml (Phase 5.2/6e
       single-sourcing -- see those files' docstrings). Always run first so the
       measurement uses the *current* central cuts, not a stale generated copy.
    2. TauFakeFactors/preselection.py    -- per channel.
    3. TauFakeFactors/ff_calculation.py  -- per channel (fake_factors_{channel}.yaml).
    4. TauFakeFactors/ff_corrections.py  -- per channel (corrections_{channel}.yaml).

Output lands exactly where it already did via run.py's PRESEL/FF/FF-CORR
modes -- this script doesn't change output locations, it just chains the
existing steps -- so shapes/preselect.py's --tff-dir and
shapes/produce_shapes.py's --*-friend-directory (fed from run.py's
FF_FRIENDS_DIR) keep working unchanged.

Example:

    python3 run_fake_factor_measurement.py --era 2024 --channels et,mt,tt

Equivalent to, but replacing the need to manually run, in order:

    python3 run.py GEN-TFF-CONFIGS --era 2024 --channels et,mt,tt
    python3 run.py PRESEL          --era 2024 --channels et,mt,tt
    python3 run.py FF              --era 2024 --channels et,mt,tt
    python3 run.py FF-CORR         --era 2024 --channels et,mt,tt

(run.py's GEN-TFF-CONFIGS/PRESEL/FF/FF-CORR modes are kept as-is for granular
single-step reruns -- e.g. rerunning only FF-CORR after tweaking a correction
-- this script is the "run the whole measurement" convenience path on top,
not a replacement for them.)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))

from config.analysis import RUN3_ERAS, get_channels


def csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--era", required=True, choices=RUN3_ERAS)
    p.add_argument("--channels", type=csv, default=get_channels())
    p.add_argument("--steps", type=csv, default=["gen-configs", "presel", "ff", "ff-corr"],
                    help="Subset/order of steps to run (default: all four, in order).")
    p.add_argument("--nthreads", type=int, default=8)
    p.add_argument("--ff-config", default=None, help="Override --config-file for the FF step.")
    p.add_argument("--ff-corr-config", default=None, help="Override --config-file for the FF-CORR step.")
    return p.parse_args()


def _tff_env() -> dict:
    env = os.environ.copy()
    tff_root = str(_REPO_ROOT / "TauFakeFactors")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [tff_root, env.get("PYTHONPATH", "")]))
    return env


def _run(cmd: list[str], **kwargs) -> None:
    print(f"[run_fake_factor_measurement] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=_REPO_ROOT, **kwargs)


def main() -> int:
    args = parse_args()
    era = args.era
    channels_csv = ",".join(args.channels)
    tff_env = _tff_env()

    if "gen-configs" in args.steps:
        _run([
            sys.executable, "config/generate_tff_configs.py",
            "--era", era, "--channels", channels_csv,
        ])

    if "presel" in args.steps:
        for channel in args.channels:
            config_file = f"TauFakeFactors/configs/smhtt_ul/{era}/preselection_{channel}.yaml"
            _run([
                sys.executable, "TauFakeFactors/preselection.py",
                "--config-file", config_file,
                "--nthreads", str(args.nthreads),
            ], env=tff_env)

    if "ff" in args.steps:
        # Note: TauFakeFactors/configs/smhtt_ul/{era}/ ships one config PER
        # CHANNEL (fake_factors_et.yaml, fake_factors_mt.yaml, ...), not one
        # joined-multi-channel file -- run.py's FF mode was fixed to loop
        # per-channel the same way (see STATUS.md Phase 6e), not repeated here.
        if args.ff_config:
            _run([sys.executable, "TauFakeFactors/ff_calculation.py", "--config-file", args.ff_config], env=tff_env)
        else:
            for channel in args.channels:
                _run([
                    sys.executable, "TauFakeFactors/ff_calculation.py",
                    "--config-file", f"TauFakeFactors/configs/smhtt_ul/{era}/fake_factors_{channel}.yaml",
                ], env=tff_env)

    if "ff-corr" in args.steps:
        # Same per-channel-file note as above; also, the actual filename is
        # `corrections_{channel}.yaml`, not `ff_corrections_{channel}.yaml`
        # -- run.py's FF-CORR mode was fixed the same way (see STATUS.md
        # Phase 6e).
        if args.ff_corr_config:
            _run([sys.executable, "TauFakeFactors/ff_corrections.py", "--config-file", args.ff_corr_config], env=tff_env)
        else:
            for channel in args.channels:
                _run([
                    sys.executable, "TauFakeFactors/ff_corrections.py",
                    "--config-file", f"TauFakeFactors/configs/smhtt_ul/{era}/corrections_{channel}.yaml",
                ], env=tff_env)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
