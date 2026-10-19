#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

import ROOT

import shapes.naming as naming
from shapes.estimations.fakefactors import fake_factor_estimation
from shapes.estimations.qcd import qcd_estimation
from shapes.estimations.ttbar_emb import emb_ttbar_contamination_estimation
from common.shapes_merge import merge_if_needed, merge_ff_reuse_if_needed
from CustomLogging import setup_logging, LogContext
from common.analysis import BACKGROUNDS
from common.systematics import ERA_TAG
import tau_es.energy_scales as tau_es_energy_scales


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input-file", required=True, help="Input root file.")
    parser.add_argument("-e", "--era", required=True, help="Experiment era.")
    parser.add_argument(
        "--do-emb-tt",
        action="store_true",
        help="Add embedded ttbar contamination systematic to file.",
    )
    parser.add_argument(
        "--do-ff",
        action="store_true",
        help="Add fake factor estimations to file.",
    )
    parser.add_argument(
        "--do-qcd",
        action="store_true",
        help="Add qcd estimations to file.",
    )
    parser.add_argument("-s", "--special-analysis", dest="special", help="Special selection.", default="")
    return parser.parse_args()


CHANNELS = ("et", "mt", "tt", "em", "mm", "ee")
# booked process names, the TauES shift points are their own EMB_<shift> processes
PROCESSES = {naming.DATA, *(p.datacard for p in BACKGROUNDS.values()),
             *(f"EMB_{tau_es_energy_scales.procname_to_shift_string(name)}" for name in tau_es_energy_scales.PROCNAMES)}


def collect_inputs(inputfile, region):
    """{(channel, category, variable): {process: [shift, ...]}} of the histograms booked in `region` (None: signal region)."""
    inputs = {}
    for variable, bin_, name in naming.iter_histograms(inputfile):
        channel = bin_.split("_")[0]
        if channel not in CHANNELS:
            continue
        category, bin_region = naming.split_bin(bin_, channel)
        split = naming.split_histogram(name, PROCESSES)
        if bin_region != region or split is None:
            continue
        process, shift = split
        inputs.setdefault((channel, category, variable), {}).setdefault(process, []).append(shift)
    return inputs


def shifts_of(processes):
    """Every shift of a region's inputs, None (nominal) first."""
    return sorted({shift for shifts in processes.values() for shift in shifts}, key=lambda shift: (shift is not None, shift or ""))


def qcd_extrapolation_factor(channel, category, era):
    if channel in ["et", "mt"] and era == "2016":
        return 1.17
    if channel == "em" and "NbtagGt1" in (category or ""):
        factor = {"2017": 0.69, "2018": 0.67}.get(era, 0.71 if "2016" in era else None)
        if factor is None:
            logger.warning("No correction for given era %s available. Setting extrapolation factor to 1.0", era)
            return 1.0
        return factor
    if channel == "tt":
        return 1.5
    return 1.0


def main(args):
    # Auto-detect and hadd condor/submit_shapes.py's --process-selection parts before
    # opening args.input_file (see common/shapes_merge.py) -- no-op for an unsplit shapes.root.
    merge_if_needed(Path(args.input_file), logger=logger)
    # Same idea for the ff-reuse case: merges a shapes_ff_only.root part onto a copy of the
    # ss-os file, so estimations/plotting only ever see one fully-merged shapes.root.
    merge_ff_reuse_if_needed(Path(args.input_file), logger=logger)

    input_file = ROOT.TFile(args.input_file, "update")
    logger.info("Reading inputs from file {}".format(args.input_file))
    if args.do_qcd:
        logger.info("Starting estimations for the QCD mulitjet process.")
        for (channel, category, variable), processes in collect_inputs(input_file, "ss").items():
            common_kwargs = dict(
                rootfile=input_file, channel=channel, category=category, variable=variable,
                is_embedding=False, extrapolation_factor=qcd_extrapolation_factor(channel, category, args.era),
            )
            for shift in shifts_of(processes):
                naming.write(input_file, *qcd_estimation(**common_kwargs, shift=shift))
            if channel == "em":
                for shift, scale in (("subtrMCUp", 0.8), ("subtrMCDown", 1.2)):
                    naming.write(input_file, *qcd_estimation(**common_kwargs, shift=shift, sub_scale=scale))
    if args.do_emb_tt:
        logger.info("Producing embedding ttbar systematics.")
        for (channel, category, variable), processes in collect_inputs(input_file, None).items():
            for process, shifts in processes.items():
                if process.startswith("EMB") and None in shifts:
                    for scale in (0.1, -0.1):
                        naming.write(input_file, *emb_ttbar_contamination_estimation(
                            input_file, channel, category, variable, ERA_TAG[args.era], sub_scale=scale, process=process))
    if args.do_ff:
        logger.info("Starting estimations for fake factors and their systematics")
        for (channel, category, variable), processes in collect_inputs(input_file, "ar").items():
            with LogContext(logger).duplicate_filter():
                for shift in shifts_of(processes):
                    naming.write(input_file, *fake_factor_estimation(
                        rootfile=input_file, channel=channel, category=category, variable=variable, shift=shift))

    logger.info("Successfully finished estimations.")
    input_file.Close()
    return


if __name__ == "__main__":
    args = parse_args()
    logger = setup_logging(logger=logging.getLogger(__name__))
    main(args)
