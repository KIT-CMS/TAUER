#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from common.sample_paths import build_friend_dir, build_shape_output_paths, crown_ntuple_base
from common.shapes_merge import write_expected_processes
from common.analysis import RUN3_ERAS, get_channels


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag, e.g. htt_260602_2024-25_v5.")
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS), help="Comma-separated eras (default: all Run3 eras from common.analysis).")
    p.add_argument("--channels", type=csv, default=get_channels(), help="Comma-separated channels (default: all channels from common.analysis).")
    p.add_argument("--user", default=getpass.getuser(), help="Grid storage username (default: current user).")
    p.add_argument("--output-dir", default=None, help="Default: build_shape_output_paths(--ntupletag).output.")
    p.add_argument("--validation-db-root", default=None,
                    help="Default: build_shape_output_paths(--ntupletag).validation. "
                         "See shapes/produce_shapes.py --validation-db-root.")
    p.add_argument("--ff-friend", default=None,
                    help="CROWN fake-factor FRIEND tree version tag, e.g. 'ff_260903'. See README's "
                         "flag reference.")
    p.add_argument("--ff-type", default="none")
    p.add_argument("--additional-friends", type=csv, default=None,
                    help="Comma-separated extra CROWN FRIEND tree version tags/paths. See README's "
                         "flag reference.")
    p.add_argument("--selection-friend", default=None,
                    help="CROWN selection-mask FRIEND tree version tag, e.g. 'selection_260817'. See "
                         "README's flag reference.")
    p.add_argument("--process-selection", type=lambda v: [csv_group.replace(" ", "").split("+") for csv_group in csv(v)],
                    default=None,
                    help="Comma-separated process GROUPS ('+'-joined within a group) -- splits each "
                         "(era, channel) into one job per group. See README's \"submit_shapes.py "
                         "--process-selection\" section for the full mechanism.")
    p.add_argument("--stxs-stage", default="stage0", choices=["stage0", "stage1p2"], help="Signal split, same as run.py/produce_shapes.py --stxs-stage.")
    p.add_argument("--skip-systematics", action="store_true")
    p.add_argument("--control-plots", action="store_true")
    p.add_argument("--control-plot-set", type=csv, default=None, help="Comma-separated variables of --control-plots (default: produce_shapes.py's, m_vis).")
    p.add_argument("--special-analysis", default=None,
                    choices=[None, "TauES", "TTbarDYWeight", "NjetsControl", "TriggerRegions", "AntiIsoTauSF"],
                    help="Passed through to produce_shapes.py's own --special-analysis. "
                         "'TTbarDYWeight' is em channel only; 'NjetsControl' supports all channels; 'TriggerRegions'/'AntiIsoTauSF' et/mt/tt, Run 3.")
    p.add_argument("--dnn-categorization", action="store_true",
                    help="Use DNN-based categorization (needs a DNN friend tree). See README's "
                         "\"submit_shapes.py --process-selection\" section for why this defaults off.")
    p.add_argument("--no-xrootd", action="store_true", help="Read ntuples from a local path instead of xrootd (--directory becomes the given --local-directory).")
    p.add_argument("--local-directory", default=None)
    p.add_argument("--tag", default=None,
                    help="Matches run.py's --tag/TAG. See README's flag reference.")
    p.add_argument("--no-era-merge", type=csv, default=None,
                    help="Comma-separated analysis eras to run WITHOUT their usual "
                         "DATA_ERA_MERGE extra eras (e.g. '2025' to plot 2025 without "
                         "2026's data folded in). Sets TAUER_NO_DATA_ERA_MERGE in "
                         "the job environment; see common.analysis.get_data_eras().")
    p.add_argument("--request-cpus", type=int, default=4,
                    help="Also passed through as produce_shapes.py's --nprocs (real worker "
                         "processes, not --nthreads). See README's flag reference.")
    p.add_argument("--request-memory-mb", type=int, default=4000)
    p.add_argument("--request-disk-kb", type=int, default=8_000_000)
    p.add_argument("--dry-run", action="store_true", help="Validate classads via `condor_submit -dry-run`, do not queue jobs.")
    return p.parse_args(argv)


def build_jobs(args, setups: list) -> list[JobSpec]:
    """setups collects the directory/manifest writes the jobs need; only a real submit runs them."""
    jobs: list[JobSpec] = []
    base_store = crown_ntuple_base(args.ntupletag, user=args.user)
    ntuples_dir = args.local_directory if args.no_xrootd else f"{base_store}/CROWNRun/"
    shape_paths = build_shape_output_paths(args.ntupletag, user=args.user)
    output_dir = args.output_dir or shape_paths.output
    validation_db_root = args.validation_db_root or shape_paths.validation
    run_tag = args.tag or args.ntupletag

    def resolve_friend(tag: str) -> str:
        # Bare tag -> build_friend_dir() against this ntupletag/user; a value containing
        # '/' is used as a full path as-is.
        return tag if "/" in tag else build_friend_dir(args.ntupletag, tag, user=args.user)

    ff_friend_dir = resolve_friend(args.ff_friend) if args.ff_friend else None
    additional_friend_dirs = [resolve_friend(tag) for tag in (args.additional_friends or [])]
    # Mirrors run.py's mode_shapes: "ff" iff a fake-factor friend is attached.
    qcd_label = "ff" if ff_friend_dir else "ss-os"

    for era in args.eras:
        for channel in args.channels:
            common = [
                f"--era {era}",
                f"--channels {channel}",
                # Scopes ntuple_processor's validation_database/ cache by ntupletag --
                # without this, a stale/racy cache entry from one tag can collide with another.
                f"--validation-tag {args.ntupletag}",
                f"--validation-db-root {validation_db_root}",
                # Each --{ch}-friend-directory is nargs="+" without action="append" on
                # produce_shapes.py's side -- every friend a channel needs must be listed
                # together in ONE occurrence per channel (see friend_dirs below), like run.py's
                # own friend_directory_args().
                f"--nprocs {args.request_cpus}",
                "--nthreads 1",
            ]
            friend_dirs = {ch: [] for ch in ("et", "mt", "tt", "em")}
            if ff_friend_dir:
                for ch in ("et", "mt", "tt"):
                    friend_dirs[ch].append(ff_friend_dir)
            for friend_dir in additional_friend_dirs:
                for ch in friend_dirs:
                    friend_dirs[ch].append(friend_dir)
            common += [
                arg
                for ch, dirs in friend_dirs.items()
                if dirs
                for arg in (f"--{ch}-friend-directory", " ".join(dirs))
            ]
            common.append(f"--directory {ntuples_dir}")
            if not args.no_xrootd:
                common.append("--xrootd")
            if args.selection_friend:
                common.append(f"--selection-friend {args.selection_friend}")
            common.append(f"--stxs-stage {args.stxs_stage}")
            if args.skip_systematics:
                common.append("--skip-systematics")
            if args.control_plots:
                common.append("--control-plots")
                if args.control_plot_set:
                    common.append(f"--control-plot-set {' '.join(args.control_plot_set)}")
            if not args.dnn_categorization and not args.special_analysis:
                common.append("--no-dnn-categorization")
            if args.special_analysis:
                common.append(f"--special-analysis {args.special_analysis}")
            if ff_friend_dir:
                common.append("--ff-type fake_factor" if args.ff_type == "none" else f"--ff-type {args.ff_type}")
            elif args.ff_type != "none":
                common.append(f"--ff-type {args.ff_type}")

            # Nested output/[<tag>/]<qcd-label>/<era>/<channel>/shapes.root -- matches
            # common.sample_paths.output_run_dir(). Created by a real submit since TFile(..., "RECREATE")
            # doesn't create missing parent directories itself.
            run_dir_parts = [output_dir]
            if run_tag != args.ntupletag:
                run_dir_parts.append(run_tag)
            run_dir_parts += [qcd_label, era, channel]
            run_dir = Path(*run_dir_parts)
            setups.append(lambda run_dir=run_dir: run_dir.mkdir(parents=True, exist_ok=True))

            # Same ss-os reuse as run.py's mode_shapes: if a plain ss-os run for this exact
            # (ntupletag, tag, era, channel) already exists, book only the FF-weighted
            # systematics (--ff-only) instead of redoing the full production. Falls through
            # to a full booking otherwise; shapes/do_estimations.py's merge_ff_reuse_if_needed()
            # hadd's the parts together later.
            ss_os_shapes = None
            if qcd_label == "ff":
                ss_os_dir_parts = list(run_dir_parts)
                ss_os_dir_parts[-3] = "ss-os"
                ss_os_shapes = Path(*ss_os_dir_parts) / "shapes.root"
                if ss_os_shapes.exists():
                    print(f"[condor] {era}/{channel}: reusing existing ss-os shapes at {ss_os_shapes} "
                          f"-- booking only --ff-only systematics instead of a full re-run.")
                else:
                    print(f"[condor] {era}/{channel}: no existing ss-os shapes at {ss_os_shapes} "
                          f"-- booking the full ff shapes (incl. FF systematics) from scratch.")
            ff_reuse = bool(ss_os_shapes and ss_os_shapes.exists())

            if args.process_selection:
                # One job per group, each into its own shapes__<group>.root -- see README's
                # "submit_shapes.py --process-selection" section for the full mechanism.
                for group in args.process_selection:
                    group_label = "_".join(group)
                    job_args = list(common)
                    job_args.append(f"--process-selection {','.join(group)}")
                    if ff_reuse:
                        job_args.append("--ff-only")
                        output_file = run_dir / f"shapes_ff_only__{group_label}.root"
                    else:
                        output_file = run_dir / f"shapes__{group_label}.root"
                    job_args.append(f"--output-file {output_file}")
                    jobs.append(JobSpec(name=f"{era}_{channel}_{group_label}", arguments=" ".join(job_args)))
                setups.append(lambda run_dir=run_dir: write_expected_processes(run_dir, [process for group in args.process_selection for process in group]))
            else:
                output_file = run_dir / "shapes.root"
                job_args = list(common)
                if ff_reuse:
                    job_args.append("--ff-only")
                    output_file = run_dir / "shapes_ff_only.root"
                job_args.append(f"--output-file {output_file}")
                jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
    return jobs


def build_plan(args) -> SubmissionPlan:
    setups: list = []
    jobs = build_jobs(args, setups)
    extra_classads = {}
    if args.no_era_merge:
        extra_classads["environment"] = '"TAUER_NO_DATA_ERA_MERGE={}"'.format(
            ",".join(args.no_era_merge)
        )
    return SubmissionPlan(
        stage="shapes",
        tag=args.tag,
        entry_point="shapes/produce_shapes.py",
        jobs=jobs,
        ntupletag=args.ntupletag,
        request_cpus=args.request_cpus,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
        extra_classads=extra_classads,
        setups=setups,
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
