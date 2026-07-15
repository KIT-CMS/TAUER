#!/usr/bin/env python3
"""Produce SM H->tautau datacards from shapes output.

Python control-script replacement for the former datacards/produce_datacard.sh
(Phase 6d, see STATUS.md "## Phase 6d"). Behavior/CLI is unchanged from the
bash version: same positional arguments, same env-var fallbacks, same
combine_datacards/make_datacards.py invocation.

Rewired in Phase 2d (see STATUS.md "## Phase 2d") to call the relocated
combine_datacards/make_datacards.py instead of the previously-referenced
"MorphingCatVariables" binary, which never existed anywhere in SMRun2Legacy's
history (grepped across every branch) -- that was a stale reference from
before this repo's SMRun2Legacy-derived datacard code was relocated/rewired.
CombineHarvester/Combine/CMSSW themselves remain an external dependency,
reached via utils/setup_cmssw.sh's `cmsenv` (see common/cmsenv.py), exactly as
before -- nothing from CombineHarvester is vendored here.

ANALYSIS selects the categorization scheme passed as --categories to
make_datacards.py (e.g. gof, stxs_stage0, stxs_stage0_run3, ...) -- for GoF
datacards use produce_gof_datacard.py instead, which wires up the gof-specific
shape file layout directly.

NOTE: --categories stxs_stage0_run3 (the Run3 DNN categorization) requires
per-category "synced shape" ROOT files produced by shapes/convert_to_synced_shapes.py
-- until real DNN-scored shapes exist (see STATUS.md "## Blockers" #3), this
only works end-to-end for non-DNN categorizations (stxs_stage0,
stxs_stage1p2_run2, ...) whose shape files follow the flat
{era}-{channel}-{ntuple_tag}-{tag}.root naming.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.cmsenv import REPO_ROOT, get_fitdir, pythonpath_with_tff, run_in_cmsenv

DEFAULT_NTUPLE_TAG = "htt_260602_2024-25_v5"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Produce SM H->tautau datacards from shapes output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("era")
    parser.add_argument("channel")
    parser.add_argument("analysis", help="Categorization scheme, e.g. gof, stxs_stage0, stxs_stage0_run3")
    parser.add_argument(
        "ntuple_tag",
        nargs="?",
        default=None,
        help=f"CROWN ntuple tag (default: $NTUPLE_TAG env var, else {DEFAULT_NTUPLE_TAG!r})",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    ntuple_tag = args.ntuple_tag or os.environ.get("NTUPLE_TAG") or DEFAULT_NTUPLE_TAG

    print(
        f"Producing datacard: era={args.era} channel={args.channel} "
        f"analysis={args.analysis} ntuple_tag={ntuple_tag}"
    )

    fitdir = get_fitdir()
    shapes_dir = f"{fitdir}/output/shapes"
    # output_${ANALYSIS}/{channel}/{era}/*.txt -- matches make_datacards.py's own
    # per-era-then-channel loop nesting (channel outer, era inner) and
    # produce_workspace.py's INPUT_DIRS glob, which expects this same layout.
    output_folder = f"{fitdir}/output_{args.analysis}"

    cmd = [
        "python3",
        "combine_datacards/make_datacards.py",
        f"--era={args.era}",
        f"--channels={args.channel}",
        f"--categories={args.analysis}",
        f"--input-folder={shapes_dir}",
        f"--ntuple-tag={ntuple_tag}",
        f"--tag={args.analysis}",
        f"--output-folder={output_folder}",
    ]
    # combine_datacards/ and config/ need to be importable -- run from the repo
    # root (same convention as before). TauFakeFactors must also be on
    # PYTHONPATH: config/logging_setup_configs.py imports the CustomLogging
    # package, which only lives inside the TauFakeFactors submodule (Phase 4
    # finding -- this was untested under CMSSW's own Python until Phase 4's
    # real run hit it; same fix as run.py's shape-production path).
    result = run_in_cmsenv(
        cmd, cwd=REPO_ROOT, env_overrides={"PYTHONPATH": pythonpath_with_tff()}, check=False
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
