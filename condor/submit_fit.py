#!/usr/bin/env python3
"""Submit datacards/run_fit.py, one job per POI of the stage's scheme (analyses/<analysis>/datacards/combine_model.poi_scheme)."""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condor.common import JobSpec, SubmissionPlan, csv, submit
from common.analysis import ACTIVE_ANALYSIS


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ntupletag", required=True, help="CROWN ntuple production tag, e.g. htt_261012 (condor run directory).")
    p.add_argument("--analysis", required=True, help="run_fit.py's analysis: the cards of $FITDIR/output_<analysis>.")
    p.add_argument("--fitdir", required=True, help="FITDIR of the datacards and workspaces.")
    p.add_argument("--stxs-stage", choices=["stage0", "stage1p2"], default="stage0")
    p.add_argument("--formalism", choices=["xsec", "mu"], default="xsec")
    p.add_argument("--pois", type=csv, default=None, help="Default: all POIs of the stage's scheme.")
    p.add_argument("--workspace", default="cmb/ws.root")
    p.add_argument("--observed", action="store_true")
    p.add_argument("--tag", default=None)
    p.add_argument("--request-memory-mb", type=int, default=6000)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def build_plan(args) -> SubmissionPlan:
    pois = args.pois or list(importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.datacards.combine_model").poi_scheme(args.stxs_stage))
    options = f"{args.analysis} --stxs-stage {args.stxs_stage} --formalism {args.formalism} --workspace {args.workspace}" + (" --observed" if args.observed else "")
    return SubmissionPlan(
        stage="fit",
        tag=args.tag,
        entry_point="datacards/run_fit.py",
        jobs=[JobSpec(name=f"{args.formalism}_{poi}", arguments=f"{options} --pois {poi}") for poi in pois],
        ntupletag=args.ntupletag,
        request_cpus=1,
        request_memory_mb=args.request_memory_mb,
        extra_classads={"environment": f'"FITDIR={args.fitdir}"'},
    )


def main():
    args = parse_args()
    return submit(build_plan(args), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
