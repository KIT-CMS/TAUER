#!/usr/bin/env python3
"""MultiDimFit of the POIs of the analysis workspace of produce_workspace.py, one fit per POI with the others floating.

The POIs are the multiSignalModel ones of combine_model.poi_scheme(--stxs-stage). --formalism xsec is the cross-section
formalism of the STXS recommendations (FittingProcedures.md): the normalisation theory NPs are frozen, except the migrations
across boundaries merged into one POI (combine_model.frozen_theory_nuisances); --formalism mu profiles all of them.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.environment import get_fitdir, run_in_cmsenv
from common.analysis import ACTIVE_ANALYSIS
from datacards import MASS


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("analysis", help="Categorization scheme: the fit uses $FITDIR/output_<analysis>/<--workspace>")
    parser.add_argument("--stxs-stage", choices=["stage0", "stage1p2"], default="stage0", help="POI scheme the workspace was built with")
    parser.add_argument("--formalism", choices=["xsec", "mu"], default="xsec", help="xsec: normalisation theory NPs frozen; mu: all profiled")
    parser.add_argument("--pois", default=None, help="Comma-separated POIs to fit (default: all of the scheme)")
    parser.add_argument("--workspace", default="cmb/ws.root", help="Workspace relative to $FITDIR/output_<analysis> (default: all channels and eras)")
    parser.add_argument("--observed", action="store_true", help="Fit the data instead of the Asimov dataset with all POIs at 1")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    combine_model = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.datacards.combine_model")
    scheme = combine_model.poi_scheme(args.stxs_stage)
    pois = args.pois.split(",") if args.pois else list(scheme)
    if unknown := set(pois) - set(scheme):
        print(f"ERROR: {sorted(unknown)} not in the {args.stxs_stage} POIs {list(scheme)}", file=sys.stderr)
        return 1
    workspace = Path(get_fitdir()) / f"output_{args.analysis}" / args.workspace
    if not workspace.is_file():
        print(f"ERROR: workspace not found: {workspace}. Run produce_workspace.py first.", file=sys.stderr)
        return 1

    # a regex, so NPs that are not in these cards (e.g. pruned) do not stop the fit
    frozen = combine_model.frozen_theory_nuisances(args.stxs_stage) if args.formalism == "xsec" else []
    label = f"{'observed' if args.observed else 'asimov'}.{args.formalism}"
    status = 0
    for poi in pois:
        cmd = [
            "combine", "-M", "MultiDimFit", workspace.name, "-m", MASS, "--algo", "singles", "-P", poi, "--floatOtherPOIs", "1",
            "--setParameters", ",".join(f"{p}=1" for p in scheme), "--robustFit", "1", "--cminDefaultMinimizerStrategy", "0",
            "-n", f".{label}.{poi}",
            *([] if args.observed else ["-t", "-1"]),
            *(["--freezeParameters", f"rgx{{^({'|'.join(frozen)})$}}"] if frozen else []),
        ]
        print(f"[run_fit] {poi} ({label})")
        status |= run_in_cmsenv(cmd, cwd=workspace.parent, check=False, unlimited_stack=True).returncode
    return status


if __name__ == "__main__":
    raise SystemExit(main())
