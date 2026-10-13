#!/usr/bin/env python3
"""Produce SM H->tautau datacards from shapes output by running datacards/make_datacards.py inside CMSSW.

ANALYSIS is the categorization scheme passed as --categories (stxs_stage0_run3, stxs_stage0, ...). With ANALYSIS=gof
a goodness-of-fit card is made for --variable from the synced shape file (shapes/convert_to_synced_shapes.py --gof)
    ${FITDIR}/output/shapes/${ERA}-${CHANNEL}-${NTUPLE_TAG}-${VARIABLE}.root
with its "${CHANNEL}_${VARIABLE}" directory; datacards/run_gof.py places it there. The GoF model defaults to MC
backgrounds (no embedding, no jet fakes), the analysis one to make_datacards.py's defaults.

NOTE: stxs_stage0_run3 (Run 3 DNN categories) needs the per-category synced shape files of
shapes/convert_to_synced_shapes.py.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.cmsenv import REPO_ROOT, get_fitdir, pythonpath_with_tff, run_in_cmsenv
from datacards import DEFAULT_NTUPLE_TAG, gof_card_dir


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("era")
    parser.add_argument("channel")
    parser.add_argument("analysis", help="Categorization scheme, e.g. gof, stxs_stage0, stxs_stage0_run3")
    parser.add_argument("ntuple_tag", nargs="?", default=None, help=f"CROWN ntuple tag (default: $NTUPLE_TAG, else {DEFAULT_NTUPLE_TAG!r})")
    parser.add_argument("--variable", help="Discriminant of the GoF card (ANALYSIS=gof only)")
    parser.add_argument("--use-asimov", action="store_true", help="GoF: replace the observation with the b-only Asimov expectation.")
    parser.add_argument("--embedding", choices=["true", "false"], default=None, help="Embedding background model (default: false for gof)")
    parser.add_argument("--jetfakes", choices=["true", "false"], default=None, help="Jet-fakes background model (default: false for gof)")
    parser.add_argument("--output-dir", default=None, help="Directory the datacards are written to (default: $FITDIR/output_<analysis>, or the GoF card directory for gof).")
    parser.add_argument("--stxs-stage", choices=["stage0", "stage1p2"], default="stage0", help="Signal split, must match the shapes' --stxs-stage (default: stage0)")
    parser.add_argument("--ff-type", choices=["fake_factor", "ml_fake_factor"], default=None, help="Fake factor flavour of the shapes (default: fake_factor)")
    args = parser.parse_args(argv)
    if (args.analysis == "gof") != (args.variable is not None):
        parser.error("--variable is required for, and only used with, ANALYSIS=gof")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    ntuple_tag = args.ntuple_tag or os.environ.get("NTUPLE_TAG") or DEFAULT_NTUPLE_TAG
    fitdir = get_fitdir()
    cmd = [
        "python3", "datacards/make_datacards.py",
        f"--era={args.era}",
        f"--channels={args.channel}",
        f"--categories={args.analysis}",
        f"--input-dir={fitdir}/output/shapes",
        f"--ntupletag={ntuple_tag}",
        f"--stxs-stage={args.stxs_stage}",
    ]
    if args.analysis == "gof":
        cmd += [
            f"--gof-category-name={args.channel}_{args.variable}",
            f"--tag={args.variable}",
            f"--real-data={str(not args.use_asimov).lower()}",
            f"--embedding={args.embedding or 'false'}",
            f"--jetfakes={args.jetfakes or 'false'}",
            # make_datacards.py appends {channel}/{era}
            f"--output-dir={args.output_dir or gof_card_dir(fitdir, args.era, args.channel, args.variable).parent.parent}",
        ]
    else:
        cmd += [f"--tag={args.analysis}", f"--output-dir={args.output_dir or f'{fitdir}/output_{args.analysis}'}"]
        cmd += [f"--{option}={value}" for option, value in (("embedding", args.embedding), ("jetfakes", args.jetfakes)) if value]
    if args.ff_type:
        cmd.append(f"--ff-type={args.ff_type}")
    print(f"Producing datacard: era={args.era} channel={args.channel} analysis={args.analysis} ntuple_tag={ntuple_tag}")
    # datacards/ and config/ need to be importable -- run from the repo root.
    return run_in_cmsenv(cmd, cwd=REPO_ROOT, env_overrides={"PYTHONPATH": pythonpath_with_tff()}, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
