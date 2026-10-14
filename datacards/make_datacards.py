import argparse
import glob
import importlib
import json
import logging
import os

from config.analysis import ACTIVE_ANALYSIS
from config.logging_setup_configs import setup_logging
from config.processes import datacard_backgrounds
from datacards import MASS as _MASS
from datacards.categories import get_categories
from datacards.systematics import add_systematics

get_signals = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.datacards.systematics").get_signals
try:
    _CADI = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.datacards.combine_model").CADI_LINE
except (ModuleNotFoundError, AttributeError):
    _CADI = "hig-26-018"
from datacards.tools import (
    apply_nn_rebinning,
    convert_shapes_to_lnN,
    filter_zero_yield_processes,
    filter_zero_yield_systs,
    fix_negative_bins,
    load_systematic_shapes,
    signal_shape_pattern,
    replace_with_asimov,
)


def str2bool(v):
    if isinstance(v, bool):
        return v
    if str(v).lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif str(v).lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


parser = argparse.ArgumentParser()
parser.add_argument("--era", type=str, default="2018",
                    help="Era or comma-separated list of eras (e.g. 2018 or 2022preEE,2022postEE). "
                         "Multiple eras produce output in {output-dir}/{channel}/{era}/")
parser.add_argument("--channels", type=str, default="mt", help="Comma-separated list of channels")
parser.add_argument("--categories", type=str, default="stxs_stage0_run3",
                    help="Categorization scheme: stxs_stage0_run3 (DNN, default), "
                         "stxs_stage0_run2, stxs_stage1p2_run2, stxs_stage1p2_run3, "
                         "stxs_stage1p2_run2_bkg_only, gof")
parser.add_argument("--gof-category-name", type=str, default="gof")
parser.add_argument("--stxs-stage", type=str, default="stage0", choices=["stage0", "stage1p2"],
                    help="Signal split: per production mode or per recommended <PROCESS>_<STXS_BIN> (must match produce_shapes --stxs-stage)")

parser.add_argument("--real-data", type=str2bool, default=False, help="Use data_obs instead of generating Asimov")
parser.add_argument("--embedding", type=str2bool, default=True, help="Use embedded samples")
parser.add_argument("--jetfakes", type=str2bool, default=True, help="Use jetFakes (FF method)")
parser.add_argument("--ff-type", choices=["fake_factor", "ml_fake_factor"], default="fake_factor", help="Fake factor flavour of the shapes (ml_fake_factor books the machine-learned systematics)")
parser.add_argument("--bbb", type=str2bool, default=True, help="Apply autoMCStats (Bin-by-Bin) uncertainties")

parser.add_argument("--correlate-emb", type=str2bool, default=True)
parser.add_argument("--convert-shapes-to-lnN", type=str2bool, default=True, help="Symmetrize noise shapes to lnN")

parser.add_argument("--rebinning-strategy", type=str, default="none", choices=["none", "total_bkg", "per_process", "total_bkg__per_process", "combine"])

parser.add_argument("--rebinning-threshold", type=float, default=10.0)

parser.add_argument("--rebinning-using-combine", type=str2bool, default=False)
parser.add_argument("--rebinning-using-combine-threshold", type=float, default=10.0)
parser.add_argument("--rebinning-using-combine-uncert-fraction", type=float, default=0.1)
parser.add_argument("--rebinning-using-combine-mode", type=int, default=1)

parser.add_argument("--custom-binning-file", type=str, default=None, help="Path to JSON file containing custom binning definitions")

parser.add_argument("--input-dir", type=str, default=".",
                    help="Directory containing the synced shape ROOT files")
parser.add_argument("--ntupletag", type=str, default=None,
                    help="Ntuple tag used in the shape filename: {era}-{channel}-{ntuple_tag}-{tag}.root")
parser.add_argument("--tag", type=str, default=None,
                    help="Shape tag used in the shape filename: {era}-{channel}-{ntuple_tag}-{tag}.root")
parser.add_argument("--output-dir", type=str, default="output_cards", help="Directory the datacards are written to ({channel}/{era}/{bin}.txt below it)")

parser.add_argument("--systematics", type=str2bool, default=True, help="Add shape systematics")

# Experimental user workflows
parser.add_argument("--nn-output-gof-bkg-only", type=str2bool, default=False, help="Enable Goodness-of-Fit background-only workflow using real data")
parser.add_argument("--bias-test", type=str2bool, default=False, help="Enable Bias test workflow using all NN classes (replaces data with Asimov)")

parser.add_argument("--log-level", type=str, default="INFO")

args = parser.parse_args()
logger = setup_logging(logger=logging.getLogger(__name__), level=getattr(logging, args.log_level.upper()))
logger.info(f"Starting datacard generation with arguments: {args}")


def main():
    # Imported here (not at module scope) so --help works even without a
    # CMSSW environment sourced.
    import CombineHarvester.CombineTools.ch as ch

    if args.nn_output_gof_bkg_only and args.bias_test:
        raise ValueError("Cannot enable both --nn-output-gof-bkg-only and --bias-test simultaneously.")

    if args.nn_output_gof_bkg_only:
        logger.info("Executing GoF on background-only classes. Overriding categories, real_data, and output_folder.")
        args.categories = "stxs_stage1p2_run2_bkg_only"
        args.real_data = True

    if args.bias_test:
        logger.info("Executing Bias test setup. Overriding real_data, setting output_folder.")
        args.real_data = False

    channels = args.channels.split(',')
    eras = args.era.split(',')
    masses = ["*"] if args.stxs_stage == "stage1p2" else [_MASS]

    def make_datacards_for_era(era: str, channels: list, output_folder: str) -> None:
        """Run the full datacard pipeline for a single era over the given channels."""
        logger.info(f"--- Era: {era}  Channels: {channels} ---")

        cb = ch.CombineHarvester()

        for channel in channels:
            categories = get_categories(
                channel=channel,
                categorization=args.categories,
                gof_category_name=args.gof_category_name,
                embedding=args.embedding,
                jetfakes=args.jetfakes,
            )
            bkgs = datacard_backgrounds(channel=channel, embedding=args.embedding, jetfakes=args.jetfakes)
            sigs = get_signals(stxs_stage=args.stxs_stage)

            logger.info(f"Initializing channel {channel} with {len(categories)} categories: {categories}")
            cb.AddObservations(["*"], ["htt"], [era], [channel], categories)
            cb.AddProcesses(["*"], ["htt"], [era], [channel], bkgs, categories, False)
            cb.AddProcesses(masses, ["htt"], [era], [channel], sigs, categories, True)

        root_files = {}
        for channel in channels:
            if args.categories == "stxs_stage0_run3":
                # Run3 DNN categories are split one-category-per-file by
                # convert_to_synced_shapes.py:
                #   synced_shapes-{era}-{channel}-{ntuple_tag}-{tag}/{era}-{channel}-synced-{category}.root
                sync_dir = os.path.join(
                    args.input_dir,
                    f"synced_shapes-{era}-{channel}-{args.ntupletag}-{args.tag}",
                )
                bin_files = {}
                for _, bin_name in get_categories(
                    channel=channel,
                    categorization=args.categories,
                    gof_category_name=args.gof_category_name,
                    embedding=args.embedding,
                    jetfakes=args.jetfakes,
                ):
                    category = bin_name[len(channel) + 1:]
                    bin_files[bin_name] = os.path.join(sync_dir, f"{era}-{channel}-synced-{category}.root")
                root_files[channel] = bin_files
                logger.info(f"Extracting shapes for {channel} from {len(bin_files)} per-category files in {sync_dir}")
                for bin_name, root_file in bin_files.items():
                    cb.cp().channel([channel]).bin([bin_name]).backgrounds().ExtractShapes(
                        root_file, "$BIN/$PROCESS", "$BIN/$PROCESS_$SYSTEMATIC")
                    cb.cp().channel([channel]).bin([bin_name]).signals().ExtractShapes(
                        root_file, signal_shape_pattern(cb), f"{signal_shape_pattern(cb)}_$SYSTEMATIC")
            else:
                if args.ntupletag is None or args.tag is None:
                    raise ValueError("--ntupletag and --tag are required to locate the shape file {era}-{channel}-{ntuple_tag}-{tag}.root")
                root_file = os.path.join(args.input_dir, f"{era}-{channel}-{args.ntupletag}-{args.tag}.root")
                root_files[channel] = root_file
                logger.info(f"Extracting shapes for {channel} from {root_file}")
                cb.cp().channel([channel]).backgrounds().ExtractShapes(
                    root_file, "$BIN/$PROCESS", "$BIN/$PROCESS_$SYSTEMATIC")
                cb.cp().channel([channel]).signals().ExtractShapes(
                    root_file, signal_shape_pattern(cb), f"{signal_shape_pattern(cb)}_$SYSTEMATIC")

        fix_negative_bins(cb)
        filter_zero_yield_processes(cb)

        if not args.real_data:
            replace_with_asimov(cb)

        logger.info("Adding Systematics...")
        if not args.systematics:
            logger.warning("Shape systematics disabled (--systematics false); lnN systematics (lumi, xsec, ...) are still added.")
        add_systematics(
            cb,
            era=era,
            jetfakes=args.jetfakes,
            ff_ml=args.ff_type.startswith("ml_"),
            embedding=args.embedding,
            correlate_emb=args.correlate_emb,
            stxs_stage=args.stxs_stage,
            shape_systematics=args.systematics,
        )

        for channel in channels:
            load_systematic_shapes(cb, root_files[channel], channel)

        filter_zero_yield_systs(cb)

        # $BIN expands to the current bin name (e.g. "mt_ggh"), which already
        # includes the channel prefix -- unlike $BINID, which is a bare integer.
        # measurement categories follow the recommended RECO__<CADI-line>__<CATEGORY> scheme, GoF keeps htt_*
        is_gof = args.categories == "gof" or args.nn_output_gof_bkg_only
        ch.SetStandardBinNames(cb, "$ANALYSIS_$BIN_$ERA" if is_gof else f"RECO__{_CADI}__$BIN_$ERA")

        custom_binnings = None
        if args.custom_binning_file:
            with open(args.custom_binning_file, "r") as f:
                custom_binnings = json.load(f)

        if args.categories != "gof":
            if args.rebinning_strategy == "none":
                if custom_binnings is not None:
                    for category, edges in custom_binnings.items():
                        if category in cb.cp().bin_set():
                            logger.info(f"Applying dedicated custom binning to {category}: {edges}")
                            cb.cp().bin([category]).VariableRebin(edges)
                else:
                    logger.info("No rebinning strategy applied.")

            elif args.rebinning_strategy in {"total_bkg", "per_process", "total_bkg__per_process", "combine"}:
                if args.rebinning_strategy == "combine":
                    logger.info("Applying rebinning using Combine's Rebin method with custom overrules...")
                    rebinner = (
                        ch.AutoRebin()
                        .SetBinThreshold(args.rebinning_threshold)
                        .SetBinUncertFraction(args.rebinning_using_combine_uncert_fraction)
                        .SetRebinMode(args.rebinning_using_combine_mode)
                        .SetPerformRebin(True)
                        .SetVerbosity(1)
                    )
                    for category in cb.cp().bin_set():
                        if custom_binnings is not None and category in custom_binnings:
                            logger.info(f"Overruling category {category} with dedicated custom binning: {custom_binnings[category]}")
                            cb.cp().bin([category]).VariableRebin(custom_binnings[category])
                        else:
                            category_cb = cb.cp().bin([category])
                            rebinner.Rebin(category_cb, cb)
                else:
                    apply_nn_rebinning(
                        cb,
                        strategy=args.rebinning_strategy,
                        threshold=args.rebinning_threshold,
                        custom_binnings=custom_binnings,
                    )
            else:
                raise ValueError(f"Invalid rebinning strategy: {args.rebinning_strategy}")

        if args.convert_shapes_to_lnN:
            convert_shapes_to_lnN(cb)

        if args.bbb:
            logger.info("Adding AutoMCStats...")
            cb.SetAutoMCStats(cb, 0.0)

        logger.info(f"Writing datacards to {output_folder}")
        os.makedirs(output_folder, exist_ok=True)

        writer = ch.CardWriter(
            os.path.join(output_folder, "$BIN.txt"),
            os.path.join(output_folder, f"common/htt_input_{era}.root")
        )
        writer.WriteCards("", cb)

        if args.bbb:
            for card in glob.glob(os.path.join(output_folder, "**/*.txt"), recursive=True):
                with open(card, "r", encoding="utf-8") as handle:
                    lines = [line for line in handle if "autoMCStats" not in line]
                lines.append(" * autoMCStats 0.0\n")
                with open(card, "w", encoding="utf-8") as handle:
                    handle.writelines(lines)

        logger.info(f"Done: era={era}, channels={channels}")

    # Always loop per channel x era -> {output_folder}/{channel}/{era}/{bin}.txt
    for era in eras:
        for channel in channels:
            output_folder = os.path.join(args.output_dir, channel, era)
            make_datacards_for_era(era, [channel], output_folder)

    # ------------------------------------------------------------------ #
    # Combination with combineCards.py
    # ------------------------------------------------------------------ #
    def run_combine_cards(card_map: dict, output_card: str) -> None:
        """
        Run combineCards.py with {label: path} pairs and write to output_card.
        card_map: {label -> path/to/card.txt}
        """
        import shutil
        import subprocess
        combine_cards_exe = shutil.which("combineCards.py")
        if combine_cards_exe is None:
            logger.error("combineCards.py not found in PATH — skipping combination.")
            return
        os.makedirs(os.path.dirname(output_card), exist_ok=True)
        cmd = [combine_cards_exe] + [f"{label}={path}" for label, path in sorted(card_map.items())]
        logger.info(f"Running: {' '.join(cmd)}")
        with open(output_card, "w") as fout:
            result = subprocess.run(["nice", "-n", "19", *cmd], stdout=fout, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"combineCards.py failed:\n{result.stderr}")
        else:
            logger.info(f"Written combined card: {output_card}")

    # Per-channel combination (all eras)
    per_channel_cards = {}  # label -> path, used for total combination
    for channel in channels:
        card_map = {}
        for era in eras:
            era_dir = os.path.join(args.output_dir, channel, era)
            for card_path in glob.glob(os.path.join(era_dir, "*.txt")):
                bin_name = os.path.splitext(os.path.basename(card_path))[0]
                label = f"{channel}_{era}_{bin_name}"
                card_map[label] = card_path
        if card_map:
            out = os.path.join(args.output_dir, channel, "combined.txt")
            run_combine_cards(card_map, out)
            per_channel_cards[channel] = out

    # Total combination (all channels x all eras)
    if len(per_channel_cards) > 1:
        total_card_map = {}
        for channel in channels:
            ch_dir = os.path.join(args.output_dir, channel)
            for era in eras:
                era_dir = os.path.join(ch_dir, era)
                for card_path in glob.glob(os.path.join(era_dir, "*.txt")):
                    bin_name = os.path.splitext(os.path.basename(card_path))[0]
                    label = f"{channel}_{era}_{bin_name}"
                    total_card_map[label] = card_path
        out = os.path.join(args.output_dir, "cmb", "combined.txt")
        run_combine_cards(total_card_map, out)

    logger.info("All done!")


if __name__ == "__main__":
    main()
