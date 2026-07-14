#!/usr/bin/env python
"""
Shape production for the TauHarvest SM H→ττ analysis.

Background sample names and base event selections are sourced from
TauFakeFactors preselection configs via config/shapes/tff_adapter.
Signal samples are defined in config/shapes/signal_files.
"""
import argparse
import logging
import os
import pickle
from functools import partial
from itertools import combinations

import numpy as np
import yaml

import config.shapes.process_selection as selection
import config.shapes.variations as variations
import shapes.utils as shape_utils
import config.ntuple_processor_config_helper as ntuple_processor_config_helper
from config.helper_collection import PreserveROOTPathsAsStrings
from config.logging_setup_configs import setup_logging
from config.shapes.category_selection import categorization as default_categorization
from config.shapes.taues_measurement_binning import categorization as taues_categorization
from config.shapes.channel_selection import channel_selection
from config.shapes.control_binning import control_binning as default_control_binning
from config.analysis import build_files_dict
from ntuple_processor import GraphManager, RunManager, UnitManager
from ntuple_processor.utils import Selection


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Produce shapes for the TauHarvest SM H→ττ analysis."
    )
    parser.add_argument("--era", required=True, type=str, help="Experiment era.")
    parser.add_argument(
        "--channels",
        default=[],
        type=lambda channellist: [channel for channel in channellist.split(",")],
        help="Channels to be considered, separated by a comma without space",
    )
    parser.add_argument(
        "--vs-jet-wp", required=True, type=str, help="Tau-vs-jet ID WP."
    )
    parser.add_argument(
        "--vs-ele-wp", required=True, type=str, help="Tau-vs-ele ID WP."
    )
    parser.add_argument(
        "--apply-tauid", action="store_true",
        help="Apply tau ID scale factors."
    )
    parser.add_argument(
        "--directory", required=True, type=str, help="Directory with CROWN ntuple outputs."
    )
    parser.add_argument("--et-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--mt-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--tt-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--em-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--mm-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--ee-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument(
        "--output-file", required=True, type=str, help="Output ROOT file."
    )
    parser.add_argument(
        "--process-selection", default=None,
        type=lambda proclist: set([process for process in proclist.split(",")]),
        help="Comma-separated list of processes to produce shapes for.",
    )
    parser.add_argument(
        "--control-plots", action="store_true",
        help="Produce shapes for control plots."
    )
    parser.add_argument(
        "--control-plot-set", default=["m_vis"], nargs="+", type=str,
        help="Set of variables for control plots.",
    )
    parser.add_argument(
        "--gof-inputs", action="store_true",
        help="Produce shapes for goodness-of-fit tests."
    )
    parser.add_argument(
        "--do-2d-gofs", action="store_true",
        help="Produce 2D GoF shapes."
    )
    parser.add_argument(
        "--control-plots-full-samples", action="store_true",
        help="Use all signal processes for control plots."
    )
    parser.add_argument(
        "--skip-systematic-variations", action="store_true",
        help="Skip systematic variations (faster, nominal shapes only).",
    )
    parser.add_argument(
        "--num-processes", default=1, type=int,
        help="Number of parallel processes for histogram production."
    )
    parser.add_argument(
        "--num-threads", default=1, type=int,
        help="Number of threads per process."
    )
    parser.add_argument(
        "--optimization-level", default=2, type=int,
        help="Graph optimization level (0-2)."
    )
    parser.add_argument(
        "--only-create-graphs", action="store_true",
        help="Only create and serialize the computation graphs, do not run."
    )
    parser.add_argument(
        "--graph-dir", default=None, type=str,
        help="Directory to write the serialized graph files."
    )
    parser.add_argument(
        "--collect-config-only", action="store_true",
        help="Only collect cuts/weights/datasets/variations into a YAML file."
    )
    parser.add_argument(
        "--config-output-file", default="tmp_config.yaml", type=str,
        help="YAML output file for --collect-config-only."
    )
    parser.add_argument(
        "--enable-booking-check", action="store_true",
        help="Enable double-booking check (slow)."
    )
    parser.add_argument(
        "--xrootd", action="store_true",
        help="Read input ntuples via xrootd."
    )
    parser.add_argument(
        "--validation-tag", default="default", type=str,
        help="Tag used for sample validation."
    )
    parser.add_argument(
        "--selection-option",
        help="Signal/control region selection.",
        choices=["CR", "DR;ff;wjet", "DR;ff;qcd", "DR;ff;ttbar"],
        default="CR",
    )
    parser.add_argument(
        "--ff-type",
        help=f"Type of fake factor. Set to 'none' to skip anti-iso variations.\n{variations.__FF_OPTION_info__}",
        default="none",
    )
    parser.add_argument(
        "--no-dnn-categorization", action="store_true",
        help="Produce shapes for variables in config/variables.yaml without DNN categorization (use when DNN friend trees are not available).",
    )
    parser.add_argument(
        "--special-analysis", default=None, choices=[None, "TauES"],
        help="Produce shapes for a special analysis instead of the default categorization. "
             "'TauES' books additional per-shift embedded ('emb<shift>') datasets for the "
             "tau energy-scale fit (mt channel only, -2.5%% to +2.5%% in 0.1%% steps).",
    )
    return parser.parse_args()


def load_variables_from_config(channel):
    import yaml
    import os
    _yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "variables.yaml")
    with open(_yaml_path) as _f:
        _cfg = yaml.safe_load(_f)
    _output_features = _cfg.get("output_features", [])
    from config.shapes.control_binning import control_binning as default_control_binning
    _available = set(default_control_binning.get(channel, {}).keys())
    _filtered = [v for v in _output_features if v in _available]
    if not _filtered:
        raise ValueError(f"No variables from config/variables.yaml are available in control_binning for channel {channel}. Available: {_available}. From YAML: {_output_features}")
    logger.info(f"Loaded {len(_filtered)} variables from config/variables.yaml for channel {channel}")
    return _filtered

def add_processes(add_fn, datasets, select_fn, channel):
    # Guard on dataset-key presence: eras that don't configure every process
    # group in config/samples.yaml (e.g. 2018, which currently only has
    # backgrounds + EMB for mt, no signals) simply skip that process instead
    # of KeyError-ing. Run3 eras are unaffected — every key below is always
    # present in their samples.yaml entries.
    def _add(name, key, selections_fn):
        dataset = datasets.get(key)
        if not dataset:
            return
        add_fn(name=name, dataset=dataset, selections=selections_fn())

    _add("data", "data", select_fn)
    _add("ztt",  "DY",   lambda: select_fn(*selection.DY.TT))
    _add("zl",   "DY",   lambda: select_fn(*selection.DY.L))
    _add("zj",   "DY",   lambda: select_fn(*selection.DY.J))
    _add("ttt",  "TT",   lambda: select_fn(*selection.TT.T))
    _add("ttl",  "TT",   lambda: select_fn(*selection.TT.L))
    _add("ttj",  "TT",   lambda: select_fn(*selection.TT.J))
    _add("vvt",  "VV",   lambda: select_fn(*selection.VV.T))
    _add("vvl",  "VV",   lambda: select_fn(*selection.VV.L))
    _add("vvj",  "VV",   lambda: select_fn(*selection.VV.J))
    _add("w",    "W",    lambda: select_fn(selection.W))
    _add("emb",  "EMB",  lambda: select_fn(selection.ZTT_embedded))
    _add("qqh",  "qqH",  lambda: select_fn(selection.qqH125))
    _add("ggh",  "ggH",  lambda: select_fn(selection.ggH125))
    _add("tth",  "ttH",  lambda: select_fn(selection.ttH))
    _add("vh",   "VH",   lambda: select_fn(selection.VH))


def get_select_function(channel_selection_obj, selection_kwargs, selection_memo):
    def _function(*args):
        _sel = [channel_selection_obj]
        for _proc in args:
            if _proc.__name__ not in selection_memo:
                selection_memo[_proc.__name__] = _proc(**selection_kwargs)
            _sel.append(selection_memo[_proc.__name__])
        return _sel
    return _function


def get_analysis_units(channel, era, datasets, categorization, apply_tauid, vs_jet_wp, vs_ele_wp, selection_option="CR", preselected=False, special=None):
    _sel_kwargs = dict(
        channel=channel, era=era, special=special,
        vs_jet_wp=vs_jet_wp, vs_ele_wp=vs_ele_wp,
        selection_option=selection_option, apply_wps=apply_tauid,
        preselected=preselected,
    )
    _memo = {}
    _ch_sel = channel_selection(**_sel_kwargs)
    _select = get_select_function(_ch_sel, _sel_kwargs, _memo)
    units = {}
    add_processes(
        add_fn=partial(shape_utils.add_process, analysis_unit=units, categorization=categorization, channel=channel),
        datasets=datasets, select_fn=_select, channel=channel,
    )
    return units


def get_control_units(channel, era, datasets, variables, apply_tauid, vs_jet_wp, vs_ele_wp, selection_option="CR", do_gofs=False, do_2dGofs=False, preselected=False):
    control_units = {}
    control_binning = default_control_binning
    if do_gofs:
        from config.shapes.gof_binning import load_gof_binning
        control_binning = load_gof_binning(era, channel)
        if do_2dGofs:
            variables_2d = []
            for var1, var2 in combinations(variables, 2):
                if f"{var1}_{var2}" in control_binning[channel]:
                    variables_2d.append(f"{var1}_{var2}")
                elif f"{var2}_{var1}" in control_binning[channel]:
                    variables_2d.append(f"{var2}_{var1}")
                else:
                    raise ValueError(f"No binning found for 2D variable from {var1} and {var2}")
            variables.extend(variables_2d)
    variable_set = set()
    for variable in set(variables):
        if variable not in control_binning[channel]:
            raise Exception(f"Variable {variable} not available in control_binning")
        variable_set.add(variable)
    logger.info(f"[INFO] Running control plots for variables: {variable_set}")
    _sel_kwargs = dict(
        channel=channel, era=era, special=None,
        vs_jet_wp=vs_jet_wp, vs_ele_wp=vs_ele_wp,
        selection_option=selection_option, apply_wps=apply_tauid,
        preselected=preselected,
    )
    _memo = {}
    _ch_sel = channel_selection(**_sel_kwargs)
    _select = get_select_function(_ch_sel, _sel_kwargs, _memo)
    add_processes(
        add_fn=partial(
            shape_utils.add_control_process,
            analysis_unit=control_units, channel=channel,
            binning=control_binning, variables=variable_set,
        ),
        datasets=datasets, select_fn=_select, channel=channel,
    )
    return control_units


def collect_config(graphs, era, channel, filename):
    r_manager = RunManager(
        graphs, create_histograms=False, create_config=True,
        config_formatter=ntuple_processor_config_helper.get_config_formatter(era=era),
    )
    r_manager.nthreads = 1
    for _graph in graphs:
        logger.info(f"Creating config for graph {_graph.name}")
        r_manager.node_to_root(_graph)
        ntuple_processor_config_helper.add_paths(graph=_graph, channel=channel, era=era, r_manager=r_manager)
    _path, _basename = os.path.split(filename)
    _path = os.path.join(_path, f"{era}__{channel}__{_basename}")
    with open(_path, "w") as config_file:
        yaml.dump(r_manager.config.regular, config_file, default_flow_style=False, Dumper=PreserveROOTPathsAsStrings)
    logger.info(f"Configuration written to {_path}")
    logger.info("Due to a ROOT/xrd bug the script may not exit cleanly. Kill with Ctrl+z && kill %1 if needed.")


def main(args):
    friend_directories = {
        "et": args.et_friend_directory,
        "mt": args.mt_friend_directory,
        "tt": args.tt_friend_directory,
        "em": args.em_friend_directory,
        "mm": args.mm_friend_directory,
        "ee": args.ee_friend_directory,
    }
    output_file = args.output_file if ".root" in args.output_file else f"{args.output_file}.root"

    files = build_files_dict(channels=args.channels, era=args.era)
    ntuple_directory = args.directory

    unit_manager = UnitManager()
    logger.info(f"Apply tau ID: {args.apply_tauid}")

    nominals = {args.era: {"datasets": {}, "units": {}}}

    for channel in args.channels:
        nominals[args.era]["datasets"][channel] = shape_utils.get_nominal_datasets(
            era=args.era, channel=channel,
            friend_directories=friend_directories,
            files=files,
            directory=ntuple_directory,
            xrootd=args.xrootd,
            validation_tag=args.validation_tag,
        )
        common_kwargs = dict(
            era=args.era, channel=channel,
            datasets=nominals[args.era]["datasets"][channel],
            apply_tauid=args.apply_tauid,
            vs_jet_wp=args.vs_jet_wp,
            vs_ele_wp=args.vs_ele_wp,
            selection_option=args.selection_option,
            preselected=False,
        )
        if args.control_plots:
            nominals[args.era]["units"][channel] = get_control_units(
                **common_kwargs, variables=args.control_plot_set, do_gofs=False,
            )
        elif args.gof_inputs:
            nominals[args.era]["units"][channel] = get_control_units(
                **common_kwargs, variables=args.control_plot_set,
                do_gofs=True, do_2dGofs=args.do_2d_gofs,
            )
        elif args.no_dnn_categorization:
            _vars = load_variables_from_config(channel)
            if not _vars:
                logger.warning(f"[no-dnn-categorization] No variables loaded for {channel}, using default set")
                _vars = ["m_vis", "pt_1", "pt_2", "eta_1", "eta_2", "mt_1", "mt_2", "mjj", "met", "mt_tot", "pt_tt", "pt_vis", "nbtag", "njets"]
                # Filter to only those available in control_binning
                _available = set(default_control_binning.get(channel, {}).keys())
                _vars = [v for v in _vars if v in _available]
                logger.info(f"[no-dnn-categorization] Using fallback variables for {channel}: {_vars}")
            else:
                logger.info(f"[no-dnn-categorization] Using variables for {channel}: {_vars}")
            nominals[args.era]["units"][channel] = get_control_units(
                **common_kwargs, variables=_vars,
            )
        elif args.special_analysis == "TauES":
            if channel != "mt":
                raise ValueError(
                    "--special-analysis TauES is only implemented for the mt channel "
                    f"(Phase 2a scope); got channel={channel!r}."
                )
            nominals[args.era]["units"][channel] = get_analysis_units(
                **common_kwargs, categorization=taues_categorization, special="TauES",
            )
            # Book additional per-shift embedded ("emb<shift>") datasets, reusing
            # the already-ported shape_utils.add_tauES_datasets/book_tauES_histograms
            # machinery (verified to match the real __EMBtauESshift_<x> friend-branch
            # suffix convention shipped by the Phase 2a 2018 embedded validation ntuples).
            #
            # Range/step corrected here: -2.5%..+2.5% in 0.1% steps (the original
            # guess, copied from smhtt_ul's dead/unused `tauESvariations` list in
            # shapes/do_estimations.py) does NOT match what's actually shipped.
            # Direct inspection of a real 2018 TauEmbedding-MuTauFinalState ntuple
            # (`pt_2__EMBtauESshift_<x>` branches) shows 100 shift points spanning
            # -12.0% to +8.0% in 0.2% steps, with 0.0% (nominal, unshifted branch)
            # excluded. Using the wrong range would silently skip real shift points
            # (shape_utils.add_tauES_datasets only logs a critical and continues
            # when `shiftname not in quantities_per_vars`, it doesn't raise) and
            # book variations for shift names that don't exist as branches at all.
            additional_emb_procS = set()
            _es_shifts = [
                round(x, 1)
                for x in np.arange(-12.0, 8.0 + 0.2, 0.2)
                if round(x, 1) != 0.0
            ]
            shape_utils.add_tauES_datasets(
                era=args.era, channel=channel,
                friend_directories=friend_directories, files=files,
                directory=ntuple_directory, nominals=nominals,
                tauESvariations=_es_shifts,
                selections=[
                    channel_selection(
                        channel=channel, era=args.era, special="TauES",
                        vs_jet_wp=args.vs_jet_wp, vs_ele_wp=args.vs_ele_wp,
                        selection_option=args.selection_option,
                    ),
                    selection.ZTT_embedded(
                        channel=channel, era=args.era,
                        apply_wps=args.apply_tauid, vs_jet_wp=args.vs_jet_wp,
                        vs_ele_wp=args.vs_ele_wp,
                    ),
                ],
                categorization=taues_categorization,
                additional_emb_procS=additional_emb_procS,
                validation_tag=args.validation_tag,
                xrootd=args.xrootd,
            )
            nominals[args.era].setdefault("tauES_procS", {})[channel] = additional_emb_procS
        else:
            nominals[args.era]["units"][channel] = get_analysis_units(
                **common_kwargs, categorization=default_categorization,
            )

    procS = args.process_selection if args.process_selection is not None else {
        "data", "ztt", "zl", "zj", "ttt", "ttl", "ttj",
        "vvt", "vvl", "vvj", "w", "ggh", "qqh", "tth", "vh",
    }

    dataS = {"data"} & procS
    # Embedding is optional; keep an explicit process set to simplify booking expressions.
    embS = {"emb"} & procS
    jetFakesDS = {
        ch: {"zj", "ttj", "vvj", "w"} & procS
        for ch in ["et", "mt", "tt", "em"]
    }
    leptonFakesS = {"zl", "ttl", "vvl"} & procS
    trueTauBkgS  = {"ztt", "ttt", "vvt"} & procS
    sm_signalsS  = {"ggh", "qqh", "tth", "vh"} & procS
    signalsS     = sm_signalsS
    if (args.control_plots or args.gof_inputs) and not args.control_plots_full_samples:
        signalsS = signalsS & {"ggh", "qqh", "vh", "tth"}
    simulatedProcsDS = {
        ch: jetFakesDS[ch] | leptonFakesS | trueTauBkgS | signalsS
        for ch in ["et", "mt", "tt", "em"]
    }
    logger.info(f"Processes: {procS}")

    def _book(processes, vlist):
        shape_utils.book_histograms(
            processes=processes, variations=vlist,
            manager=unit_manager,
            datasets=nominals[args.era]["units"][channel],
            enable_check=args.enable_booking_check,
        )

    for channel in args.channels:
        if args.special_analysis == "TauES":
            # TauES fit inputs: nominal background/embedded shapes in the
            # tauES categorization, plus one embedded template per tau-ES
            # shift (booked via book_tauES_histograms below). The regular
            # systematic-variation stack below is not relevant to this mode.
            _book(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesDS[channel], [variations.same_sign])
            shape_utils.book_tauES_histograms(
                manager=unit_manager,
                additional_emb_procS=nominals[args.era]["tauES_procS"][channel],
                datasets=nominals[args.era]["units"][channel],
                variations=[variations.same_sign],
                enable_check=args.enable_booking_check,
            )
            continue
        _book(signalsS, [])
        if channel in {"mt", "et", "tt"}:
            _book(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesDS[channel], [variations.same_sign])
        if channel in {"mt", "et"} and args.ff_type != "none":
            _book(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesDS[channel], variations.SemiLeptonicFFEstimations.unrolled())
        elif channel == "tt" and args.ff_type != "none":
            _book(dataS | embS | trueTauBkgS | leptonFakesS | jetFakesDS[channel], variations.FullyHadronicFFEstimations.unrolled())
        elif channel == "em":
            _book((dataS | embS | simulatedProcsDS[channel]) - signalsS, [variations.same_sign_em])
        elif channel in {"mm", "ee"}:
            _book(procS, [variations.same_sign])
        if not args.skip_systematic_variations:
            _book({"ggh"} & procS, [variations.ggh_acceptance, variations.ggh_muRmuF_acceptance])
            _book({"qqh"} & procS, [variations.qqh_acceptance, variations.qqh_muRmuF_acceptance])
            _book(signalsS, variations.LHE_scale.unrolled())
            _book({"ztt", "zj", "zl", "w"} & procS | signalsS, variations.Recoil.unrolled())
            _book(simulatedProcsDS[channel], [variations.met_unclustered, variations.pileup_reweighting])
            _book({"ztt", "zl", "zj"} & procS, [variations.zpt])
            _book({"ttt", "ttl", "ttj"} & procS, [variations.top_pt])
            if channel in ["et", "mt", "tt"]:
                _book(jetFakesDS[channel], [variations.jet_to_tau_fake])
                _book((trueTauBkgS | leptonFakesS | signalsS) - {"zl"}, variations.TauEnergyScale.unrolled())
            if channel in ["et", "mt"]:
                _book((trueTauBkgS | leptonFakesS | signalsS) - {"zl"}, [variations.tau_id_eff_lt])
                _book(embS, [variations.emb_tau_id_eff_lt, variations.emb_tau_id_eff_lt_corr])
                if args.ff_type != "none":
                    _book(dataS | embS | leptonFakesS | trueTauBkgS, variations.FakeFactorLT.unrolled())
                    _book(leptonFakesS | trueTauBkgS | embS, [variations.ff_variations_tau_es_lt])
                    _book(embS, [variations.ff_variations_tau_es_emb_lt])
            if channel in ["et", "em"]:
                _book(simulatedProcsDS[channel], [variations.ele_es_res, variations.ele_es_scale])
                _book(embS, [variations.emb_e_es])
            if channel == "mt":
                _book({"zl"} & procS, [variations.mu_fake_es_inc])
                _book(embS, [variations.emb_mu_fake_es_inc, variations.emb_mu_fake_es_inc_corr])
                if args.ff_type != "none":
                    _book(dataS | embS | leptonFakesS | trueTauBkgS, variations.FakeFactorLT.unrolled())
                    _book(leptonFakesS | trueTauBkgS | embS, [variations.ff_variations_tau_es_lt])
                    _book(embS, [variations.ff_variations_tau_es_emb_lt])
            if channel == "tt":
                _book((trueTauBkgS | leptonFakesS | signalsS) - {"zl"}, variations.TauEnergyScale.unrolled())
                if args.ff_type != "none":
                    _book(dataS | embS | leptonFakesS | trueTauBkgS, variations.FullyHadronicFFEstimations.unrolled())

    g_manager = GraphManager(unit_manager.booked_units, True)
    g_manager.optimize(args.optimization_level)
    graphs = g_manager.graphs
    for graph in graphs:
        print(f"{graph}")

    if args.collect_config_only:
        if len(args.channels) > 1:
            raise NotImplementedError("Config collection for multiple channels is not yet supported.")
        collect_config(graphs=graphs, era=args.era, channel=args.channels[0], filename=args.config_output_file)
        return

    if args.only_create_graphs:
        _channels = ",".join(args.channels)
        _processes = ",".join(sorted(procS))
        if args.control_plots or args.gof_inputs or args.no_dnn_categorization:
            graph_file_name = f"control_unit_graphs-{args.era}-{_channels}-{_processes}.pkl"
        else:
            graph_file_name = f"analysis_unit_graphs-{args.era}-{_channels}-{_processes}.pkl"
        graph_file = os.path.join(args.graph_dir, graph_file_name) if args.graph_dir else graph_file_name
        logger.info(f"Writing graphs to {graph_file}")
        with open(graph_file, "wb") as f:
            pickle.dump(graphs, f)
    else:
        r_manager = RunManager(graphs)
        r_manager.run_locally(output_file, args.num_processes, args.num_threads)


if __name__ == "__main__":
    args = parse_arguments()
    log_file = args.output_file.replace(".root", ".log") if ".root" in args.output_file else f"{args.output_file}.log"
    logger = setup_logging(logger=logging.getLogger(__name__))
    variations.set_jet_wp(args.vs_jet_wp)
    variations.set_ff_type(args.ff_type)
    main(args)
