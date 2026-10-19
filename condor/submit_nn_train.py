#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from common.analysis import get_channels


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag; derives the feather folds (run.py TRAIN --ntupletag).")
    p.add_argument("--channels", type=csv, default=get_channels(), help="Comma-separated channels, trained one after the other by the one job (as run.py TRAIN does).")
    p.add_argument("--user", default=getpass.getuser(), help="Grid storage username for the --ntupletag-derived paths (default: current user).")
    p.add_argument("--tag", default=None, help="Matches run.py's --tag/TAG: the law version is <tag>_<channel>.")
    p.add_argument("--train-task", default=None, help="Law task name (default: run.py's, RunAllCENNTConfusionMatrixWorkflow).")
    p.add_argument("--cuda-device", default=None,
                    help="Device indices among the GPUs the job sees (default: 0..N-1 of --request-gpus; run.py's default without GPUs). "
                         "Condor restricts the job to its assigned GPUs through CUDA_VISIBLE_DEVICES, so the indices are always relative to those.")
    p.add_argument("--workers", default=None, help="Law workers (default: run.py's).")
    p.add_argument("--request-gpus", type=int, default=0, help="request_gpus of the job (0: none).")
    p.add_argument("--request-cpus", type=int, default=4)
    p.add_argument("--request-memory-mb", type=int, default=32000)
    p.add_argument("--request-disk-kb", type=int, default=10_000_000)
    p.add_argument("--dry-run", action="store_true", help="Validate classads via `condor_submit -dry-run`, do not queue jobs.")
    return p.parse_args(argv)


def build_jobs(args) -> list[JobSpec]:
    cuda_device = args.cuda_device or (",".join(map(str, range(args.request_gpus))) if args.request_gpus else None)
    job_args = ["TRAIN", "--channels", ",".join(args.channels), "--ntupletag", args.ntupletag, "--user", args.user]
    for flag, value in (("--tag", args.tag), ("--train-task", args.train_task), ("--cuda-device", cuda_device), ("--workers", args.workers)):
        if value:
            job_args += [flag, value]
    return [JobSpec(name="train_" + "_".join(args.channels), arguments=" ".join(job_args))]


def build_plan(args) -> SubmissionPlan:
    return SubmissionPlan(
        stage="nn_train",
        tag=args.tag,
        entry_point="run.py",
        jobs=build_jobs(args),
        ntupletag=args.ntupletag,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
        extra_classads={"request_gpus": str(args.request_gpus)} if args.request_gpus else {},
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
