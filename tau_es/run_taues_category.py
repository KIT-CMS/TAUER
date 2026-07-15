#!/usr/bin/env python3
"""
End-to-end tauES measurement for ONE category: build the datacard
(tau_es/make_taues_datacard.py), build its workspace, then run the
MultiDimFit scan (both via tau_es/run_taues_fit.py) -- one process, one
category, one output directory. This is the natural per-job granularity for
condor (see condor/submit_taues_fit.py): each category's datacard-build +
T2W + MultiDimFit is CPU-bound and independent of every other category, same
reasoning condor/submit_shapes.py already applies per (era, channel).

Must be run inside the CMSSW/Combine environment (`source
utils/setup_cmssw.sh`) -- same requirement as tau_es/make_taues_datacard.py
and combine_datacards/make_datacards.py.
"""
import argparse
import logging
import os

from config.logging_setup_configs import setup_logging
import tau_es.make_taues_datacard as make_taues_datacard
import tau_es.run_taues_fit as run_taues_fit


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--era", default="2018")
    p.add_argument("--channel", default="mt")
    p.add_argument("--category", required=True, help="One of DM0, DM1, DM10_11, Inclusive.")
    p.add_argument("--input-file", required=True)
    p.add_argument("--output-folder", required=True)
    p.add_argument("--real-data", action="store_true")
    p.add_argument("--bbb", action="store_true")
    p.add_argument("--shift-min", type=float, default=None)
    p.add_argument("--shift-max", type=float, default=None)
    p.add_argument("--shift-step", type=float, default=None)
    p.add_argument("--taues-min", type=float, default=-2.5)
    p.add_argument("--taues-max", type=float, default=1.6)
    p.add_argument("--taues-init", type=float, default=-1.0)
    p.add_argument("--points", type=int, default=30)
    p.add_argument("--with-r", action="store_true")
    p.add_argument("--skip-fit", action="store_true", help="Only build the datacard/workspace, skip MultiDimFit.")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main():
    args = parse_args()
    logger = setup_logging(logger=logging.getLogger(__name__), level=getattr(logging, args.log_level.upper()))

    category_folder = os.path.join(args.output_folder, args.category)

    datacard_args = argparse.Namespace(
        era=args.era, channel=args.channel, categories=[args.category],
        input_file=args.input_file, output_folder=category_folder,
        real_data=args.real_data, shift_min=args.shift_min, shift_max=args.shift_max,
        shift_step=args.shift_step, taues_min=args.taues_min, taues_max=args.taues_max,
        taues_init=args.taues_init, bbb=args.bbb, log_level=args.log_level,
    )
    logger.info(f"[{args.category}] Building datacard...")
    make_taues_datacard.build_datacard(datacard_args, logger)

    if args.skip_fit:
        logger.info(f"[{args.category}] --skip-fit set, done.")
        return

    workspace = os.path.join(category_folder, "workspace.root")
    ws_args = argparse.Namespace(datacard=category_folder, workspace=workspace, parallel=1)
    logger.info(f"[{args.category}] Building workspace (T2W)...")
    run_taues_fit.cmd_workspace(ws_args)

    fit_args = argparse.Namespace(
        workspace=workspace, tag=f"{args.era}_{args.category}_taues",
        taues_min=args.taues_min, taues_max=args.taues_max, taues_init=args.taues_init,
        points=args.points, with_r=args.with_r,
    )
    logger.info(f"[{args.category}] Running MultiDimFit scan...")
    result_file = run_taues_fit.cmd_fit(fit_args)
    logger.info(f"[{args.category}] Done: {result_file}")


if __name__ == "__main__":
    main()
