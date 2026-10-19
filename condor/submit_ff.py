#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from common.analysis import RUN3_ERAS, ff_config_era

DEFAULT_FF_CHANNELS = ["et", "mt", "tt"]  # em has no FF configs
DEFAULT_STEPS = ["gen-configs", "presel", "ff", "ff-corr"]
FF_CONDA_ENV = "tauer"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS), help="Comma-separated eras (default: all Run3 eras from common.analysis).")
    p.add_argument("--channels", type=csv, default=list(DEFAULT_FF_CHANNELS), help="Comma-separated channels (default: et,mt,tt).")
    p.add_argument("--steps", type=csv, default=list(DEFAULT_STEPS),
                    help="Subset/order of FF-MEASURE's steps: gen-configs,presel,ff,ff-corr.")
    p.add_argument("--split-by-channel", action="store_true", help="One job per (era, channel) instead of one job per era.")
    p.add_argument("--nthreads", type=int, default=8)
    p.add_argument("--ff-config", default=None, help="Override --config-file for the FF step (only meaningful for a single channel).")
    p.add_argument("--ff-corr-config", default=None, help="Override --config-file for the FF-CORR step (same caveat as --ff-config).")
    p.add_argument("--ntupletag", default=None, help="CROWN ntuple production tag -- required whenever --steps includes presel/ff/ff-corr.")
    p.add_argument("--selection-friend", default=None, help="CROWN selection-mask FRIEND tree version tag.")
    p.add_argument("--additional-friends", default=None, help="Comma-separated extra CROWN FRIEND tree tags attached in the preselection (run.py --additional-friends).")
    p.add_argument("--correction-tag", default=None, help="Override corrections_{channel}.yaml's correction_tag (nests the ff-corr step's output).")
    p.add_argument("--user", default=getpass.getuser(),
                    help="Grid storage username, resolved here on the submission host -- "
                         "getpass.getuser() fails on the condor execute node's container.")
    p.add_argument("--tag", default=None, help="Label of the condor run dir and of the FF workdir (run.py --tag, default: --ntupletag).")
    p.add_argument("--request-cpus", type=int, default=None, help="Default: --nthreads.")
    p.add_argument(
        "--request-memory-mb", type=int, default=32000,
        help="32000 keeps headroom for the largest era (2025, 41.9M entries) -- 16000 held jobs "
             "whose preselected data.root exceeded ~20M entries.",
    )
    p.add_argument("--request-disk-kb", type=int, default=4_000_000)
    p.add_argument("--dry-run", action="store_true", help="Validate classads via `condor_submit -dry-run`, do not queue jobs.")
    args = p.parse_args(argv)
    if not args.ntupletag and {"presel", "ff", "ff-corr"} & set(args.steps):
        p.error(
            "--ntupletag is required whenever --steps includes presel/ff/ff-corr (common_settings.yaml "
            "no longer carries a hardcoded default ntuple_path/output_path/file_path/workdir_name)."
        )
    return args


def collapse_eras(eras: list[str]) -> list[tuple[str, list[str]]]:
    """Collapse eras sharing a TauFakeFactors config era (2022preEE+2022postEE -> "2022",
    etc. -- see common.analysis.ff_config_era) onto one representative: both halves read/
    write the same preselection output, so submitting both races two identical jobs on the
    same files instead of splitting work. Returns [(representative era, all eras it stands
    for)], input order kept."""
    grouped: dict[str, list[str]] = {}
    for era in eras:
        grouped.setdefault(ff_config_era(era), []).append(era)
    return [(members[0], members) for members in grouped.values()]


def build_jobs(args) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    steps_csv = ",".join(args.steps)
    for era, _ in collapse_eras(args.eras):
        if args.split_by_channel:
            for channel in args.channels:
                job_args = [
                    "FF-MEASURE",
                    f"--era {era}",
                    f"--channels {channel}",
                    f"--steps {steps_csv}",
                    f"--nthreads {args.nthreads}",
                ]
                if args.ff_config:
                    job_args.append(f"--ff-config {args.ff_config}")
                if args.ff_corr_config:
                    job_args.append(f"--ff-corr-config {args.ff_corr_config}")
                if args.ntupletag:
                    job_args.append(f"--ntupletag {args.ntupletag}")
                if args.selection_friend:
                    job_args.append(f"--selection-friend {args.selection_friend}")
                if args.additional_friends:
                    job_args.append(f"--additional-friends {args.additional_friends}")
                if args.tag:
                    job_args.append(f"--tag {args.tag}")
                if args.correction_tag:
                    job_args.append(f"--correction-tag {args.correction_tag}")
                job_args.append(f"--user {args.user}")
                jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
        else:
            job_args = [
                "FF-MEASURE",
                f"--era {era}",
                f"--channels {','.join(args.channels)}",
                f"--steps {steps_csv}",
                f"--nthreads {args.nthreads}",
            ]
            if args.ff_config:
                job_args.append(f"--ff-config {args.ff_config}")
            if args.ff_corr_config:
                job_args.append(f"--ff-corr-config {args.ff_corr_config}")
            if args.ntupletag:
                job_args.append(f"--ntupletag {args.ntupletag}")
            if args.selection_friend:
                job_args.append(f"--selection-friend {args.selection_friend}")
            if args.additional_friends:
                job_args.append(f"--additional-friends {args.additional_friends}")
            if args.tag:
                job_args.append(f"--tag {args.tag}")
            if args.correction_tag:
                job_args.append(f"--correction-tag {args.correction_tag}")
            job_args.append(f"--user {args.user}")
            jobs.append(JobSpec(name=era, arguments=" ".join(job_args)))
    return jobs


def build_plan(args) -> SubmissionPlan:
    for era, members in collapse_eras(args.eras):
        if len(members) > 1:
            print(f"[submit_ff] {'+'.join(members)} share the '{ff_config_era(era)}' fake factor "
                  f"config era and the same output paths -- submitting '{era}' only.")
    jobs = build_jobs(args)
    return SubmissionPlan(
        stage="fake_factors",
        tag=args.tag,
        entry_point="run.py",
        jobs=jobs,
        ntupletag=args.ntupletag,
        conda_env=FF_CONDA_ENV,
        request_cpus=args.request_cpus or args.nthreads,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
