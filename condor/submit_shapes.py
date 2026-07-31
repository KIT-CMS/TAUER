#!/usr/bin/env python3
"""
HTCondor submission for shapes/produce_shapes.py.

Fans out ONE htcondor job per (era, channel[, process-group]) from a single
CLI invocation, e.g.:

    python3 condor/submit_shapes.py \\
        --ntupletag htt_260602_2024-25_v5 \\
        --eras 2024,2025 --channels et,mt,tt \\
        --vs-jet-wp Medium --dry-run

submits (or dry-run validates) one job per era x channel combination (6 jobs
in the example above). Pass --split-by-process to additionally fan out each
(era, channel) into one job per process group (data/ztt/zl/.../vh), for much
finer-grained, more restartable jobs at the cost of more of them.

Era/channel lists default to config.analysis.RUN3_ERAS / get_channels() — the
Phase 1 central config — never hardcoded here.

NOTE (see STATUS.md Phase 1 note + shapes/produce_shapes.py --directory help):
--directory must be the bare xrootd store path (e.g.
/store/user/<user>/CROWN/ntuples/<tag>/CROWNRun/), NOT a full root://host/...
URL, when --xrootd is set. This script builds that path itself (mirroring
common/sample_paths.py's convention -- formerly utils/setup_ul_samples.sh,
converted to Python in Phase 6d, see STATUS.md "## Phase 6d") so callers
don't have to get this right by hand.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, make_tag, submit
from common.sample_paths import build_shape_output_paths
from config.analysis import RUN3_ERAS, get_channels, vs_ele_wp_for

# Default process groups produced by shapes/produce_shapes.py (see its
# `procS` default in main()). Used only when --split-by-process is set and
# --process-selection was not given.
DEFAULT_PROCESSES = [
    "data", "ztt", "zl", "zj", "ttt", "ttl", "ttj",
    "vvt", "vvl", "vvj", "w", "ggh", "qqh", "tth", "vh",
]


def csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag, e.g. htt_260602_2024-25_v5.")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS), help="Comma-separated eras (default: all Run3 eras from config.analysis).")
    p.add_argument("--channels", type=csv, default=get_channels(), help="Comma-separated channels (default: all channels from config.analysis).")
    p.add_argument("--vs-jet-wp", default="Medium")
    p.add_argument("--vs-ele-wp", default=None, help="Default: Tight for et, VVLoose otherwise (config.analysis.vs_ele_wp_for(), matches run.py).")
    p.add_argument("--user", default=getpass.getuser(), help="Grid storage username (default: current user).")
    p.add_argument("--output-dir", default=None, help="Default: build_shape_output_paths(--ntupletag).output.")
    p.add_argument("--validation-db-root", default=None,
                    help="Default: build_shape_output_paths(--ntupletag).validation. "
                         "See shapes/produce_shapes.py --validation-db-root.")
    p.add_argument("--ff-friends-dir", default=None)
    p.add_argument("--ff-type", default="none")
    p.add_argument("--presel-dir", default=None)
    p.add_argument("--process-selection", type=csv, default=None, help="Restrict to this comma-separated process list (default: all).")
    p.add_argument("--split-by-process", action="store_true", help="One job per process (within --process-selection or the default set) instead of one job per (era, channel).")
    p.add_argument("--skip-systematic-variations", action="store_true")
    p.add_argument("--control-plots", action="store_true")
    p.add_argument("--num-processes", type=int, default=1)
    p.add_argument("--num-threads", type=int, default=4)
    p.add_argument("--no-xrootd", action="store_true", help="Read ntuples from a local path instead of xrootd (--directory becomes the given --local-directory).")
    p.add_argument("--local-directory", default=None)
    p.add_argument("--tag", default=None, help="Batch tag (default: shapes-<timestamp>).")
    p.add_argument("--request-cpus", type=int, default=None, help="Default: --num-threads.")
    p.add_argument("--request-memory-mb", type=int, default=4000)
    p.add_argument("--request-disk-kb", type=int, default=8_000_000)
    p.add_argument("--dry-run", action="store_true", help="Validate classads via `condor_submit -dry-run`, do not queue jobs.")
    return p.parse_args()


def build_jobs(args) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    base_store = f"/store/user/{args.user}/CROWN/ntuples/{args.ntupletag}"
    ntuples_dir = args.local_directory if args.no_xrootd else f"{base_store}/CROWNRun/"
    xsec_friends = f"{base_store}/CROWNFriends/xsec/"
    shape_paths = build_shape_output_paths(args.ntupletag, user=args.user)
    output_dir = args.output_dir or shape_paths.output
    validation_db_root = args.validation_db_root or shape_paths.validation

    process_groups = args.process_selection or DEFAULT_PROCESSES
    for era in args.eras:
        for channel in args.channels:
            vs_ele_wp = vs_ele_wp_for(channel, args.vs_ele_wp)
            common = [
                f"--era {era}",
                f"--channels {channel}",
                f"--vs-jet-wp {args.vs_jet_wp}",
                f"--vs-ele-wp {vs_ele_wp}",
                # Scopes ntuple_processor's on-disk validation_database/ cache
                # by ntupletag -- without this, produce_shapes.py's
                # --validation-tag default ("default") is shared across every
                # ntupletag ever submitted through this script, and a stale/
                # racy cache entry from one tag can be silently reused (or
                # collide) with another. run.py's mode_shapes has passed this
                # since Phase 6d; this script never did (bug, fixed here).
                f"--validation-tag {args.ntupletag}",
                f"--validation-db-root {validation_db_root}",
                f"--et-friend-directory {xsec_friends}",
                f"--mt-friend-directory {xsec_friends}",
                f"--tt-friend-directory {xsec_friends}",
                f"--em-friend-directory {xsec_friends}",
                f"--num-processes {args.num_processes}",
                f"--num-threads {args.num_threads}",
            ]
            # --directory and --presel-dir are mutually exclusive in
            # shapes/produce_shapes.py.
            if args.presel_dir:
                common.append(f"--presel-dir {args.presel_dir}")
            else:
                common.append(f"--directory {ntuples_dir}")
            if not args.no_xrootd and not args.presel_dir:
                common.append("--xrootd")
            if args.skip_systematic_variations:
                common.append("--skip-systematic-variations")
            if args.control_plots:
                common.append("--control-plots")
            if args.ff_friends_dir:
                common += [
                    f"--et-friend-directory {args.ff_friends_dir}",
                    f"--mt-friend-directory {args.ff_friends_dir}",
                    f"--tt-friend-directory {args.ff_friends_dir}",
                    "--ff-type fake_factor" if args.ff_type == "none" else f"--ff-type {args.ff_type}",
                ]
            elif args.ff_type != "none":
                common.append(f"--ff-type {args.ff_type}")

            if args.split_by_process:
                for process in process_groups:
                    output_file = f"{output_dir}/{era}-{channel}-{process}-shapes.root"
                    job_args = common + [
                        f"--process-selection {process}",
                        f"--output-file {output_file}",
                    ]
                    jobs.append(JobSpec(name=f"{era}_{channel}_{process}", arguments=" ".join(job_args)))
            else:
                output_file = f"{output_dir}/{era}-{channel}-shapes.root"
                job_args = list(common)
                if args.process_selection:
                    job_args.append(f"--process-selection {','.join(process_groups)}")
                job_args.append(f"--output-file {output_file}")
                jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
    return jobs


def main():
    args = parse_args()
    jobs = build_jobs(args)
    plan = SubmissionPlan(
        stage="shapes",
        tag=args.tag or make_tag("shapes"),
        entry_point="shapes/produce_shapes.py",
        jobs=jobs,
        request_cpus=args.request_cpus or args.num_threads,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )
    return submit(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
