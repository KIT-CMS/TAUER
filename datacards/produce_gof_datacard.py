#!/usr/bin/env python3
"""Produce a goodness-of-fit (GoF) datacard from a synced shape file.

Python control-script replacement for the former datacards/produce_gof_datacard.sh
(Phase 6d). Same positional/optional arguments and defaults as the bash
version.

Calls the relocated combine_datacards/make_datacards.py --categories gof (see
STATUS.md "## Phase 2d"/"## Phase 3"). Expects a *synced* shape ROOT file
(produced by shapes/convert_to_synced_shapes.py --gof) placed at
    ${FITDIR}/output/shapes/${ERA}-${CHANNEL}-${NTUPLE_TAG}-${VARIABLE}.root
containing a TDirectory named "${CHANNEL}_${VARIABLE}" (e.g. "mt_m_vis").
datacards/run_gof.py does that placement for you; run this directly only if
you already have such a synced file.

IMPORTANT (Phase 4 fix): --gof-category-name must equal "${CHANNEL}_${VARIABLE}",
which is the TDirectory name convert_to_synced_shapes.py --gof writes and the
name make_datacards' ExtractShapes("$BIN/$PROCESS") looks up.

The GoF background model is the MC-only closure validated in Phase 3
(embedding=False, jetfakes=False -> the 12-process ZTT/ZL/ZJ/TTT/TTL/TTJ/
VVT/VVL/VVJ/W + ggH/qqH card whose yields came out bit-identical to legacy
SMRun2Legacy). Pass --embedding/--jetfakes to switch models once
embedding/FF shape files are produced.
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
        description="Produce a goodness-of-fit (GoF) datacard from a synced shape file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("era")
    parser.add_argument("channel")
    parser.add_argument("variable")
    parser.add_argument(
        "ntuple_tag",
        nargs="?",
        default=None,
        help=f"CROWN ntuple tag (default: $NTUPLE_TAG env var, else {DEFAULT_NTUPLE_TAG!r})",
    )
    parser.add_argument(
        "--use-asimov",
        action="store_true",
        help="Replace observation with the Asimov (b-only) expectation. "
        "Default: use the real recorded data_obs (needed for a real data-vs-model GoF p-value).",
    )
    parser.add_argument("--embedding", action="store_true", help="Use the embedding background model.")
    parser.add_argument("--jetfakes", action="store_true", help="Use the jet-fakes background model.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    ntuple_tag = args.ntuple_tag or os.environ.get("NTUPLE_TAG") or DEFAULT_NTUPLE_TAG

    real_data = not args.use_asimov
    gof_category_name = f"{args.channel}_{args.variable}"

    fitdir = get_fitdir()
    shapes_dir = f"{fitdir}/output/shapes"
    output_folder = f"{fitdir}/output/datacards/{args.era}-{args.channel}-{args.variable}-gof"

    print(
        f"[GoF datacard] era={args.era} channel={args.channel} variable={args.variable} "
        f"real_data={str(real_data).lower()} embedding={str(args.embedding).lower()} "
        f"jetfakes={str(args.jetfakes).lower()}"
    )
    print(
        f"[GoF datacard] input={shapes_dir}/{args.era}-{args.channel}-{ntuple_tag}-{args.variable}.root  "
        f"category={gof_category_name}"
    )

    cmd = [
        "python3",
        "combine_datacards/make_datacards.py",
        f"--era={args.era}",
        f"--channels={args.channel}",
        "--categories=gof",
        f"--gof-category-name={gof_category_name}",
        "--stxs-signals=stxs_stage0",
        f"--input-folder={shapes_dir}",
        f"--ntuple-tag={ntuple_tag}",
        f"--tag={args.variable}",
        f"--real-data={str(real_data).lower()}",
        f"--embedding={str(args.embedding).lower()}",
        f"--jetfakes={str(args.jetfakes).lower()}",
        f"--output-folder={output_folder}",
    ]
    result = run_in_cmsenv(
        cmd, cwd=REPO_ROOT, env_overrides={"PYTHONPATH": pythonpath_with_tff()}, check=False
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
