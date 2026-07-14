#!/usr/bin/env python3
"""
HTCondor submission for trainings/create_training_dataset.py.

Scope note (see STATUS.md, "Phase 2c"): the actual NN training loop lives
under trainings/uncertainty-aware-training/, which already has its own
law-based (local, subprocess-driven) task graph
(_law_workflow_ff.py / _law_CENNT_workflow.py) — that is left untouched here,
per the instruction to keep the law dependency as-is rather than grow or
duplicate it. What genuinely has *no* HTCondor submission today, and is what
this script covers, is the top-level trainings/create_training_dataset.py
dataset-preparation step (ROOT shapes -> feather folds), which is the
condor-shaped, CPU/IO-bound, per-(channel,era)-parallelisable piece of the
training pipeline.

trainings/create_training_dataset.py takes a single --config YAML nested as
config[channel][era][process][...] and processes every (channel, era) present
in it in one process. To fan that out one job per (era, channel) without
modifying create_training_dataset.py, this script *slices* a user-provided
master config into one filtered YAML per (era, channel) pair (written under
the run directory) and points each condor job at its own slice.

Example:

    python3 condor/submit_training.py \\
        --master-config trainings/full_dataset_config.yaml \\
        --eras 2024,2025 --channels et,mt,tt \\
        --base-dataset-directory /ceph/sgiappic/smhtt_ul_new/training_datasets \\
        --dry-run

Era/channel lists default to config.analysis.RUN3_ERAS / get_channels(),
intersected with what's actually present as keys in --master-config so a job
is never generated for a (era, channel) with nothing to do.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, make_tag, submit
from config.analysis import RUN3_ERAS, get_channels


def csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--master-config", required=True, help="Path to the full trainings/create_training_dataset.py --config YAML (config[channel][era][process]...).")
    p.add_argument("--common-setup-config", default=None)
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS))
    p.add_argument("--channels", type=csv, default=get_channels())
    p.add_argument("--base-dataset-directory", required=True)
    p.add_argument("--recreate", action="store_true")
    p.add_argument("--tag", default=None)
    p.add_argument("--request-cpus", type=int, default=2)
    p.add_argument("--request-memory-mb", type=int, default=8000)
    p.add_argument("--request-disk-kb", type=int, default=10_000_000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def slice_config(master: dict, channel: str, era: str) -> dict | None:
    channel_dict = master.get(channel)
    if not isinstance(channel_dict, dict):
        return None
    # YAML parses unquoted era keys like `2024` as int, not str; match either.
    era_key = era if era in channel_dict else next(
        (k for k in channel_dict if str(k) == str(era)), None
    )
    if era_key is None:
        return None
    return {channel: {era_key: channel_dict[era_key]}}


def build_jobs(args, run_dir: Path) -> list:
    master = yaml.safe_load(Path(args.master_config).read_text())
    jobs = []
    slice_dir = run_dir / "configs"
    slice_dir.mkdir(parents=True, exist_ok=True)

    for channel in args.channels:
        for era in args.eras:
            sliced = slice_config(master, channel, era)
            if sliced is None:
                continue  # nothing for this (channel, era) in the master config
            slice_path = slice_dir / f"{channel}_{era}.yaml"
            slice_path.write_text(yaml.safe_dump(sliced, default_flow_style=False))

            job_args = [
                f"--config {slice_path}",
                f"--base-dataset-directory {args.base_dataset_directory}",
            ]
            if args.common_setup_config:
                job_args.append(f"--common-setup-config {args.common_setup_config}")
            if args.recreate:
                job_args.append("--recreate")
            jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
    return jobs


def main():
    args = parse_args()
    tag = args.tag or make_tag("training")
    from condor.common import REPO_ROOT
    run_dir = REPO_ROOT / "condor" / "run" / "training" / tag

    jobs = build_jobs(args, run_dir)
    plan = SubmissionPlan(
        stage="training",
        tag=tag,
        entry_point="trainings/create_training_dataset.py",
        jobs=jobs,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )
    return submit(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
