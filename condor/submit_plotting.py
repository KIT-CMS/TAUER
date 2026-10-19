#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import REPO_ROOT, JobSpec, SubmissionPlan, csv, submit
from common.sample_paths import build_shape_output_paths
from common.analysis import RUN3_ERAS, get_channels



def chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ntupletag", default=None,
                    help="CROWN ntuple production tag -- derives --input-dir when not given "
                         "explicitly. Also the default --tag.")
    p.add_argument("--user", default=getpass.getuser(), help="Username for --ntupletag-derived path defaults (default: current user).")
    p.add_argument("--input-dir", default=None,
                    help="Root shapes directory, before the <ss-os|ff>/<era>/<channel>/ nesting. "
                         "Default: build_shape_output_paths(--ntupletag).output[/--tag].")
    p.add_argument("--input-pattern", default="{qcd_label}/{era}/{channel}/shapes.root", help="Path pattern within --input-dir, formatted with era/channel/qcd_label.")
    p.add_argument("--output-dir", default=None,
                    help="Base plot output directory. Default: <repo>/plotting/plots/ -- NOT /web, "
                         "which condor execute nodes can't write to.")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS))
    p.add_argument("--channels", type=csv, default=get_channels())
    p.add_argument("--variables", type=csv, default=None, help="Comma-separated variable list (default: all in common/variables.yaml, handled by plot_shapes_control.py itself).")
    p.add_argument("--split-variables", type=int, default=None, metavar="N", help="If set, split --variables into chunks of N and submit one extra job per chunk instead of one job per (era, channel).")
    p.add_argument("--log-y", action="store_true")
    p.add_argument("--blinded", action="store_true")
    p.add_argument("--embedding", action="store_true")
    p.add_argument("--fake-factor", action="store_true", help="Selects the 'ff' half of the ss-os/ff input+output split; also passed through to plot_shapes_control.py.")
    p.add_argument("--tag", default=None, help="Shapes run tag to read (default: --ntupletag, as run.py/submit_shapes.py --tag) and condor run label.")
    p.add_argument("--request-cpus", type=int, default=1)
    p.add_argument("--request-memory-mb", type=int, default=2000)
    p.add_argument("--request-disk-kb", type=int, default=2_000_000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def build_jobs(args) -> list:
    jobs = []
    run_tag = args.tag or args.ntupletag
    qcd_label = "ff" if args.fake_factor else "ss-os"

    if args.input_dir:
        input_root = args.input_dir
    elif args.ntupletag:
        input_root = build_shape_output_paths(args.ntupletag, user=args.user).output
    else:
        raise SystemExit("condor/submit_plotting.py: either --input-dir or --ntupletag is required.")
    if run_tag and run_tag != args.ntupletag:
        input_root = f"{input_root}/{run_tag}"

    output_root = args.output_dir or str(REPO_ROOT / "plotting" / "plots")
    for era in args.eras:
        # plot_shapes_control.py appends <channel>/ under this itself; don't nest it here too.
        plot_dir = f"{output_root}/{qcd_label}/{era}/{args.ntupletag or 'notag'}/"
        if run_tag != args.ntupletag:
            plot_dir += f"{run_tag}/"
        for channel in args.channels:
            input_file = str(Path(input_root) / args.input_pattern.format(era=era, channel=channel, qcd_label=qcd_label))
            common = [
                f"--input-file {input_file}",
                f"--output-dir {plot_dir}",
                f"--era {era}",
                f"--channels {channel}",
            ]
            if args.log_y:
                common.append("--log-y")
            if args.blinded:
                common.append("--blinded")
            if args.embedding:
                common.append("--embedding")
            if args.fake_factor:
                common.append("--fake-factor")

            if args.split_variables and args.variables:
                for i, var_chunk in enumerate(chunk(args.variables, args.split_variables)):
                    job_args = common + [f"--variables {','.join(var_chunk)}"]
                    jobs.append(JobSpec(name=f"{era}_{channel}_vars{i}", arguments=" ".join(job_args)))
            else:
                job_args = list(common)
                if args.variables:
                    job_args.append(f"--variables {','.join(args.variables)}")
                jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
    return jobs


def build_plan(args) -> SubmissionPlan:
    jobs = build_jobs(args)
    return SubmissionPlan(
        stage="plotting",
        tag=args.tag,
        entry_point="plotting/plot_shapes_control.py",
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
