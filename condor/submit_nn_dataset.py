#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from common.sample_paths import build_shape_output_paths
from common.analysis import get_channels


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag; derives the configs and datasets directories (run.py TRAIN-DATASET --ntupletag).")
    p.add_argument("--channels", type=csv, default=get_channels(),
                    help="Comma-separated channels, one job each: combine_folds() merges every part of a dataset directory, so the eras of a channel stay in one job.")
    p.add_argument("--train-eras", type=csv, default=None, help="Comma-separated eras merged into the dataset (run.py's --train-eras; default: every era in the configs directory).")
    p.add_argument("--user", default=getpass.getuser(), help="Grid storage username for the --ntupletag-derived paths (default: current user).")
    p.add_argument("--recreate", action="store_true", help="Rebuild the existing per-process parts and folds (create_training_dataset.py --recreate).")
    p.add_argument("--tag", default=None)
    p.add_argument("--request-cpus", type=int, default=4)
    p.add_argument("--request-memory-mb", type=int, default=96000)  # the merged 2022-2025 mt fold0 is ~20 GB, combine_folds holds it ~2-3 times
    p.add_argument("--request-disk-kb", type=int, default=10_000_000)
    p.add_argument("--dry-run", action="store_true", help="Validate classads via `condor_submit -dry-run`, do not queue jobs.")
    return p.parse_args(argv)


def build_jobs(args) -> list[JobSpec]:
    datasets = f"{build_shape_output_paths(args.ntupletag, user=args.user).training}/datasets/stage0"  # labels of both STXS stages
    jobs = []
    for channel in args.channels:
        job_args = ["TRAIN-DATASET", "--channels", channel, "--ntupletag", args.ntupletag, "--user", args.user, "--base-dataset-dir", f"{datasets}/{channel}"]
        if args.train_eras:
            job_args += ["--train-eras", ",".join(args.train_eras)]
        if args.recreate:
            job_args.append("--recreate")
        jobs.append(JobSpec(name=f"dataset_{channel}", arguments=" ".join(job_args)))
    return jobs


def build_plan(args) -> SubmissionPlan:
    return SubmissionPlan(
        stage="nn_dataset",
        tag=args.tag,
        entry_point="run.py",
        jobs=build_jobs(args),
        ntupletag=args.ntupletag,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
