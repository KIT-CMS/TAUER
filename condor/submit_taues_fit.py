#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit

DEFAULT_CATEGORIES = ["DM0", "DM1", "DM10_11", "Inclusive"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--era", default="2018", help="Run2 era with tauES/embedding support (2018 today).")
    p.add_argument("--channels", dest="channel", default="mt")
    p.add_argument("--categories", type=csv, default=DEFAULT_CATEGORIES)
    p.add_argument("--input-file", required=True, help="TauES shapes.root of run.py SHAPES --special-analysis TauES.")
    p.add_argument("--variable", default=None, help="Discriminant of the shapes file (default: tau_es.taues_categories.discriminator_variable).")
    p.add_argument("--output-dir", required=True, help="Base output directory; a per-category subdirectory is appended.")
    p.add_argument("--real-data", action="store_true")
    p.add_argument("--bbb", action="store_true")
    p.add_argument("--skip-fit", action="store_true", help="Only build datacards/workspaces, skip the MultiDimFit scan (faster smoke test).")
    p.add_argument("--points", type=int, default=30)
    p.add_argument("--tag", default=None)
    p.add_argument("--request-cpus", type=int, default=1)
    p.add_argument("--request-memory-mb", type=int, default=2000)
    p.add_argument("--request-disk-kb", type=int, default=2_000_000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def build_jobs(args) -> list:
    jobs = []
    for category in args.categories:
        job_args = [
            f"--era {args.era}",
            f"--channels {args.channel}",
            f"--category {category}",
            f"--input-file {args.input_file}",
            f"--output-dir {args.output_dir}",
            f"--points {args.points}",
        ]
        if args.variable:
            job_args.append(f"--variable {args.variable}")
        if args.real_data:
            job_args.append("--real-data")
        if args.bbb:
            job_args.append("--bbb")
        if args.skip_fit:
            job_args.append("--skip-fit")
        jobs.append(JobSpec(name=f"{args.era}_{category}", arguments=" ".join(job_args)))
    return jobs


def build_plan(args) -> SubmissionPlan:
    jobs = build_jobs(args)
    return SubmissionPlan(
        stage="taues_fit",
        tag=args.tag,
        entry_point="tau_es/run_taues_category.py",
        jobs=jobs,
        env_mode="cmssw",
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
