#!/usr/bin/env python3
"""
HTCondor submission for the fake-factor measurement
(run_fake_factor_measurement.py -- the GEN-TFF-CONFIGS -> preselection.py ->
ff_calculation.py -> ff_corrections.py chain, see that script's own
docstring / run.py's FF-MEASURE mode).

Fans out ONE htcondor job per era by default (run_fake_factor_measurement.py
already loops over --channels internally within a single process, same
granularity choice as condor/submit_btag_efficiency.py's `calculate` step).
Pass --split-by-channel for one job per (era, channel) instead, for more
restartable jobs -- useful when only one channel's FF needs a rerun.

Example:

    python3 condor/submit_ff.py --eras 2022preEE,2022postEE --dry-run

    python3 condor/submit_ff.py --eras 2024 --channels mt \\
        --split-by-channel --dry-run

Era list defaults to config.analysis.RUN3_ERAS. Channels default to et,mt,tt
-- NOT config.analysis.get_channels() (which also lists em):
TauFakeFactors/configs/smhtt_ul/*/ ships no fake_factors_em.yaml /
corrections_em.yaml / preselection_em.yaml (em never uses fake factors, same
exclusion as run.py's FF/FF-CORR/FF-MEASURE modes and every job_*.sh script
in Bash/), so passing em here would just fail per-job on a missing config
file.

Unlike every other condor/submit_*.py in this repo, this stage needs the
`fake_factors` conda env, not `taukitflow` -- see README.md "`fake_factors`
conda env -- TauFakeFactors' own scripts" (ruamel.yaml/XRootD-client live
there, not in `taukitflow`). Passed explicitly as SubmissionPlan.conda_env
below; condor/common.py's wrapper activates whatever env is given the same
way for either.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, make_tag, submit
from config.analysis import RUN3_ERAS

# et/mt/tt only -- see module docstring. Deliberately NOT get_channels().
DEFAULT_FF_CHANNELS = ["et", "mt", "tt"]
DEFAULT_STEPS = ["gen-configs", "presel", "ff", "ff-corr"]
FF_CONDA_ENV = "fake_factors"


def csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--eras", type=csv, default=list(RUN3_ERAS), help="Comma-separated eras (default: all Run3 eras from config.analysis).")
    p.add_argument("--channels", type=csv, default=list(DEFAULT_FF_CHANNELS), help="Comma-separated channels (default: et,mt,tt -- em has no FF configs, see module docstring).")
    p.add_argument("--steps", type=csv, default=list(DEFAULT_STEPS),
                    help="Subset/order of run_fake_factor_measurement.py's steps to run "
                         "(default: all four, in order): gen-configs,presel,ff,ff-corr.")
    p.add_argument("--split-by-channel", action="store_true", help="One job per (era, channel) instead of one job per era.")
    p.add_argument("--nthreads", type=int, default=8)
    p.add_argument("--ff-config", default=None, help="Override --config-file for the FF step (passed through as-is; only meaningful for a single channel).")
    p.add_argument("--ff-corr-config", default=None, help="Override --config-file for the FF-CORR step (same caveat as --ff-config).")
    p.add_argument("--tag", default=None, help="Batch tag (default: ff-<timestamp>).")
    p.add_argument("--request-cpus", type=int, default=None, help="Default: --nthreads.")
    p.add_argument("--request-memory-mb", type=int, default=4000)
    p.add_argument("--request-disk-kb", type=int, default=4_000_000)
    p.add_argument("--dry-run", action="store_true", help="Validate classads via `condor_submit -dry-run`, do not queue jobs.")
    return p.parse_args()


def build_jobs(args) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    steps_csv = ",".join(args.steps)
    for era in args.eras:
        if args.split_by_channel:
            for channel in args.channels:
                job_args = [
                    f"--era {era}",
                    f"--channels {channel}",
                    f"--steps {steps_csv}",
                    f"--nthreads {args.nthreads}",
                ]
                if args.ff_config:
                    job_args.append(f"--ff-config {args.ff_config}")
                if args.ff_corr_config:
                    job_args.append(f"--ff-corr-config {args.ff_corr_config}")
                jobs.append(JobSpec(name=f"{era}_{channel}", arguments=" ".join(job_args)))
        else:
            job_args = [
                f"--era {era}",
                f"--channels {','.join(args.channels)}",
                f"--steps {steps_csv}",
                f"--nthreads {args.nthreads}",
            ]
            if args.ff_config:
                job_args.append(f"--ff-config {args.ff_config}")
            if args.ff_corr_config:
                job_args.append(f"--ff-corr-config {args.ff_corr_config}")
            jobs.append(JobSpec(name=era, arguments=" ".join(job_args)))
    return jobs


def main():
    args = parse_args()
    jobs = build_jobs(args)
    plan = SubmissionPlan(
        stage="ff",
        tag=args.tag or make_tag("ff"),
        entry_point="run_fake_factor_measurement.py",
        jobs=jobs,
        conda_env=FF_CONDA_ENV,
        request_cpus=args.request_cpus or args.nthreads,
        request_memory_mb=args.request_memory_mb,
        request_disk_kb=args.request_disk_kb,
    )
    return submit(plan, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
