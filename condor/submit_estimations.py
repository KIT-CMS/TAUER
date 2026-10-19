#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from common.sample_paths import build_shape_output_paths
from common.analysis import RUN3_ERAS, get_channels


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag, e.g. htt_260602_2024-25_v5.")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS), help="Comma-separated eras (default: all Run3 eras from common.analysis).")
    p.add_argument("--channels", type=csv, default=get_channels(), help="Comma-separated channels (default: all channels from common.analysis).")
    p.add_argument("--user", default=getpass.getuser(), help="Grid storage username for --ntupletag-derived path defaults (default: current user).")
    p.add_argument("--input-dir", default=None, help="Default: build_shape_output_paths(--ntupletag).output (same default condor/submit_shapes.py uses for --output-dir).")
    p.add_argument("--ff-friend", default=None,
                    help="Same flag/value as condor/submit_shapes.py's --ff-friend for this "
                         "ntupletag -- only its truthiness matters (picks --do-ff vs --do-qcd).")
    p.add_argument("--do-emb-tt", action="store_true", help="Add embedded ttbar contamination systematic (see shapes/do_estimations.py --do-emb-tt).")
    p.add_argument("--special-analysis", dest="special", default=None, help="See shapes/do_estimations.py --special-analysis (e.g. TauES).")
    p.add_argument("--tag", default=None,
                    help="Must match condor/submit_shapes.py's --tag for this ntupletag -- drives the "
                         "input path here too. See README's flag reference.")
    p.add_argument("--request-cpus", type=int, default=1, help="Single-threaded histogram post-processing -- no --nprocs/--nthreads here.")
    p.add_argument("--request-memory-mb", type=int, default=2000)
    p.add_argument("--request-disk-kb", type=int, default=1_000_000)
    p.add_argument("--dry-run", action="store_true", help="Validate classads via `condor_submit -dry-run`, do not queue jobs.")
    return p.parse_args(argv)


def build_jobs(args) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    input_root = args.input_dir or build_shape_output_paths(args.ntupletag, user=args.user).output
    run_tag = args.tag or args.ntupletag
    if run_tag != args.ntupletag:
        input_root = f"{input_root}/{run_tag}"
    qcd_label = "ff" if args.ff_friend else "ss-os"
    estimation_flag = "--do-ff" if args.ff_friend else "--do-qcd"

    for era in args.eras:
        for channel in args.channels:
            input_file = f"{input_root}/{qcd_label}/{era}/{channel}/shapes.root"
            job_args = [
                f"--era {era}",
                f"--input-file {input_file}",
                estimation_flag,
            ]
            if args.do_emb_tt:
                job_args.append("--do-emb-tt")
            if args.special:
                job_args.append(f"--special-analysis {args.special}")
            jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
    return jobs


def build_plan(args) -> SubmissionPlan:
    jobs = build_jobs(args)
    return SubmissionPlan(
        stage=f"estimation-{'ff' if args.ff_friend else 'ss-os'}",
        tag=args.tag,
        entry_point="shapes/do_estimations.py",
        jobs=jobs,
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
