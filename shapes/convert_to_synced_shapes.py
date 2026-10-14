#!/usr/bin/env python3
# The flat-histogram -> synced ($BIN/$PROCESS TDirectory) converter that bridges
# shapes/produce_shapes.py output to the input format
# datacards/make_datacards.py's ExtractShapes("$BIN/$PROCESS", ...) reads. With
# --gof it writes one "{channel}_{variable}" TDirectory per discriminant variable. The booked process names
# already are the datacard ones (only data -> data_obs and, with --mc, jetFakesMC -> jetFakes are renamed here).
#
# `tau_es_map` below is generated from tau_es/energy_scales.py's canonical shift list
# (-12.0%..+8.0% in 0.2% steps, 100 points) -- the single source of truth for the tauES
# shift-point convention, same as shapes/produce_shapes.py/do_estimations.py use.
import os
import argparse
import logging
import multiprocessing

import ROOT

from tau_es.energy_scales import build_tau_es_map

logger = logging.getLogger("")

tau_es_map = build_tau_es_map()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--era", help="Experiment era.")
    parser.add_argument("-i", "--input-file", help="Input root file.")
    parser.add_argument("-o", "--output-dir", help="Output directory.")
    parser.add_argument(
        "--gof",
        action="store_true",
        help="Convert shapes for GoF or control plots. "
        "Use variable as category indicator.",
    )
    parser.add_argument(
        "--mc", action="store_true", help="Use jet fake estimation based on mc shapes."
    )
    parser.add_argument(
        "--special-analysis", dest="special", help="Use for special cases with no-trivial shapes.", default=""
    )
    parser.add_argument(
        "--variable-selection",
        default=None,
        type=str,
        nargs=1,
        help="Select final discriminator for shape creation.",
    )
    parser.add_argument(
        "-n", "--nprocs", dest="num_processes", default=1, type=int, help="Number of processes used."
    )
    return parser.parse_args()


def setup_logging(output_file, level=logging.INFO):
    logger.setLevel(level)
    formatter = logging.Formatter("%(name)s - %(levelname)s - %(message)s")

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    file_handler = logging.FileHandler(output_file, "w")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return


def write_hists_per_category(cat_hists: tuple):
    category, keys, channel, ofname, ifname = cat_hists
    infile = ROOT.TFile(ifname, "READ")
    dir_name = "{CHANNEL}_{CATEGORY}".format(CHANNEL=channel, CATEGORY=category)
    if "{category}" in ofname:
        outfile = ROOT.TFile(ofname.format(category=dir_name), "RECREATE")
    else:
        outfile = ROOT.TFile(
            ofname.replace(".root", "-" + category + ".root"), "RECREATE"
        )
    outfile.cd()
    outfile.mkdir(dir_name)
    outfile.cd(dir_name)
    for name, name_output in sorted(keys.items(), key=lambda x: x[1]):
        hist = infile.Get(name)
        hist.SetTitle(name_output)
        hist.SetName(name_output)
        hist.Write()
    outfile.Close()
    infile.Close()
    return


def main(args):
    input_file = ROOT.TFile(args.input_file)

    # Loop over histograms to extract relevant information for synced files.
    logging.info("Reading input histograms from file %s", args.input_file)
    hist_map = {}
    for key in input_file.GetListOfKeys():
        split_name = key.GetName().split("#")
        channel = split_name[1].split("-")[0]
        if args.gof:
            # Use variable as category label for GOF test and control plots.
            category = split_name[3]
            process = "data_obs" if "data" in split_name[0] else split_name[1].split("-")[1]
        else:
            category = split_name[1].split("-")[-1]
            process = "data_obs" if "data" in split_name[0] else "-".join(split_name[1].split("-")[1:-1])
            if "emb" in split_name[0] and split_name[0] != "emb0p0":
                process = split_name[0]
        # add the additional process of special analyses to the sync file
        if args.special == "TauES" or args.special == "EleES":
            if "emb" in split_name[0]:
                if "jetFakes" in split_name[0]:
                    process = "jetFakes_"
                    split_name[0] = (
                        split_name[0].replace("jetFakes", "").replace("emb", "")
                    )
                else:
                    process = "EMB_"
                    split_name[0] = split_name[0].replace("emb", "")
                if "minus" in split_name[0]:
                    process += "-"
                    split_name[0] = split_name[0].replace("minus", "")
                process += ".".join(split_name[0].split("p"))
            # Skip discriminant variables we do not want in the sync file.
            # This is necessary because the sync file only allows for one type of histogram.
            # A combination of the runs for different variables can then be used in separate files.
            if args.variable_selection is None:
                pass
            else:
                if split_name[3] not in args.variable_selection:
                    continue
        systematic = split_name[2]
        # V-associated hadronic events booked as qqH125 are merged into the qqH dataset by --do-qqh-procs
        if split_name[0] == "VH" and process == "qqH_htt125":
            continue
        # Skip systematics necessary for estimations which are of no further use.
        if "same_sign" in systematic or "anti_iso" in systematic:
            continue

        # Check if channel and category are already in the map
        if not channel in hist_map:
            hist_map[channel] = {}
        if not category in hist_map[channel]:
            hist_map[channel][category] = {}

        # the MC-based jet fake estimates take the datacard names in --mc mode, the data-driven ones otherwise
        if args.mc:
            if process in ["jetFakes", "QCD"]:
                continue
            process = process.removesuffix("MC")
        elif "MC" in process:
            continue
        if args.special == "TauES":
            if "EMB" in process:
                process  = "EMB_"+category+"_0.0"
            if "emb" in process:
                process = "EMB_"+category+"_"+tau_es_map[process]

        name_output = "{process}".format(process=process)
        if "Nominal" not in systematic:
            name_output += "_" + systematic
        logging.debug(
            "Adding histogram with name %s as %s to category %s.",
            key.GetName(),
            name_output,
            channel + "_" + category,
        )
        hist_map[channel][category][key.GetName()] = name_output
    # Clean up
    input_file.Close()

    # Loop over map and create the output file.
    for channel in hist_map:
        ofname = os.path.join(
            args.output_dir,
            "{ERA}-{CHANNELS}-synced.root".format(CHANNELS=channel, ERA=args.era),
        )
        logging.info(
            "Writing histograms to file %s with %s processes",
            ofname,
            args.num_processes,
        )

        if not os.path.exists(args.output_dir):
            os.mkdir(args.output_dir)
        with multiprocessing.Pool(args.num_processes) as pool:
            pool.map(
                write_hists_per_category,
                [
                    (*item, channel, ofname, args.input_file)
                    for item in sorted(hist_map[channel].items())
                ],
            )

    logging.info("Successfully written all histograms to file.")


if __name__ == "__main__":
    args = parse_args()
    setup_logging("convert_to_synced_shapes.log", level=logging.INFO)
    main(args)
