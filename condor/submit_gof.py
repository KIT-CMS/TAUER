#!/usr/bin/env python3
"""Submit datacards/run_gof.py (b-only GoF with toys, optionally the post-fit) for each era, channel and variable."""
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
    p.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag, e.g. htt_261012.")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS))
    p.add_argument("--channels", type=csv, default=get_channels())
    p.add_argument("--variables", type=csv, required=True, help="Comma-separated GoF variables, 2D ones as <var1>_<var2>.")
    p.add_argument("--fitdir", required=True, help="FITDIR of the GoF datacards, workspaces and results.")
    p.add_argument("--user", default=getpass.getuser())
    p.add_argument("--input-dir", default=None, help="Default: build_shape_output_paths(--ntupletag).output, as condor/submit_estimations.py.")
    p.add_argument("--tag", default=None, help="Same as condor/submit_shapes.py's --tag of the GoF shapes.")
    p.add_argument("--ff-friend", default=None, help="Same as condor/submit_shapes.py's --ff-friend (only its truthiness matters).")
    p.add_argument("--algo", default="saturated", choices=["saturated", "KS", "AD"])
    p.add_argument("--ntoys", type=int, default=500)
    p.add_argument("--postfit", action="store_true", help="Also the b-only post-fit shapes and pulls.")
    p.add_argument("--request-cpus", type=int, default=4, help="Parallel toy seeds per job.")
    p.add_argument("--request-memory-mb", type=int, default=4000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def build_plan(args) -> SubmissionPlan:
    input_root = args.input_dir or build_shape_output_paths(args.ntupletag, user=args.user).output
    if args.tag and args.tag != args.ntupletag:
        input_root = f"{input_root}/{args.tag}"
    qcd_label = "ff" if args.ff_friend else "ss-os"
    jobs = [
        JobSpec(
            name=f"{era}_{channel}_{variable}",
            arguments=f"{era} {channel} {variable} {input_root}/{qcd_label}/{era}/{channel}/shapes.root {args.algo} {args.ntoys} 0 {args.request_cpus}"
            + (" --postfit" if args.postfit else ""),
        )
        for era in args.eras for channel in args.channels for variable in args.variables
    ]
    return SubmissionPlan(
        stage="gof",
        tag=args.tag,
        entry_point="datacards/run_gof.py",
        jobs=jobs,
        ntupletag=args.ntupletag,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        extra_classads={"environment": f'"FITDIR={args.fitdir}"'},
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
