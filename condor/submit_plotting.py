#!/usr/bin/env python3
"""
HTCondor submission for plotting/plot_shapes_control.py.

Fans out ONE htcondor job per (era, channel) from a single CLI invocation
(sensible granularity: plot_shapes_control.py already loops internally over
all variables/categories for a given input shapes file + channel, and reads
one input ROOT file per era; splitting further, per-variable, would mean
re-opening/re-reading that ROOT file once per variable per job for no real
parallelism benefit). Pass --split-variables to instead fan out per
(era, channel, variable-chunk) if input-file I/O is not the bottleneck for
your case.

Example:

    python3 condor/submit_plotting.py \\
        --input-dir output --eras 2024,2025 --channels et,mt,tt \\
        --output-dir /web/sgiappic/public_html/CMS_HTT --dry-run

expects one input file per (era, channel) at
<input-dir>/<era>-<channel>-shapes.root, matching submit_shapes.py's default
--output-file naming (shapes/produce_shapes.py's own single-file-per-invocation
convention, not something plotting introduces).

Era/channel lists default to config.analysis.RUN3_ERAS / get_channels().
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


def chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input-dir", required=True, help="Directory with <era>-<channel>-shapes.root files (see submit_shapes.py).")
    p.add_argument("--input-pattern", default="{era}-{channel}-shapes.root", help="Filename pattern within --input-dir, formatted with era/channel.")
    p.add_argument("--output-dir", required=True, help="Base output directory for plots; a per-(era,channel) subdirectory is appended.")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS))
    p.add_argument("--channels", type=csv, default=get_channels())
    p.add_argument("--variables", type=csv, default=None, help="Comma-separated variable list (default: all in config/variables.yaml, handled by plot_shapes_control.py itself).")
    p.add_argument("--split-variables", type=int, default=None, metavar="N", help="If set, split --variables into chunks of N and submit one extra job per chunk instead of one job per (era, channel).")
    p.add_argument("--log-y", action="store_true")
    p.add_argument("--blinded", action="store_true")
    p.add_argument("--embedding", action="store_true")
    p.add_argument("--fake-factor", action="store_true")
    p.add_argument("--tag", default=None)
    p.add_argument("--request-cpus", type=int, default=1)
    p.add_argument("--request-memory-mb", type=int, default=2000)
    p.add_argument("--request-disk-kb", type=int, default=2_000_000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def build_jobs(args) -> list:
    jobs = []
    for era in args.eras:
        for channel in args.channels:
            input_file = str(Path(args.input_dir) / args.input_pattern.format(era=era, channel=channel))
            output_dir = str(Path(args.output_dir) / era / channel)
            common = [
                f"--input {input_file}",
                f"--output {output_dir}",
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


def main():
    args = parse_args()
    jobs = build_jobs(args)
    plan = SubmissionPlan(
        stage="plotting",
        tag=args.tag or make_tag("plotting"),
        entry_point="plotting/plot_shapes_control.py",
        jobs=jobs,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )
    return submit(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
