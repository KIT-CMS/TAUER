#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.sample_paths import build_shape_output_paths
from condor.common import JobSpec, SubmissionPlan, csv, submit
from config.analysis import RUN3_ERAS, get_channels


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--master-config", required=True, help="Path to the full trainings/create_training_dataset.py --config YAML (config[channel][era][process]...).")
    p.add_argument("--common-setup-config", default=None)
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS))
    p.add_argument("--channels", type=csv, default=get_channels())
    p.add_argument("--ntupletag", default=None, help="CROWN ntuple production tag; derives the default --base-dataset-dir (as run.py does).")
    p.add_argument("--user", default=getpass.getuser(), help="Grid storage username (default: current user).")
    p.add_argument("--base-dataset-dir", default=None, help="Default: derived from --ntupletag/--user (run.py's --base-dataset-dir).")
    p.add_argument("--recreate", action="store_true")
    p.add_argument("--tag", default=None)
    p.add_argument("--request-cpus", type=int, default=2)
    p.add_argument("--request-memory-mb", type=int, default=8000)
    p.add_argument("--request-disk-kb", type=int, default=10_000_000)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not args.base_dataset_dir:
        if not args.ntupletag:
            p.error("--ntupletag or --base-dataset-dir is required")
        args.base_dataset_dir = f"{build_shape_output_paths(args.ntupletag, user=args.user).training}/datasets"
    return args


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
                f"--base-dataset-dir {args.base_dataset_dir}",
            ]
            if args.common_setup_config:
                job_args.append(f"--common-setup-config {args.common_setup_config}")
            if args.recreate:
                job_args.append("--recreate")
            jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
    return jobs


def main():
    args = parse_args()
    plan = SubmissionPlan(
        stage="training",
        tag=args.tag,
        entry_point="trainings/create_training_dataset.py",
        jobs=[],
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )
    plan.jobs = build_jobs(args, plan.run_dir)
    return submit(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
