#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from common.analysis import RUN3_ERAS, get_channels

FF_CONDA_ENV = "tauer"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--steps", type=csv, default=["presel", "calc"],
                   help="Subset/order of BTAG's steps: gen-configs,presel,calc (presel: one job per (era, channel); "
                        "calc: one job per era; gen-configs is prepended to every presel job).")
    p.add_argument("--ntupletag", required=True,
                   help="CROWN ntuple production tag, e.g. htt_260903_24-26_btag.")
    p.add_argument("--selection-friend", default=None,
                   help="CROWN selection-mask FRIEND tree version tag, e.g. selection_260819.")
    p.add_argument("--additional-friends", default=None, help="Comma-separated extra CROWN FRIEND tree tags attached in the preselection (run.py --additional-friends).")
    p.add_argument("--user", default=getpass.getuser(),
                   help="Grid storage username, resolved here on the submission host -- "
                        "getuser() fails on the condor execute node.")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS))
    p.add_argument("--channels", type=csv, default=get_channels(),
                    help="Only used for the presel step (calc is one job per era).")
    p.add_argument("--nthreads", type=int, default=8)
    p.add_argument("--tag", default=None, help="Label of the condor run dir and of the btag workdir (run.py --tag, default: --ntupletag).")
    p.add_argument("--request-cpus", type=int, default=8)
    p.add_argument("--request-memory-mb", type=int, default=16000)
    p.add_argument("--request-disk-kb", type=int, default=10_000_000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def build_jobs(args) -> list:
    jobs = []
    common = f" --ntupletag {args.ntupletag} --user {args.user}" + (f" --tag {args.tag}" if args.tag else "")
    if "presel" in args.steps:
        steps = ",".join(step for step in ("gen-configs", "presel") if step in args.steps)
        for era in args.eras:
            for channel in args.channels:
                job_args = f"BTAG --era {era} --channels {channel} --steps {steps} --nthreads {args.nthreads}{common}"
                if args.selection_friend:
                    job_args += f" --selection-friend {args.selection_friend}"
                if args.additional_friends:
                    job_args += f" --additional-friends {args.additional_friends}"
                jobs.append(JobSpec(name=f"presel_{era}_{channel}", arguments=job_args))
    if "calc" in args.steps:
        for era in args.eras:
            jobs.append(JobSpec(name=f"calc_{era}", arguments=f"BTAG --era {era} --steps calc{common}"))
    return jobs


def build_plan(args) -> SubmissionPlan:
    jobs = build_jobs(args)
    return SubmissionPlan(
        stage="btag_efficiencies",
        tag=args.tag,
        entry_point="run.py",
        jobs=jobs,
        ntupletag=args.ntupletag,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
        conda_env=FF_CONDA_ENV,
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
