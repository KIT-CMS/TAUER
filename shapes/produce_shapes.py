#!/usr/bin/env python
import argparse
import logging
import os
import pickle
from functools import partial
from itertools import combinations

import yaml

import importlib

import shapes.selection.process_selection as selection
import shapes.selection.systematics as selection_systematics
import shapes.utils as shape_utils
from analyses.smhtt.common import stxs_tools
import common.booking as booking
from common.booking import PreserveROOTPathsAsStrings
from CustomLogging import setup_logging
from common.analysis import ACTIVE_ANALYSIS

analysis_selection = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.shapes.selection.process_selection")
analysis_selection_systematics = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.shapes.selection.systematics")
default_categorization = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.shapes.selection.category_selection").categorization
from tau_es.taues_categories import categorization as taues_categorization
from shapes.special.ttbar_dy_weight_categories import categorization as ttbar_dy_weight_categorization
from shapes.special.njets_control_categories import categorization as njets_control_categorization
from shapes.special.trigger_region_categories import categorization as trigger_region_categorization
from shapes.special.njets_control_categories import _variables_for as control_variables
import tau_es.energy_scales as tau_es_energy_scales
from shapes.selection.channel_selection import channel_selection
from common.binning import control_binning as default_control_binning
from common.sample_paths import build_selection_friend_dir, parse_ntuple_directory
from common.analysis import RUN3_ERAS, build_files_dict, get_mc_ntuple_era, mc_lumi_scale
from common.systematics import systematics
from common.analysis import BACKGROUNDS, GROUPS, SIGNAL_DATASETS, expand
from ntuple_processor import GraphManager, RunManager, UnitManager
from ntuple_processor.utils import Selection


def parse_arguments():
    parser = argparse.ArgumentParser(description="Produce shapes.")
    parser.add_argument("--era", required=True, type=str, help="Experiment era.")
    parser.add_argument(
        "--channels", default=[],
        type=lambda channellist: [channel for channel in channellist.split(",")],
        help="Channels to be considered, separated by a comma without space",
    )
    parser.add_argument("--apply-tauid", action="store_true", help="Apply tau ID scale factors.")
    parser.add_argument(
        "--directory", required=True, type=str,
        help="Directory with CROWN ntuple outputs. With --xrootd, the bare xrootd store "
             "path (e.g. /store/user/<user>/CROWN/ntuples/<tag>/CROWNRun/), not a full "
             "root://host/... URL -- see common.sample_paths.UlSamplePaths.ntuples.",
    )
    parser.add_argument(
        "--selection-friend", required=True, type=str,
        help="CROWN shapes_preparation FRIEND tree version tag, e.g. 'shapes_preparation_260930' "
             "-- just the last path component. Resolved via "
             "common.sample_paths.build_selection_friend_dir(ntupletag, tag). A value "
             "containing '/' is used as-is (a full directory). Required: this friend "
             "supplies the SR_mask/SR_mask_ss/presel_mask branches, gen_category_{T,J,L}, "
             "the fused per-event `weight`, and the fake-factor region masks that "
             "channel_selection()/process_selection() build on.",
    )
    parser.add_argument("--et-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--mt-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--tt-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--em-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--mm-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--ee-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--output-file", required=True, type=str, help="Output ROOT file.")
    parser.add_argument(
        "--process-selection", default=None,
        type=lambda proclist: set([process for process in proclist.split(",")]),
        help="Comma-separated list of processes to produce shapes for.",
    )
    parser.add_argument(
        "--stxs-stage", default="stage0", choices=["stage0", "stage1p2"],
        help="Signal split: per production mode (stage0) or per recommended <PROCESS>_<STXS_BIN> of STXS stage 1.2 (stage1p2).",
    )
    parser.add_argument("--control-plots", action="store_true", help="Produce shapes for control plots.")
    parser.add_argument(
        "--control-plot-set", default=["m_vis"], nargs="+", type=str,
        help="Set of variables for control plots.",
    )
    parser.add_argument("--gof-inputs", action="store_true", help="Produce shapes for goodness-of-fit tests.")
    parser.add_argument("--do-2d-gofs", action="store_true", help="Produce 2D GoF shapes.")
    parser.add_argument(
        "--control-plots-full-samples", action="store_true",
        help="Use all signal processes for control plots.",
    )
    parser.add_argument(
        "--skip-systematics", action="store_true",
        help="Skip systematics (faster, nominal shapes only).",
    )
    parser.add_argument("--nprocs", dest="num_processes", default=1, type=int, help="Number of parallel processes for histogram production.")
    parser.add_argument("--nthreads", dest="num_threads", default=1, type=int, help="Number of threads per process.")
    parser.add_argument("--optimization-level", default=2, type=int, help="Graph optimization level (0-2).")
    parser.add_argument(
        "--only-create-graphs", action="store_true",
        help="Only create and serialize the computation graphs, do not run.",
    )
    parser.add_argument("--graph-dir", default=None, type=str, help="Directory to write the serialized graph files.")
    parser.add_argument(
        "--collect-config-only", action="store_true",
        help="Only collect cuts/weights/datasets/systematics into a YAML file.",
    )
    parser.add_argument("--config-output-file", default="tmp_config.yaml", type=str, help="YAML output file for --collect-config-only.")
    parser.add_argument("--enable-booking-check", action="store_true", help="Enable double-booking check (slow).")
    parser.add_argument("--xrootd", action="store_true", help="Read input ntuples via xrootd.")
    parser.add_argument("--validation-tag", default="default", type=str, help="Tag used for sample validation.")
    parser.add_argument(
        "--validation-db-root", default="validation_database", type=str,
        help="Base directory for the on-disk validation_database/ cache.",
    )
    parser.add_argument(
        "--ff-type", choices=["none", "fake_factor", "ml_fake_factor"], default="none",
        help="Set to 'fake_factor' to book the anti-iso regions weighted with CROWN's ff_weight and their systematics; "
             "'ml_fake_factor' for friends made with the machine-learned fake factors (their systematics are booked).",
    )
    parser.add_argument(
        "--ff-only", action="store_true",
        help="Book only the FF-weighted anti-iso systematics (requires --ff-type != none); "
             "skip signals/same_sign/systematics. For hadd'ing onto an already-produced "
             "non-FF shapes file, see run.py's SHAPES ff qcd-label handling.",
    )
    parser.add_argument(
        "--no-dnn-categorization", action="store_true",
        help="Produce shapes for variables in common/variables.yaml without DNN categorization (use when DNN friend trees are not available).",
    )
    parser.add_argument(
        "--special-analysis", default=None,
        choices=[None, "TauES", "TTbarDYWeight", "NjetsControl", "TriggerRegions", "AntiIsoTauSF"],
        help="Produce shapes for a special analysis instead of the default categorization. "
             "'TauES': mt-only tau energy-scale fit inputs (per-shift embedded datasets, "
             "tau_es/energy_scales.py). 'TTbarDYWeight': em-only nbtag x m_vis-Z-peak 2x2 "
             "categorization (shapes/special/ttbar_dy_weight_categories.py) for the ttbar/DY "
             "normalization measurement. 'NjetsControl': njets==0/==1/>=2 categorization "
             "over the control-plot variable set, all channels. 'TriggerRegions': et/mt/tt "
             "trg_cross/trg_single offline-pt categorization (shapes/special/trigger_region_categories.py), Run 3 only. "
             "'AntiIsoTauSF': et/mt/tt control variables in the anti-isolated region (<ch>_ar) without fake factors, "
             "MC also as <proc>_noVsJetSF without the Medium vsJet SF, Run 3 only.",
    )
    return parser.parse_args()


def load_variables_from_config(channel):
    _yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common", "variables.yaml")
    with open(_yaml_path) as _f:
        _cfg = yaml.safe_load(_f)
    _output_features = _cfg.get("output_features", [])
    _available = set(default_control_binning.get(channel, {}).keys())
    _filtered = [v for v in _output_features if v in _available]
    if not _filtered:
        raise ValueError(f"No variables from common/variables.yaml are available in control_binning for channel {channel}. Available: {_available}. From YAML: {_output_features}")
    logger.info(f"Loaded {len(_filtered)} variables from common/variables.yaml for channel {channel}")
    return _filtered


# process name -> ntuple_processor dataset keys
PROCESS_DATASET_KEYS = {"data": ("data",), **{k: (p.dataset,) for k, p in BACKGROUNDS.items()}, **SIGNAL_DATASETS}

SIGNAL_PROCESSES = set(SIGNAL_DATASETS)


def signal_unit_names(stxs_stage, keys):
    """Names of the booked signal units belonging to the given process keys."""
    return {unit for unit, info in stxs_tools.signal_units(stxs_stage).items() if info["key"] in keys}


def add_processes(add_fn, datasets, select_fn, channel, stxs_stage="stage0"):
    # Guard on dataset-key presence
    def _add(name, selections_fn):
        dataset = datasets.get(PROCESS_DATASET_KEYS[name][0])
        if not dataset or not dataset.ntuples:
            return
        add_fn(name=name, dataset=dataset, selections=selections_fn())

    _add("data", select_fn)
    _add("ztt",  lambda: select_fn(selection.ZTT))
    _add("zl",   lambda: select_fn(selection.ZL))
    _add("zj",   lambda: select_fn(selection.ZJ))
    _add("ttt",  lambda: select_fn(selection.TTT))
    _add("ttl",  lambda: select_fn(selection.TTL))
    _add("ttj",  lambda: select_fn(selection.TTJ))
    _add("vvt",  lambda: select_fn(selection.VVT))
    _add("vvl",  lambda: select_fn(selection.VVL))
    _add("vvj",  lambda: select_fn(selection.VVJ))
    _add("w",    lambda: select_fn(selection.W))
    _add("emb",  lambda: select_fn(selection.ZTT_embedded))
    for unit, info in stxs_tools.signal_units(stxs_stage).items():
        dataset = shape_utils.combine_datasets([datasets.get(key) for key in info["datasets"]])
        if dataset:
            add_fn(name=unit, dataset=dataset, selections=select_fn(analysis_selection.signal_selection(stxs_stage, unit)))


def get_select_function(channel_selection_obj, selection_kwargs, selection_memo):
    def _function(*args):
        _sel = [channel_selection_obj]
        for _proc in args:
            if _proc.__name__ not in selection_memo:
                selection_memo[_proc.__name__] = _proc(**selection_kwargs)
            _sel.append(selection_memo[_proc.__name__])
        # MC normalized to this run's data, e.g. 2026 alone with the 2025(+2026) MC
        if args and (scale := mc_lumi_scale(selection_kwargs["era"])) != 1:
            _sel.append(Selection(name="mc_lumi_scale", weights=[(f"{scale:.9g}", "mc_lumi_scale")]))
        return _sel
    return _function


def get_analysis_units(channel, era, datasets, categorization, apply_tauid, special=None, stxs_stage="stage0"):
    _sel_kwargs = dict(
        channel=channel, era=era, special=special,
        apply_wps=apply_tauid,
    )
    _memo = {}
    _ch_sel = channel_selection(**_sel_kwargs)
    _select = get_select_function(_ch_sel, _sel_kwargs, _memo)
    units = {}
    add_processes(
        add_fn=partial(shape_utils.add_process, analysis_unit=units, categorization=categorization, channel=channel),
        datasets=datasets, select_fn=_select, channel=channel, stxs_stage=stxs_stage,
    )
    return units


def get_control_units(channel, era, datasets, variables, apply_tauid, do_gofs=False, do_2dGofs=False, stxs_stage="stage0"):
    control_units = {}
    control_binning = default_control_binning
    if do_gofs:
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
        apply_wps=apply_tauid,
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
        datasets=datasets, select_fn=_select, channel=channel, stxs_stage=stxs_stage,
    )
    return control_units


def collect_config(graphs, era, channel, filename, processes):
    r_manager = RunManager(graphs, create_histograms=False, create_config=True)
    r_manager.nthreads = 1
    for _graph in graphs:
        logger.info(f"Creating config for graph {_graph.name}")
        r_manager.config_formatter = booking.get_config_formatter(era=era, graph=_graph, processes=processes)
        r_manager.node_to_root(_graph)
        booking.add_paths(graph=_graph, channel=channel, era=era, r_manager=r_manager)
    _path, _basename = os.path.split(filename)
    _path = os.path.join(_path, f"{era}__{channel}__{_basename}")
    with open(_path, "w") as config_file:
        yaml.dump(r_manager.config.regular, config_file, default_flow_style=False, Dumper=PreserveROOTPathsAsStrings)
    logger.info(f"Configuration written to {_path}")


def main(args):
    friend_directories = {
        "et": args.et_friend_directory,
        "mt": args.mt_friend_directory,
        "tt": args.tt_friend_directory,
        "em": args.em_friend_directory,
        "mm": args.mm_friend_directory,
        "ee": args.ee_friend_directory,
    }
    # CROWN's shapes_preparation friend scopes to et/mt/tt/em (mm/ee have no mask group).
    if "/" in args.selection_friend:
        selection_friend_dir = args.selection_friend
    else:
        _user, _ntupletag = parse_ntuple_directory(args.directory)
        selection_friend_dir = build_selection_friend_dir(_ntupletag, args.selection_friend, user=_user)
    for channel in ("et", "mt", "tt", "em"):
        friend_directories[channel] = [*friend_directories[channel], selection_friend_dir]
    logger.info(f"Selection friend: {selection_friend_dir}")
    output_file = args.output_file if ".root" in args.output_file else f"{args.output_file}.root"

    if args.ff_only and args.ff_type == "none":
        raise SystemExit("--ff-only requires --ff-type to be set (nothing to book otherwise).")

    files = build_files_dict(channels=args.channels, era=args.era)
    ntuple_directory = args.directory

    unit_manager = UnitManager()
    logger.info(f"Apply tau ID: {args.apply_tauid}")

    nominals = {args.era: {"datasets": {}, "units": {}}}

    procS = args.process_selection if args.process_selection is not None else {
        "data", "ztt", "zl", "zj", "ttt", "ttl", "ttj",
        "vvt", "vvl", "vvj", "w", "ggh", "qqh", "tth", "vh",
    }
    # Restrict validation to the dataset keys procS actually needs -- every other key gets
    # a full xrootd validation pass in get_nominal_datasets() and is then thrown away.
    needed_keys = {key for p in procS if p in PROCESS_DATASET_KEYS for key in PROCESS_DATASET_KEYS[p]}
    validation_files = {
        args.era: {
            channel: {k: v for k, v in files[args.era][channel].items() if k in needed_keys}
            for channel in files[args.era]
        }
    }

    for channel in args.channels:
        nominals[args.era]["datasets"][channel] = shape_utils.get_nominal_datasets(
            era=args.era, channel=channel,
            friend_directories=friend_directories,
            files=validation_files,
            directory=ntuple_directory,
            xrootd=args.xrootd,
            validation_tag=args.validation_tag,
            validation_db_root=args.validation_db_root,
        )
        common_kwargs = dict(
            era=args.era, channel=channel,
            datasets=nominals[args.era]["datasets"][channel],
            apply_tauid=args.apply_tauid,
            stxs_stage=args.stxs_stage,
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
        elif args.no_dnn_categorization and args.special_analysis is None:
            _vars = load_variables_from_config(channel)
            if not _vars:
                logger.warning(f"[no-dnn-categorization] No variables loaded for {channel}, using default set")
                _vars = ["m_vis", "pt_1", "pt_2", "eta_1", "eta_2", "mt_1", "mt_2", "mjj", "puppimet", "mt_tot", "pt_tt", "pt_vis", "nbtag", "njets"]
                _available = set(default_control_binning.get(channel, {}).keys())
                _vars = [v for v in _vars if v in _available]
                logger.info(f"[no-dnn-categorization] Using fallback variables for {channel}: {_vars}")
            else:
                logger.info(f"[no-dnn-categorization] Using variables for {channel}: {_vars}")
            nominals[args.era]["units"][channel] = get_control_units(**common_kwargs, variables=_vars)
        elif args.special_analysis == "TauES":
            if channel != "mt":
                raise ValueError(f"--special-analysis TauES is only implemented for the mt channel; got channel={channel!r}.")
            nominals[args.era]["units"][channel] = get_analysis_units(
                **common_kwargs, categorization=taues_categorization, special="TauES",
            )
            additional_emb_procS = set()
            _es_shifts = tau_es_energy_scales.shift_values()
            shape_utils.add_tauES_datasets(
                era=args.era, channel=channel,
                friend_directories=friend_directories,
                files=files,
                directory=ntuple_directory, nominals=nominals,
                tauESshifts=_es_shifts,
                selections=[
                    channel_selection(
                        channel=channel, era=args.era, special="TauES",
                    ),
                    selection.ZTT_embedded(
                        channel=channel, era=args.era,
                        apply_wps=args.apply_tauid,
                    ),
                ],
                categorization=taues_categorization,
                additional_emb_procS=additional_emb_procS,
                validation_tag=args.validation_tag,
                validation_db_root=args.validation_db_root,
                xrootd=args.xrootd,
            )
            nominals[args.era].setdefault("tauES_procS", {})[channel] = additional_emb_procS
        elif args.special_analysis == "TTbarDYWeight":
            if channel != "em":
                raise ValueError(f"--special-analysis TTbarDYWeight is only implemented for the em channel; got channel={channel!r}.")
            nominals[args.era]["units"][channel] = get_analysis_units(**common_kwargs, categorization=ttbar_dy_weight_categorization)
        elif args.special_analysis == "NjetsControl":
            nominals[args.era]["units"][channel] = get_analysis_units(**common_kwargs, categorization=njets_control_categorization)
        elif args.special_analysis == "TriggerRegions":
            if channel not in ("et", "mt", "tt"):
                raise ValueError(f"--special-analysis TriggerRegions is only implemented for et/mt/tt; got channel={channel!r}.")
            nominals[args.era]["units"][channel] = get_analysis_units(**common_kwargs, categorization=trigger_region_categorization(args.era))
        elif args.special_analysis == "AntiIsoTauSF":
            if channel not in ("et", "mt", "tt") or args.era not in RUN3_ERAS or args.ff_only:
                raise ValueError(f"--special-analysis AntiIsoTauSF is only implemented for et/mt/tt in Run 3 and not with --ff-only; got {args.era} {channel}.")
            nominals[args.era]["units"][channel] = get_control_units(**common_kwargs, variables=control_variables(channel))
        else:
            nominals[args.era]["units"][channel] = get_analysis_units(**common_kwargs, categorization=default_categorization)

    dataS = {"data"} & procS
    embS = {"emb"} & procS
    jetFakesS = set(GROUPS["jet_fake"]) & procS
    leptonFakesS = set(GROUPS["lep_fake"]) & procS
    trueTauBkgS = set(GROUPS["real_tau"]) & procS
    signalsS = signal_unit_names(args.stxs_stage, set(SIGNAL_DATASETS) & procS)
    simulatedProcsS = jetFakesS | leptonFakesS | trueTauBkgS | signalsS
    logger.info(f"Processes: {procS}")

    # CROWN's era-tagged shift names are MC-only and baked in at the physical CROWN
    # production era -- for eras that borrow their MC from another era, mc_era differs
    # from args.era (see common.analysis.MC_NTUPLE_ERA_OVERRIDE).
    mc_era = get_mc_ntuple_era(args.era)

    def _book(processes, vlist):
        shape_utils.book_histograms(
            processes=processes, systematics=vlist,
            manager=unit_manager,
            datasets=nominals[args.era]["units"][channel],
            enable_check=args.enable_booking_check,
        )

    def _book_nonff(processes, vlist):
        if args.ff_only:
            return
        _book(processes, vlist)

    def _book_qcd(processes, vlist):
        # register_raw=False: only the region/shift copies are booked, the raw units are the nominal ones booked above
        shape_utils.book_histograms(
            processes=processes, systematics=vlist,
            manager=unit_manager,
            datasets=nominals[args.era]["units"][channel],
            enable_check=args.enable_booking_check,
            register_raw=False,
        )

    def _book_qcd_ss(processes):
        _book_qcd(processes, [selection_systematics.same_sign])

    def _book_qcd_ss_nonff(processes):
        if args.ff_only:
            return
        _book_qcd_ss(processes)

    for channel in args.channels:
        if args.special_analysis == "TauES":
            _book_qcd_ss_nonff(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesS)
            if not args.ff_only:
                shape_utils.book_tauES_histograms(
                    manager=unit_manager,
                    additional_emb_procS=nominals[args.era]["tauES_procS"][channel],
                    datasets=nominals[args.era]["units"][channel],
                    systematics=[selection_systematics.same_sign],
                    enable_check=args.enable_booking_check,
                )
            continue
        if args.special_analysis == "AntiIsoTauSF":
            _book_qcd(procS, [selection_systematics.anti_iso_no_ff])
            _book_qcd(simulatedProcsS, [selection_systematics.anti_iso_no_vsjet_sf(channel)])
            continue
        _book_nonff(signalsS, [])
        # Unconditional OS/signal-region nominal for every non-signal process
        _book_nonff(procS - signalsS, [])
        if channel in {"mt", "et", "tt"}:
            _book_qcd_ss_nonff(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesS)
        if channel in {"mt", "et", "tt"} and args.ff_type != "none":
            _book_qcd(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesS, [selection_systematics.anti_iso])
        elif channel == "em":
            _book_qcd_ss_nonff((dataS | embS | simulatedProcsS) - signalsS)
        elif channel in {"mm", "ee"}:
            _book_qcd_ss_nonff(procS)
        if not args.skip_systematics:
            for unit, unit_systematics in analysis_selection_systematics.signal_systematics(args.stxs_stage).items():
                if unit in signalsS and unit_systematics:
                    _book_nonff({unit}, unit_systematics)
            use_ff = channel in {"mt", "et", "tt"} and args.ff_type != "none"
            for syst in systematics(mc_era, jetfakes=use_ff, ff_ml=args.ff_type.startswith("ml_")):
                if syst.kind != "shape" or channel not in syst.channels or syst.source == "estimation":
                    continue
                keys = expand(syst.processes)
                if syst.source != "ff":
                    _book_nonff(set(keys) & procS | (signalsS if "signal" in keys else set()), selection_systematics.shape_systematics(syst))
                if use_ff and "jetFakes" in keys:
                    # the fake factor shifts act on data too, the CROWN shifts only on the subtracted MC
                    subtracted = (dataS | embS if syst.source == "ff" else set()) | (set(GROUPS["ff_subtraction"]) & procS)
                    _book_qcd(subtracted, selection_systematics.anti_iso_systematics(syst))
            if channel in ["et", "mt"]:
                _book_nonff(embS, [selection_systematics.emb_tau_id_eff_lt, selection_systematics.emb_tau_id_eff_lt_corr])
            if channel in ["et", "em"] and int(args.era[:4]) < 2022:
                _book_nonff(embS, [selection_systematics.emb_e_es])

    g_manager = GraphManager(unit_manager.booked_units, True)
    g_manager.optimize(args.optimization_level)
    graphs = g_manager.graphs
    for graph in graphs:
        print(f"{graph}")

    if args.collect_config_only:
        if len(args.channels) > 1:
            raise NotImplementedError("Config collection for multiple channels is not yet supported.")
        collect_config(
            graphs=graphs, era=args.era, channel=args.channels[0], filename=args.config_output_file,
            processes={unit.path.split("/")[-1] for unit in unit_manager.booked_units},
        )
        logging.shutdown()
        os._exit(0)  # the ROOT/xrootd teardown hangs after the config is written

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
    os.nice(19)
    args = parse_arguments()
    logger = setup_logging(logger=logging.getLogger(__name__))
    main(args)
