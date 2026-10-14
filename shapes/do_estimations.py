#!/usr/bin/env python3
import argparse
import importlib
import logging
import json
from pathlib import Path

import ROOT
from functools import partial

from shapes.estimations.fakefactors import fake_factor_estimation
from shapes.estimations.qcd import qcd_estimation
from shapes.estimations.ttbar_emb import emb_ttbar_contamination_estimation
from common.shapes_merge import merge_if_needed, merge_ff_reuse_if_needed
from config.analysis import ACTIVE_ANALYSIS
from config.logging_setup_configs import setup_logging, LogContext
from config.systematics import ERA_TAG
import tau_es.energy_scales as tau_es_energy_scales

try:
    _analysis_estimations = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.shapes.estimations.estimations")
except ModuleNotFoundError:
    _analysis_estimations = None



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
    parser.add_argument(
        "--do-qqh-procs",
        action="store_true",
        help="Add qqh procs estimations to file.",
    )
    parser.add_argument("-s", "--special-analysis", dest="special", help="Special selection.", default="")
    return parser.parse_args()


def parse_process_name(name, systematic_key):
    logger.debug("Processing histogram %s", name.GetName())
    dataset, selection, systematic, variable = name.GetName().split("#")
    if systematic_key in systematic:
        sel_split = selection.split("-", maxsplit=1)
        # Set category to default since not present in control plots.
        category = ""
        # Treat data hists seperately because only channel selection is applied to data.
        if "data" in dataset:
            channel = sel_split[0]
            # Set category label for analysis categories.
            if len(sel_split) > 1:
                category = sel_split[1]
            process = "data"
        else:
            channel = sel_split[0]
            # Control plots have no category: the histogram is {channel}-{process}[-{category}].
            process, _, category = sel_split[1].partition("-")
        return channel, category, variable, systematic, process
    else:
        return None, None, None, None, None


def add_input_to_inputdict(input_dict, channel, category, variable, systematic, process):
    if channel not in input_dict:
        input_dict[channel] = {category: {variable: {systematic: [process]}}}
    if category not in input_dict[channel]:
        input_dict[channel][category] = {variable: {systematic: [process]}}
    if variable not in input_dict[channel][category]:
        input_dict[channel][category][variable] = {systematic: [process]}
    if systematic not in input_dict[channel][category][variable]:
        input_dict[channel][category][variable][systematic] = [process]
    if systematic in input_dict[channel][category][variable]:
        input_dict[channel][category][variable][systematic].append(process)


def parse_histograms_for_ff(inputfile):
    ff_inputs = {}
    available_systematics = set()
    for key in inputfile.GetListOfKeys():
        channel, category, variable, systematic, process = parse_process_name(
            key, "anti_iso"
        )
        available_systematics.add(systematic)
        if channel is not None:
            add_input_to_inputdict(
                ff_inputs, channel, category, variable, systematic, process
            )
    logger.debug(available_systematics)
    return ff_inputs


def parse_histograms_for_qcd(inputfile):
    qcd_inputs = {}
    for key in inputfile.GetListOfKeys():
        channel, category, variable, systematic, process = parse_process_name(
            key, "same_sign"
        )
        if channel is not None:
            if channel in ["et", "mt", "em", "tt", "mm", "ee"]:
                add_input_to_inputdict(
                    qcd_inputs, channel, category, variable, systematic, process
                )
    return qcd_inputs


def parse_histograms_for_emb_estimation(inputfile):
    emb_categories = {}
    for key in inputfile.GetListOfKeys():
        dataset, selection, systematic, variable = key.GetName().split("#")
        if "Nominal" in systematic:
            sel_split = selection.split("-", maxsplit=1)
            if "EMB" in dataset or ("emb" in dataset and "jetFakes" not in dataset):
                channel = sel_split[0]
                category = sel_split[1].replace("EMB", "").strip("-")
                if channel in emb_categories:
                    if category in emb_categories[channel]:
                        emb_categories[channel][category].append(variable)
                    else:
                        emb_categories[channel][category] = [variable]
                else:
                    emb_categories[channel] = {category: [variable]}
    return emb_categories




def main(args):
    # Auto-detect and hadd condor/submit_shapes.py's --process-selection parts before
    # opening args.input_file (see common/shapes_merge.py) -- no-op for an unsplit shapes.root.
    merge_if_needed(Path(args.input_file), logger=logger)
    # Same idea for the ff-reuse case: merges a shapes_ff_only.root part onto a copy of the
    # ss-os file, so estimations/plotting only ever see one fully-merged shapes.root.
    merge_ff_reuse_if_needed(Path(args.input_file), logger=logger)

    input_file = ROOT.TFile(args.input_file, "update")
    logger.info("Reading inputs from file {}".format(args.input_file))
    tauES_names = []
    eleES_names = []
    if args.special == "TauES":
        # Extends _dataset_map/_process_map with the TauES shifts (tau_es/energy_scales.py).
        tauES_names = list(tau_es_energy_scales.PROCNAMES)
    elif args.special == "EleES":
        eleES_names = [tau_es_energy_scales.shift_to_procname(-1.5 + 0.05 * i) for i in range(0, 51)]
    else:
        pass
    if args.do_qcd:
        qcd_inputs = parse_histograms_for_qcd(input_file)
        logger.info("Starting estimations for the QCD mulitjet process.")
        logger.debug("%s", json.dumps(qcd_inputs, sort_keys=True, indent=4))
        for channel in qcd_inputs:
            for category in qcd_inputs[channel]:
                logger.info("Do estimation for category %s", category)
                extrapolation_factor = 1.0
                if channel in ["et", "mt"] and args.era == "2016":
                    extrapolation_factor = 1.17
                elif channel in ["em"]:
                    if "NbtagGt1" in category:
                        if "2016" in args.era:
                            extrapolation_factor = 0.71
                        elif args.era == "2017":
                            extrapolation_factor = 0.69
                        elif args.era == "2018":
                            extrapolation_factor = 0.67
                        else:
                            logger.warning(
                                "No correction for given era %s available. "
                                "Setting extrapolation factor to 1.0",
                                args.era,
                            )
                            extrapolation_factor = 1.0
                elif channel in ["tt"]:
                    extrapolation_factor = 1.5
                else:
                    pass
                for var in qcd_inputs[channel][category]:
                    common_kwargs = dict(
                        rootfile=input_file,
                        channel=channel,
                        selection=category,
                        variable=var,
                    )
                    for systematic in qcd_inputs[channel][category][var]:
                        estimated_hist = qcd_estimation(
                            **common_kwargs,
                            systematic=systematic,
                            is_embedding=False,
                            is_nlo=False,
                            extrapolation_factor=extrapolation_factor,
                        )
                        estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)
                    if channel in ["em"]:
                        for systematic, scale in zip(
                            ["subtrMCUp", "subtrMCDown"], [0.8, 1.2]
                        ):
                            for use_emb in [False]:
                                estimated_hist = qcd_estimation(
                                    **common_kwargs,
                                    systematic=systematic,
                                    is_embedding=use_emb,
                                    extrapolation_factor=extrapolation_factor,
                                    sub_scale=scale,
                                )
                                estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)
    if args.do_qqh_procs:
        if _analysis_estimations is None or not hasattr(_analysis_estimations, "parse_histograms_for_qqh"):
            logger.warning(f"analyses.{ACTIVE_ANALYSIS}.shapes.estimations.estimations has no qqH merge hook; skipping --do-qqh-procs.")
        else:
            qqh_procs = _analysis_estimations.parse_histograms_for_qqh(input_file)
            logger.info("Starting adding for qqH and VH processes.")
            logger.debug("%s", json.dumps(qqh_procs, sort_keys=True, indent=4))
            for channel in qqh_procs:
                for category in qqh_procs[channel]:
                    if "MTGt70" in category:
                        continue
                    logger.info("Do estimation for category %s", category)
                    for var in qqh_procs[channel][category]:
                        for systematic in qqh_procs[channel][category][var]:
                            estimated_hist = _analysis_estimations.qqh_merge_estimation(
                                input_file, channel, category, var, systematic=systematic
                            )
                            estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)
    if args.do_emb_tt:
        emb_categories = parse_histograms_for_emb_estimation(input_file)
        logger.info("Producing embedding ttbar systematics.")
        logger.debug("%s", json.dumps(emb_categories, sort_keys=True, indent=4))
        for channel in emb_categories:
            for category in emb_categories[channel]:
                logger.info("Do estimation for category %s", category)
                if args.special in ("EleES", "TauES"):
                    # Both special-analysis modes book one embedded "process" per
                    # energy-scale shift point (emb<shift>, e.g. "emb2p4"/"embminus1p6").
                    shift_names = eleES_names if args.special == "EleES" else tauES_names
                    for embsignal in shift_names:
                        print(embsignal)
                        var = emb_categories[channel][category][0]
                        estimated_hist = emb_ttbar_contamination_estimation(
                            input_file,
                            channel,
                            category,
                            var,
                            ERA_TAG[args.era],
                            sub_scale=0.1,
                            embname=embsignal,
                        )
                        estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)
                        estimated_hist = emb_ttbar_contamination_estimation(
                            input_file,
                            channel,
                            category,
                            var,
                            ERA_TAG[args.era],
                            sub_scale=-0.1,
                            embname=embsignal,
                        )
                        estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)
                else:
                    for var in emb_categories[channel][category]:
                        estimated_hist = emb_ttbar_contamination_estimation(
                            input_file,
                            channel,
                            category,
                            var,
                            ERA_TAG[args.era],
                            sub_scale=0.1,
                            embname="EMB",
                        )
                        estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)
                        estimated_hist = emb_ttbar_contamination_estimation(
                            input_file,
                            channel,
                            category,
                            var,
                            ERA_TAG[args.era],
                            sub_scale=-0.1,
                            embname="EMB",
                        )
                        estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)
    if args.do_ff:
        logger.info("Starting estimations for fake factors and their systematics")
        ff_inputs = parse_histograms_for_ff(input_file)
        logger.debug("%s", json.dumps(ff_inputs, sort_keys=True, indent=4))
        for ch in ff_inputs:
            for cat in ff_inputs[ch]:
                logger.info("Do estimation for category %s", cat)
                with LogContext(logger).duplicate_filter():
                    for var in ff_inputs[ch][cat]:
                        for systematic in ff_inputs[ch][cat][var]:

                            _fake_factor_estimation = partial(
                                fake_factor_estimation,
                                rootfile=input_file,
                                channel=ch,
                                selection=cat,
                                variable=var,
                            )
                            estimated_hist = _fake_factor_estimation(
                                systematic=systematic,
                            )
                            estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)
                            estimated_hist = _fake_factor_estimation(
                                systematic=systematic,
                                is_embedding=False,
                            )
                            estimated_hist.Write(estimated_hist.GetName(), ROOT.TObject.kOverwrite)

    logger.info("Successfully finished estimations.")
    input_file.Close()
    return


if __name__ == "__main__":
    args = parse_args()
    logger = setup_logging(logger=logging.getLogger(__name__))
    main(args)
