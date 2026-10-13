#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyses.smhtt.common.stxs_tools import _scan_key, dbs_files, signal_nicks
from condor.common import JobSpec, SubmissionPlan, csv, submit

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--eras", type=csv, default=None, help="Eras of signals.yaml whose nicks are scanned (default: all).")
    p.add_argument("--max-files", type=int, default=None, help="Scan only the first N files of each filtered nick.")
    p.add_argument("--max-files-unfiltered", type=int, default=None, help="Scan only the first N files of each unfiltered nick.")
    p.add_argument("--files-per-job", type=int, default=25)
    p.add_argument("--scan-dir", default=str(REPO_ROOT / "condor/run/stxs_table/scans"))
    p.add_argument("--missing-only", action="store_true", help="Only submit the chunks without an output file in --scan-dir.")
    p.add_argument("--tag", default="stxs_table")
    p.add_argument("--request-cpus", type=int, default=1)
    p.add_argument("--request-memory-mb", type=int, default=4000)
    p.add_argument("--request-disk-kb", type=int, default=2_000_000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def build_jobs(args) -> list:
    jobs = []
    for dbs, (_, files) in dbs_files(signal_nicks(eras=args.eras)[0], args.max_files, args.max_files_unfiltered).items():
        for start in range(0, len(files), args.files_per_job):
            stop = start + args.files_per_job
            if args.missing_only and (Path(args.scan_dir) / f"{_scan_key(dbs)}__{start}_{stop}.json").exists():
                continue
            jobs.append(JobSpec(name=f"scan_{_scan_key(dbs)}_{start}", arguments=f"--scan-chunk {dbs} {start} {stop} --scan-dir {args.scan_dir}"))
    return jobs


def main():
    args = parse_args()
    jobs = build_jobs(args)
    print(f"[stxs_table] {len(jobs)} jobs of up to {args.files_per_job} files, scans in {args.scan_dir}")
    plan = SubmissionPlan(
        stage="stxs_table",
        tag=args.tag,
        entry_point="analyses/smhtt/common/stxs_tools.py",
        jobs=jobs,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
        env_mode="lcg",
    )
    return submit(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
