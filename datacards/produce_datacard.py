#!/usr/bin/env python3
"""Produce SM H->tautau datacards from shapes output by running datacards/make_datacards.py inside CMSSW.

ANALYSIS is the categorization scheme passed as --categories (stxs_stage0_run3, stxs_stage0, ...). SHAPES is the
shapes.root of run.py SHAPES for the era and channel, read directly (bins <channel>_<category>, see shapes/naming.py),
and --variable the discriminant it holds. With ANALYSIS=gof the card has the single bin <channel> of a control-variable
shapes file (m_vis/mt/ZTT, ...) and is written to the GoF card directory used by datacards/run_gof.py. The GoF model
defaults to MC backgrounds (no embedding, no jet fakes), the analysis one to make_datacards.py's defaults.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.cmsenv import REPO_ROOT, get_fitdir, pythonpath_with_tff, run_in_cmsenv
from datacards import gof_card_dir


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("era")
    parser.add_argument("channel")
    parser.add_argument("analysis", help="Categorization scheme, e.g. gof, stxs_stage0, stxs_stage0_run3")
    parser.add_argument("shapes", help="shapes.root of run.py SHAPES for this era and channel")
    parser.add_argument("--variable", required=True, help="Discriminant: the variable directory of the shapes file")
    parser.add_argument("--use-asimov", action="store_true", help="GoF: replace the observation with the b-only Asimov expectation.")
    parser.add_argument("--embedding", choices=["true", "false"], default=None, help="Embedding background model (default: false for gof)")
    parser.add_argument("--jetfakes", choices=["true", "false"], default=None, help="Jet-fakes background model (default: false for gof)")
    parser.add_argument("--output-dir", default=None, help="Directory the datacards are written to (default: $FITDIR/output_<analysis>, or the GoF card directory for gof).")
    parser.add_argument("--stxs-stage", choices=["stage0", "stage1p2"], default="stage0", help="Signal split, must match the shapes' --stxs-stage (default: stage0)")
    parser.add_argument("--ff-type", choices=["fake_factor", "ml_fake_factor"], default=None, help="Fake factor flavour of the shapes (default: fake_factor)")
    args = parser.parse_args(argv)
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    fitdir = get_fitdir()
    cmd = [
        "python3", "datacards/make_datacards.py",
        f"--era={args.era}",
        f"--channels={args.channel}",
        f"--categories={args.analysis}",
        f"--shapes={Path(args.shapes).resolve()}",
        f"--variable={args.variable}",
        f"--stxs-stage={args.stxs_stage}",
    ]
    if args.analysis == "gof":
        cmd += [
            f"--real-data={str(not args.use_asimov).lower()}",
            f"--embedding={args.embedding or 'false'}",
            f"--jetfakes={args.jetfakes or 'false'}",
            # make_datacards.py appends {channel}/{era}
            f"--output-dir={args.output_dir or gof_card_dir(fitdir, args.era, args.channel, args.variable).parent.parent}",
        ]
    else:
        cmd.append(f"--output-dir={args.output_dir or f'{fitdir}/output_{args.analysis}'}")
        cmd += [f"--{option}={value}" for option, value in (("embedding", args.embedding), ("jetfakes", args.jetfakes)) if value]
    if args.ff_type:
        cmd.append(f"--ff-type={args.ff_type}")
    print(f"Producing datacard: era={args.era} channel={args.channel} analysis={args.analysis} shapes={args.shapes}")
    # datacards/ and config/ need to be importable -- run from the repo root.
    return run_in_cmsenv(cmd, cwd=REPO_ROOT, env_overrides={"PYTHONPATH": pythonpath_with_tff()}, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
