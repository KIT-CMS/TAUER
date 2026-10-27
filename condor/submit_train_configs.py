#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from common.sample_paths import build_friend_dir, build_shape_output_paths, crown_ntuple_base
from common.analysis import RUN3_ERAS, get_channels


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag, e.g. htt_260602_2024-25_v5.")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS), help="Comma-separated eras (default: all Run3 eras from common.analysis).")
    p.add_argument("--channels", type=csv, default=get_channels(), help="Comma-separated channels (default: all channels from common.analysis). "
                                                                          "One job per (era, channel) -- produce_shapes.py's --collect-config-only "
                                                                          "only supports a single channel per invocation.")
    p.add_argument("--user", default=getpass.getuser(), help="Grid storage username (default: current user).")
    p.add_argument("--output-dir", default=None,
                    help="Directory for the {era}__{channel}__config.yaml files (default: derived from --ntupletag/--user, "
                         "where run.py TRAIN-DATASET looks for them).")
    p.add_argument("--ff-friend", default=None,
                    help="CROWN fake-factor FRIEND tree version tag, e.g. 'ff_260903'. See README's "
                         "flag reference.")
    p.add_argument("--ff-type", default="none")
    p.add_argument("--additional-friends", type=csv, default=None,
                    help="Comma-separated extra CROWN FRIEND tree version tags/paths. See README's "
                         "flag reference.")
    p.add_argument("--selection-friend", required=True,
                    help="CROWN shapes_preparation FRIEND tree version tag, e.g. "
                         "'shapes_preparation_260930'. See README's flag reference.")
    p.add_argument("--include-systematics", action="store_true",
                    help="By default this passes --skip-systematics. Set this "
                         "flag to collect shifted systematics into the config too.")
    p.add_argument("--tag", default=None, help="Matches run.py's --tag/TAG. See README's flag reference.")
    p.add_argument("--request-cpus", type=int, default=1)
    p.add_argument("--request-memory-mb", type=int, default=4000)
    p.add_argument("--request-disk-kb", type=int, default=4_000_000)
    p.add_argument("--dry-run", action="store_true", help="Validate classads via `condor_submit -dry-run`, do not queue jobs.")
    return p.parse_args(argv)


def build_jobs(args, setups: list) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    base_store = crown_ntuple_base(args.ntupletag, user=args.user)
    ntuples_dir = f"{base_store}/CROWNRun/"

    def resolve_friend(tag: str) -> str:
        return tag if "/" in tag else build_friend_dir(args.ntupletag, tag, user=args.user)

    ff_friend_dir = resolve_friend(args.ff_friend) if args.ff_friend else None
    additional_friend_dirs = [resolve_friend(tag) for tag in (args.additional_friends or [])]

    output_dir = Path(args.output_dir or f"{build_shape_output_paths(args.ntupletag, user=args.user).training}/configs/stage0")  # stage0 booking, the stage-1.2 labels are per event
    setups.append(lambda: output_dir.mkdir(parents=True, exist_ok=True))

    for era in args.eras:
        for channel in args.channels:
            friend_dirs = []
            if ff_friend_dir and channel in ("et", "mt", "tt"):
                friend_dirs.append(ff_friend_dir)
            friend_dirs.extend(additional_friend_dirs)

            job_args = [
                f"--era {era}",
                f"--channels {channel}",
                f"--validation-tag {args.ntupletag}",
                f"--directory {ntuples_dir}",
                *([f"--{channel}-friend-directory", " ".join(friend_dirs)] if friend_dirs else []),
                "--xrootd",
                "--collect-config-only",
                "--no-dnn-categorization",  # no NN friend before training: the NN categories cut on nn_predicted_class
                # collect_config() itself prefixes the basename with "{era}__{channel}__",
                # landing the real output at output_dir/{era}__{channel}__config.yaml.
                f"--config-output-file {output_dir / 'config.yaml'}",
                # --output-file is required by argparse but never touched -- collect_config
                # returns before any histogram is written.
                f"--output-file {output_dir / f'{era}_{channel}_unused.root'}",
            ]
            if args.selection_friend:
                job_args.append(f"--selection-friend {args.selection_friend}")
            if not args.include_systematics:
                job_args.append("--skip-systematics")
            if ff_friend_dir:
                job_args.append("--ff-type fake_factor" if args.ff_type == "none" else f"--ff-type {args.ff_type}")
            elif args.ff_type != "none":
                job_args.append(f"--ff-type {args.ff_type}")

            jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
    return jobs


def build_plan(args) -> SubmissionPlan:
    setups: list = []
    return SubmissionPlan(
        stage="train-configs",
        tag=args.tag,
        entry_point="shapes/produce_shapes.py",
        jobs=build_jobs(args, setups),
        ntupletag=args.ntupletag,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
        setups=setups,
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
