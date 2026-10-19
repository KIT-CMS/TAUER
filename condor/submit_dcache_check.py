#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from sample_database.samplemanager.scripts.check_dcache_files import XROOTD_NOT_FOUND, flatten_files

REPO_ROOT = Path(__file__).resolve().parent.parent
KINGMAKER_ROOT = REPO_ROOT.parent / "KingMaker"


def parse_args():
    p = argparse.ArgumentParser(description="Stat the files of the samples on the GridKA dCache with condor jobs, then --merge the chunks into a report.")
    p.add_argument("--samples-file", required=True, help="One sample nick per line.")
    p.add_argument("--sample-database", default=str(KINGMAKER_ROOT / "sample_database"))
    p.add_argument("--nanoaod-versions", type=csv, default=None, help="Only look for the nick in these nanoAOD versions of the database (default: all).")
    p.add_argument("--files-per-job", type=int, default=1000)
    p.add_argument("--scan-dir", default=None, help="Chunks and report (default: condor/run/dcache_check/<samples file name>).")
    p.add_argument("--missing-only", action="store_true", help="Only submit the chunks without an output file in --scan-dir.")
    p.add_argument("--merge", action="store_true", help="Do not submit, write the report of the chunks in --scan-dir.")
    p.add_argument("--tag", default="dcache_check")
    p.add_argument("--request-memory-mb", type=int, default=1000)
    p.add_argument("--request-disk-kb", type=int, default=500_000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def load_files(args) -> dict:
    """nick -> filelist and nick -> dbs for the nicks of the samples file, read from the sample database."""
    files, dbs = {}, {}
    for nick in Path(args.samples_file).read_text().split():
        versions = args.nanoaod_versions or ["nanoAOD_v*"]
        paths = [p for v in versions for p in glob.glob(f"{args.sample_database}/{v}/*/*/{nick}.json")]
        if len(paths) != 1:
            raise ValueError(f"{nick}: found {len(paths)} filelists in {args.sample_database}, expected 1")
        info = json.load(open(paths[0]))
        files[nick], dbs[nick] = info["filelist"], info["dbs"]
    return files, dbs


def merge(args, files: dict, dbs: dict) -> int:
    """Writes missing_files.txt, missing_dbs.txt and report.json to scan-dir and prints the files per nick missing on the dCache."""
    results = {}
    for chunk in Path(args.scan_dir).glob("chunk_*.json"):
        results.update(json.load(open(chunk))["results"])
    if not results:
        raise SystemExit(f"[dcache_check] no chunk_*.json in {args.scan_dir}, the jobs have not written anything yet (or use the --scan-dir of the submission)")
    report = {}
    for nick in sorted(files):
        errnos = [results.get(f) for f in files[nick]]
        report[nick] = {"nfiles": len(errnos), "missing": errnos.count(XROOTD_NOT_FOUND), "errors": sum(e not in (None, 0, XROOTD_NOT_FOUND) for e in errnos), "unchecked": errnos.count(None)}
        print(f"{report[nick]['missing']:>5}/{report[nick]['nfiles']:<5} missing {report[nick]['errors']:>4} errors {report[nick]['unchecked']:>4} unchecked  {nick}")
    missing = [f for nick in sorted(files) for f in files[nick] if results.get(f) == XROOTD_NOT_FOUND]
    (Path(args.scan_dir) / "missing_files.txt").write_text("\n".join(missing) + "\n")
    missing_dbs = sorted({dbs[nick] for nick in files if report[nick]["missing"]})
    (Path(args.scan_dir) / "missing_dbs.txt").write_text("\n".join(missing_dbs) + "\n")
    print("\n".join(missing_dbs))
    json.dump(report, open(Path(args.scan_dir) / "report.json", "w"), indent=4)
    total = sum(r["nfiles"] for r in report.values())
    print(f"[dcache_check] {len(missing)}/{total} files missing, {sum(r['errors'] for r in report.values())} errors, {sum(r['unchecked'] for r in report.values())} unchecked; report in {args.scan_dir}")
    return 0


def main():
    args = parse_args()
    args.scan_dir = args.scan_dir or str(REPO_ROOT / "condor/run/dcache_check" / Path(args.samples_file).stem)
    files, dbs = load_files(args)
    if args.merge:
        return merge(args, files, dbs)
    scan_dir = Path(args.scan_dir)
    def write_files():
        scan_dir.mkdir(parents=True, exist_ok=True)
        json.dump(files, open(scan_dir / "files.json", "w"))

    nfiles = len(flatten_files(files))
    jobs = [
        JobSpec(name=f"dcache_{start}", arguments=f"--files {scan_dir / 'files.json'} --start {start} --stop {min(start + args.files_per_job, nfiles)} --output-dir {scan_dir}")
        for start in range(0, nfiles, args.files_per_job)
        if not (args.missing_only and (scan_dir / f"chunk_{start}_{min(start + args.files_per_job, nfiles)}.json").exists())
    ]
    print(f"[dcache_check] {len(files)} nicks, {nfiles} files, {len(jobs)} jobs of up to {args.files_per_job} files, chunks in {scan_dir}")
    plan = SubmissionPlan(
        stage="dcache_check",
        tag=args.tag,
        entry_point="sample_database/samplemanager/scripts/check_dcache_files.py",
        jobs=jobs,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
        env_mode="lcg",
        setups=[write_files],
    )
    return submit(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
