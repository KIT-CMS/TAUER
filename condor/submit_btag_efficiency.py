#!/usr/bin/env python3
"""
HTCondor submission for the b-tag efficiency measurement
(btag_efficiencies/run_btag_efficiency.py).

Fans out per --step, matching how the underlying scripts are actually
parallelisable (see btag_efficiencies/run_btag_efficiency.py's module
docstring for why the two steps have different granularity):

  --step preselect  -> one job per (era, channel) — this is
                       TauFakeFactors/preselection.py, CPU/IO-bound per
                       channel's sample list, same shape as condor/submit_shapes.py.
  --step calculate  -> one job per era — btag_efficiencies/calculate_efficiency.py
                       processes every channel in its own config's `channels:`
                       list internally in one job.
  --step all        -> both of the above (preselect jobs first is implied by
                       nothing here — this only submits, it does not wait for
                       the preselect jobs to finish before submitting
                       calculate jobs; run --step preselect, wait for
                       completion, then --step calculate for a real run).

Example:

    python3 condor/submit_btag_efficiency.py --step preselect \\
        --eras 2024,2025 --channels et,mt,tt --dry-run

    python3 condor/submit_btag_efficiency.py --step calculate \\
        --eras 2024,2025 --dry-run

Era/channel lists default to config.analysis.RUN3_ERAS / get_channels() (the
central config), never hardcoded here — same convention as the other
condor/submit_*.py scripts.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, make_tag, submit
from config.analysis import RUN3_ERAS, get_channels


def csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--step", choices=["preselect", "calculate", "all"], default="all")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS))
    p.add_argument("--channels", type=csv, default=get_channels(),
                    help="Only used for --step preselect/all (calculate is one job per era).")
    p.add_argument("--regenerate-configs", action="store_true")
    p.add_argument("--nthreads", type=int, default=8)
    p.add_argument("--tag", default=None)
    p.add_argument("--request-cpus", type=int, default=8)
    p.add_argument("--request-memory-mb", type=int, default=8000)
    p.add_argument("--request-disk-kb", type=int, default=10_000_000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def build_jobs(args) -> list:
    jobs = []
    if args.step in ("preselect", "all"):
        for era in args.eras:
            for channel in args.channels:
                job_args = f"--era {era} --channel {channel} --step preselect --nthreads {args.nthreads}"
                if args.regenerate_configs:
                    job_args += " --regenerate-configs"
                jobs.append(JobSpec(name=f"presel_{era}_{channel}", arguments=job_args))
    if args.step in ("calculate", "all"):
        for era in args.eras:
            job_args = f"--era {era} --step calculate"
            jobs.append(JobSpec(name=f"calc_{era}", arguments=job_args))
    return jobs


def main():
    args = parse_args()
    tag = args.tag or make_tag("btag-efficiency")
    jobs = build_jobs(args)
    plan = SubmissionPlan(
        stage="btag_efficiency",
        tag=tag,
        entry_point="btag_efficiencies/run_btag_efficiency.py",
        jobs=jobs,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )
    return submit(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
