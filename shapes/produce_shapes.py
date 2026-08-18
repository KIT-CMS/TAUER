#!/usr/bin/env python
"""
Shape production for the TauKITFlow SM H→ττ analysis.

Background sample names and base event selections are sourced from
TauFakeFactors preselection configs via config/shapes/tff_adapter.
Signal samples are defined in config/samples.yaml (config.analysis.SIGNAL_SAMPLES).
"""
import argparse
import logging
import os
import pickle
from functools import partial
from itertools import combinations

import yaml

import shapes.selection.process_selection as selection
import shapes.selection.variations as variations
import shapes.utils as shape_utils
import common.ntuple_processor_config_helper as ntuple_processor_config_helper
from common.helper_collection import PreserveROOTPathsAsStrings
from config.logging_setup_configs import setup_logging
from shapes.selection.category_selection import categorization as default_categorization
from config.shapes.taues_measurement_binning import categorization as taues_categorization
import tau_es.energy_scales as tau_es_energy_scales
from shapes.selection.channel_selection import channel_selection
from config.shapes.control_binning import control_binning as default_control_binning
from config.analysis import (
    build_files_dict,
    masks_available,
    vs_ele_wp_for,
)
from ntuple_processor import GraphManager, RunManager, UnitManager



def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Produce shapes for the TauKITFlow SM H→ττ analysis."
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
        "--vs-ele-wp", required=False, default=None, type=str,
        help="Tau-vs-ele ID WP. Default: per-channel, matching smhtt_ul's Run3 "
             "configs (Tight for et, VVLoose otherwise) -- see "
             "config.analysis.vs_ele_wp_for(). Given a value, it is used for "
             "every channel instead.",
    )
    parser.add_argument(
        "--apply-tauid", action="store_true",
        help="Apply tau ID scale factors."
    )
    parser.add_argument(
        "--directory", required=True, type=str,
        help="Directory with CROWN ntuple outputs. With --xrootd, this must be the "
             "bare xrootd store path (e.g. /store/user/<user>/CROWN/ntuples/<tag>/CROWNRun/), "
             "NOT a full root://host/... URL -- ntuple_processor/booking.py's xrootd branch "
             "prepends the xrootd host itself, so a full URL here double-prefixes it and "
             "every dirlist() call silently fails with 'TypeError: NoneType object is not "
             "iterable'. See common/sample_paths.py's UlSamplePaths.ntuples for the exact "
             "convention (formerly utils/setup_ul_samples.sh's $NTUPLES; converted to Python "
             "in Phase 6d).",
    )
    parser.add_argument(
        "--selection-friend", default=None, type=str,
        help="Base directory of CROWN's selection-mask FRIEND trees for this ntuple tag "
             "(CROWN selection_friends.py output, e.g. "
             ".../CROWN/ntuples/<tag>/CROWNFriend/selection_<version>/). When given: (1) it "
             "is attached as an extra friend for every channel, alongside the xsec/FF "
             "friends; (2) the mask-based preselection (single `presel_mask > 0.5` cut, "
             "replacing the tau-ID/trigger/tau-pt/decay-mode/jet-veto cut strings) is used "
             "unconditionally instead of being merely probed for (see detect_masks()); (3) "
             "the shifted `presel_mask__<shift>` branches -- which live ONLY in this friend, "
             "not in the main ntuple -- are correctly picked up by the same per-shift "
             "quantity substitution (ReplaceVariable) used for every other CROWN quantity, "
             "matching smhtt_ul's per-shift cut substitution (see "
             "ntuple_processor/booking.py's get_quantities_per_variation, which scans "
             "attached friends for this). Leave unset for masks-in-the-ntuple or maskless "
             "productions -- masks-in-the-ntuple are still auto-detected without it "
             "(--force-legacy-cuts turns that off too, for both).",
    )
    parser.add_argument("--et-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--mt-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--tt-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--em-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--mm-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument("--ee-friend-directory", type=str, default=[], nargs="+")
    parser.add_argument(
        "--ff-friends-tag", type=str, default=[], nargs="+",
        help="CROWN friend TAG(s) that hold the FAKE-FACTOR friend trees, e.g. "
             "'fake_factors_260618_v5'. The tag is the directory right after "
             "CROWNFriends/CROWNMultiFriends in the friend path. Declaring it "
             "marks those friends as fake-factor friends, so they are dropped "
             "for signal samples no matter what the directory is called -- the "
             "role no longer has to be guessed from the name. The friend "
             "directories themselves are still passed through the usual "
             "--{channel}-friend-directory options. Several tags may be given "
             "(e.g. two FF versions); each friend is judged independently. "
             "Without this option the role falls back to inferring it from the "
             "tag name, so existing invocations keep working.",
    )
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
        "--validation-db-root", default="validation_database", type=str,
        help="Base directory for the on-disk validation_database/ cache "
             "(default: CWD-relative 'validation_database')."
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
        "--ff-only", action="store_true",
        help="Book ONLY the FF-weighted anti-iso variations (requires --ff-type != none); "
             "skip signals/same_sign/systematics entirely. For a fast follow-up run once FF "
             "friend trees exist, on top of an already-produced non-FF shapes file (same "
             "era/channels/validation-tag) -- see run.py's SHAPES ff qcd-label handling, "
             "which hadd's this output onto that earlier file instead of redoing it."
    )
    parser.add_argument(
        "--no-dnn-categorization", action="store_true",
        help="Produce shapes for variables in config/variables.yaml without DNN categorization (use when DNN friend trees are not available).",
    )
    parser.add_argument(
        "--force-legacy-cuts", action="store_true",
        help="Never use CROWN's precomputed selection-mask branches; always build the "
             "preselection as individual cut strings from config/cuts.yaml, even when "
             "`presel_mask` is present on the inputs. Escape hatch for A/B validation of "
             "the two paths (they must produce identical shapes) and for debugging a "
             "suspect mask. Without it, the mask path is chosen automatically per "
             "(era, channel) from the first input file -- old, maskless ntuples always "
             "fall back on their own.",
    )
    parser.add_argument(
        "--special-analysis", default=None, choices=[None, "TauES"],
        help="Produce shapes for a special analysis instead of the default categorization. "
             "'TauES' books additional per-shift embedded ('emb<shift>') datasets for the "
             "tau energy-scale fit (mt channel only, -12%% to +8%% in 0.2%% steps -- see "
             "tau_es/energy_scales.py; this help text previously said -2.5%%..+2.5%% in 0.1%% "
             "steps, which was a stale guess fixed in Phase 2a but never corrected here).",
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

def detect_masks(datasets, era, channel, force_legacy_cuts=False):
    """
    Decide once per (era, channel) whether to select on CROWN's precomputed
    selection masks or on the legacy cut strings.

    Only relevant for masks-in-the-ntuple productions: when --selection-friend
    is given, main() forces use_masks=True directly and this probe never runs
    (the friend is explicitly declared, there is nothing to detect).

    Probes the FIRST booked input file of the first dataset -- and, if that
    file has no masks, the FRIEND files booked next to it -- for the
    `presel_mask` branch (config.analysis.masks_available). CROWN writes the
    masks either into the ntuple (selection_config.py) or into a friend
    (selection_friends.py); the friends probed here are the very ones
    ntuple_processor is going to attach to this dataset (they come from the
    booked Ntuple objects, i.e. from --{channel}-friend-directory), so what is
    probed is exactly what the booked cuts will see. One probe per
    era/channel, not per file: a single CROWN production is homogeneous, and
    shape production books thousands of files whose paths are mostly remote --
    opening them all would cost more than the production it is meant to speed
    up.

    Fails safe in both directions: `--force-legacy-cuts` short-circuits to
    False, and masks_available() itself returns False (with a warning) for
    anything it cannot open or read, so an unexpected input degrades to the
    historical behaviour instead of crashing on a missing branch. That is also
    what makes Run2 2018 (whose ntuples predate the masks) and every
    pre-feature production keep working with no flag at all.
    """
    if force_legacy_cuts:
        logger.info(f"[{era}/{channel}] --force-legacy-cuts: selection via cut strings")
        return False

    probe = None
    tree = None
    friend_probes: list[str] = []
    for dataset in datasets.values():
        ntuples = getattr(dataset, "ntuples", None) or []
        if ntuples:
            probe = ntuples[0].path
            tree = ntuples[0].directory
            # `friends` is only set on Ntuple when friends were booked at all.
            friend_probes = [f.path for f in getattr(ntuples[0], "friends", None) or []]
            break
    if probe is None:
        logger.warning(
            f"[{era}/{channel}] no booked input files to probe for selection masks — "
            f"selection via cut strings"
        )
        return False

    use_masks = masks_available(probe, tree=tree or "ntuple", friend_dirs=friend_probes)
    logger.info(
        f"[{era}/{channel}] selection via "
        f"{'CROWN mask branches' if use_masks else 'legacy cut strings'} "
        f"(probed {probe}"
        f"{f' + {len(friend_probes)} friend(s)' if friend_probes else ''})"
    )
    return use_masks


def add_processes(add_fn, datasets, select_fn, channel):
    # Guard on dataset-key presence: eras that don't configure every process
    # group in config/samples.yaml (e.g. 2018, which currently only has
    # backgrounds + EMB for mt, no signals) simply skip that process instead
    # of KeyError-ing. Run3 eras are unaffected — every key below is always
    # present in their samples.yaml entries.
    def _add(name, key, selections_fn):
        dataset = datasets.get(key)
        if not dataset or not dataset.ntuples:
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
    # EW qqH is officially defined as VBF + hadronically-decaying-V associated
    # production merged together -- "EW qqH (VBF and qq -> V(->qq)H)" per the
    # LHCHWGFiducialAndSTXS twiki, true at every STXS stage (0, 1, 1.1, 1.2,
    # 1.3) -- while VH is leptonic-decay-only: "VH (qq+gg -> V(->leptons)H)".
    # So the WminusH/WplusH/ZH files (dataset key "VH") also contain events
    # that belong in the qqH shape (selection.qqH125's
    # HTXS_stage1_2_cat_pTjet30GeV 200-210 range cut picks these up, since
    # hadronic V(->qq)H falls in the same stage-1.2 "EW qqH" bins as genuine
    # VBF -- confirmed directly against htt_260813_22-23's WminusH ntuples:
    # 14850/22365 events land in 200-210, only 7515/22365 in VH's 300-505).
    # They're booked here as a *separate* process ("vh_as_qqh") rather than
    # merged into the "qqH" dataset itself, because CROWN only ever writes
    # "_qqH"-postfixed LHE scale/PDF/alphaS/PS branches into the actual VBF
    # ntuples -- the WminusH/WplusH/ZH ntuples carry "_VH"/"_ttH"-postfixed
    # branches instead (same "rem_htautau" CROWN sample type as ttH). A
    # single merged RDataFrame chain can't reference a column that's absent
    # from some of its files, so the "_qqH"-postfixed weight expressions used
    # to crash with "undeclared identifier" whenever the loop reached a
    # WminusH/WplusH/ZH file. do_estimations.py's qqH_merge_estimation sums
    # "qqh" + "vh_as_qqh" back into one physical qqH125 shape for the
    # datacard -- smhtt_ul skips this merge (it only ever books the plain
    # "qqh"/"vh" processes), which undercounts EW qqH relative to the
    # official STXS definition; TauKITFlow does the merge to match it.
    _add("vh_as_qqh", "VH", lambda: select_fn(selection.qqH125))


def get_select_function(channel_selection_obj, selection_kwargs, selection_memo):
    def _function(*args):
        _sel = [channel_selection_obj]
        for _proc in args:
            if _proc.__name__ not in selection_memo:
                selection_memo[_proc.__name__] = _proc(**selection_kwargs)
            _sel.append(selection_memo[_proc.__name__])
        return _sel
    return _function


def get_analysis_units(channel, era, datasets, categorization, apply_tauid, vs_jet_wp, vs_ele_wp, selection_option="CR", preselected=False, special=None, use_masks=False):
    _sel_kwargs = dict(
        channel=channel, era=era, special=special,
        vs_jet_wp=vs_jet_wp, vs_ele_wp=vs_ele_wp,
        selection_option=selection_option, apply_wps=apply_tauid,
        preselected=preselected, use_masks=use_masks,
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


def get_control_units(channel, era, datasets, variables, apply_tauid, vs_jet_wp, vs_ele_wp, selection_option="CR", do_gofs=False, do_2dGofs=False, preselected=False, use_masks=False):
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
        preselected=preselected, use_masks=use_masks,
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
    # Explicitly-declared fake-factor friends. They join the per-channel friend
    # lists of the FF-capable channels (so booking is byte-for-byte what
    # passing them via --{channel}-friend-directory did), and are handed to
    # shape_utils separately so filter_friends() knows their ROLE instead of
    # having to guess it from the directory name.
    ff_friends_tags = list(args.ff_friends_tag)
    if ff_friends_tags:
        logger.info(f"Fake-factor friend tags (declared): {ff_friends_tags}")
    # The selection-mask friend joins every channel's friend list exactly like
    # xsec/FF friends do (see friend_directories above) -- CROWN's
    # selection_friends.py production scopes to et/mt/tt/em (mm/ee never had a
    # preselection mask group to begin with), so nothing is appended for those.
    if args.selection_friend:
        for channel in ("et", "mt", "tt", "em"):
            friend_directories[channel] = [*friend_directories[channel], args.selection_friend]
        logger.info(f"Selection-mask friend (declared): {args.selection_friend}")
    output_file = args.output_file if ".root" in args.output_file else f"{args.output_file}.root"

    if args.ff_only and args.ff_type == "none":
        raise SystemExit("--ff-only requires --ff-type to be set (nothing to book otherwise).")

    files = build_files_dict(channels=args.channels, era=args.era)
    ntuple_directory = args.directory

    unit_manager = UnitManager()
    logger.info(f"Apply tau ID: {args.apply_tauid}")

    nominals = {args.era: {"datasets": {}, "units": {}}}

    for channel in args.channels:
        channel_vs_ele_wp = vs_ele_wp_for(channel, args.vs_ele_wp)
        nominals[args.era]["datasets"][channel] = shape_utils.get_nominal_datasets(
            era=args.era, channel=channel,
            friend_directories=friend_directories,
            ff_friends_tags=ff_friends_tags,
            files=files,
            directory=ntuple_directory,
            xrootd=args.xrootd,
            validation_tag=args.validation_tag,
            validation_db_root=args.validation_db_root,
        )
        common_kwargs = dict(
            era=args.era, channel=channel,
            datasets=nominals[args.era]["datasets"][channel],
            apply_tauid=args.apply_tauid,
            vs_jet_wp=args.vs_jet_wp,
            vs_ele_wp=channel_vs_ele_wp,
            selection_option=args.selection_option,
            # --selection-friend declares the mask friend explicitly -- force
            # the mask path on rather than merely probing for it (still the
            # right call even if --force-legacy-cuts is also passed for A/B
            # validation, hence the explicit override there too). Otherwise
            # fall back to auto-detection, for masks-in-the-ntuple productions
            # that never carry a separate selection friend. See detect_masks().
            use_masks=(
                False if args.force_legacy_cuts else
                True if args.selection_friend else
                detect_masks(
                    nominals[args.era]["datasets"][channel],
                    era=args.era, channel=channel,
                    force_legacy_cuts=args.force_legacy_cuts,
                )
            ),
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
            # Phase 6b: single-sourced from tau_es/energy_scales.py (was an
            # inline duplicate of shapes/do_estimations.py's identical list;
            # see that module's docstring for the full record). Verified
            # identical output to the pre-refactor inline comprehension.
            _es_shifts = tau_es_energy_scales.shift_values()
            shape_utils.add_tauES_datasets(
                era=args.era, channel=channel,
                friend_directories=friend_directories,
                ff_friends_tags=ff_friends_tags,
                files=files,
                directory=ntuple_directory, nominals=nominals,
                tauESvariations=_es_shifts,
                selections=[
                    channel_selection(
                        channel=channel, era=args.era, special="TauES",
                        vs_jet_wp=args.vs_jet_wp, vs_ele_wp=channel_vs_ele_wp,
                        selection_option=args.selection_option,
                    ),
                    selection.ZTT_embedded(
                        channel=channel, era=args.era,
                        apply_wps=args.apply_tauid, vs_jet_wp=args.vs_jet_wp,
                        vs_ele_wp=channel_vs_ele_wp,
                    ),
                ],
                categorization=taues_categorization,
                additional_emb_procS=additional_emb_procS,
                validation_tag=args.validation_tag,
                validation_db_root=args.validation_db_root,
                xrootd=args.xrootd,
            )
            nominals[args.era].setdefault("tauES_procS", {})[channel] = additional_emb_procS
        else:
            nominals[args.era]["units"][channel] = get_analysis_units(
                **common_kwargs, categorization=default_categorization,
            )

    procS = args.process_selection if args.process_selection is not None else {
        "data", "ztt", "zl", "zj", "ttt", "ttl", "ttj",
        "vvt", "vvl", "vvj", "w", "ggh", "qqh", "tth", "vh", "vh_as_qqh",
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
    sm_signalsS  = {"ggh", "qqh", "tth", "vh", "vh_as_qqh"} & procS
    signalsS     = sm_signalsS
    if (args.control_plots or args.gof_inputs) and not args.control_plots_full_samples:
        signalsS = signalsS & {"ggh", "qqh", "vh", "tth", "vh_as_qqh"}
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

    def _book_nonff(processes, vlist):
        # --ff-only: every FF-dependent _book() call in this loop is already
        # explicitly gated behind `if args.ff_type != "none":` (or a
        # channel-specific elif) in the code below -- so skipping every OTHER
        # (non-FF) _book() call via this wrapper, and leaving those existing
        # gated calls as plain _book(), is a complete and exact partition:
        # nothing FF-dependent is skipped, nothing FF-independent survives.
        if args.ff_only:
            return
        _book(processes, vlist)

    for channel in args.channels:
        if args.special_analysis == "TauES":
            # TauES fit inputs: nominal background/embedded shapes in the
            # tauES categorization, plus one embedded template per tau-ES
            # shift (booked via book_tauES_histograms below). The regular
            # systematic-variation stack below is not relevant to this mode.
            # Not FF-dependent (no ff_type branching anywhere in this special
            # analysis) -- --ff-only + --special-analysis TauES books nothing.
            _book_nonff(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesDS[channel], [variations.same_sign])
            if not args.ff_only:
                shape_utils.book_tauES_histograms(
                    manager=unit_manager,
                    additional_emb_procS=nominals[args.era]["tauES_procS"][channel],
                    datasets=nominals[args.era]["units"][channel],
                    variations=[variations.same_sign],
                    enable_check=args.enable_booking_check,
                )
            continue
        _book_nonff(signalsS, [])
        if channel in {"mt", "et", "tt"}:
            _book_nonff(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesDS[channel], [variations.same_sign])
        if channel in {"mt", "et"} and args.ff_type != "none":
            _book(embS | dataS | trueTauBkgS | leptonFakesS | jetFakesDS[channel], variations.SemiLeptonicFFEstimations.unrolled())
        elif channel == "tt" and args.ff_type != "none":
            _book(dataS | embS | trueTauBkgS | leptonFakesS | jetFakesDS[channel], variations.FullyHadronicFFEstimations.unrolled())
        elif channel == "em":
            _book_nonff((dataS | embS | simulatedProcsDS[channel]) - signalsS, [variations.same_sign_em])
        elif channel in {"mm", "ee"}:
            _book_nonff(procS, [variations.same_sign])
        if not args.skip_systematic_variations:
            _book_nonff({"ggh"} & procS, [variations.ggh_acceptance, variations.ggh_muRmuF_acceptance])
            _book_nonff({"qqh"} & procS, [variations.qqh_acceptance, variations.qqh_muRmuF_acceptance])
            # vh_as_qqh reads the same STXS-1.2 qqH categorization (QQH_WG1_Uncertainties
            # is booked by CROWN for "rem_htautau" too, so THU_qqH_* branches exist on
            # these files) but only "_VH"-postfixed LHE scale/PDF/alphaS branches exist
            # for it -- see vh_as_qqh_muRmuF_acceptance in variations.py.
            _book_nonff({"vh_as_qqh"} & procS, [variations.qqh_acceptance, variations.vh_as_qqh_muRmuF_acceptance])
            _book_nonff({"ggh"} & procS, variations.LHE_scale_ggH.unrolled())
            _book_nonff({"qqh"} & procS, variations.LHE_scale_qqH.unrolled())
            _book_nonff({"vh"} & procS, variations.LHE_scale_VH.unrolled())
            _book_nonff({"vh_as_qqh"} & procS, variations.LHE_scale_VH.unrolled())
            _book_nonff({"tth"} & procS, variations.LHE_scale_ttH.unrolled())
            _book_nonff({"ztt", "zj", "zl", "w"} & procS | signalsS, variations.recoil_resolution(args.era) + variations.recoil_response(args.era))
            _book_nonff(simulatedProcsDS[channel], variations.met_unclustered(args.era) + variations.pileup_reweighting(args.era))
            _jet_variations = variations.jet_energy_scale(args.era) + variations.jet_energy_resolution(args.era)
            if args.era in variations.BTAG_FIXEDWP_ERAS:
                _jet_variations += variations.btag_fixedWP(args.era)
            _book_nonff(simulatedProcsDS[channel], _jet_variations)
            if int(args.era[:4]) >= 2022:
                _book_nonff({"ztt", "zl", "zj"} & procS, variations.zpt(args.era))
            _book_nonff({"ttt", "ttl", "ttj"} & procS, [variations.top_pt])
            if channel in ["et", "mt", "tt"]:
                _book_nonff(jetFakesDS[channel], [variations.jet_to_tau_fake])
                _book_nonff((trueTauBkgS | leptonFakesS | signalsS) - {"zl"}, variations.tau_energy_scale(args.era))
                if channel == "mt":
                    _book_nonff(simulatedProcsDS[channel], variations.trigger_eff_mt(args.era))
                elif channel == "et":
                    _book_nonff(simulatedProcsDS[channel], variations.trigger_eff_et)
                elif channel == "tt":
                    _book_nonff(simulatedProcsDS[channel], variations.trigger_eff_tt)
            if channel in ["et", "mt"]:
                _book_nonff((trueTauBkgS | leptonFakesS | signalsS) - {"zl"}, variations.tau_id_eff_lt(args.era))
                _book_nonff(embS, [variations.emb_tau_id_eff_lt, variations.emb_tau_id_eff_lt_corr])
                if args.ff_type != "none":
                    _book(dataS | embS | leptonFakesS | trueTauBkgS, variations.FakeFactorLT.unrolled())
                    _book(leptonFakesS | trueTauBkgS | embS, [variations.ff_variations_tau_es_lt])
                    _book(embS, [variations.ff_variations_tau_es_emb_lt])
            if channel in ["et", "em"]:
                _book_nonff(simulatedProcsDS[channel], [variations.ele_es_res, variations.ele_es_scale])
                # CROWN only defines the embedding electron-ES shift for era < 2022
                # (tau_embedding_settings.py: "not yet measured for run 3") -- no
                # eleEsBarrel/eleEsEndcap branch exists in Run3 embedding ntuples.
                if int(args.era[:4]) < 2022:
                    _book_nonff(embS, [variations.emb_e_es])
            if channel == "mt":
                _book_nonff({"zl"} & procS, variations.mu_fake_es_inc(args.era))
                # No embedding booking here: CROWN never produces a muon-fake-ES
                # branch for embedding samples (the MC genMuon/DM-split shifts in
                # analysis_configurations/tau/variations.py explicitly
                # exclude_samples=["data","embedding","embedding_mc"], and
                # tau_embedding_settings.py defines no muon-fake-ES shift at all)
                # -- variations.emb_mu_fake_es_inc/emb_mu_fake_es_inc_corr were
                # referenced here but never defined anywhere in variations.py.
                if args.ff_type != "none":
                    _book(dataS | embS | leptonFakesS | trueTauBkgS, variations.FakeFactorLT.unrolled())
                    _book(leptonFakesS | trueTauBkgS | embS, [variations.ff_variations_tau_es_lt])
                    _book(embS, [variations.ff_variations_tau_es_emb_lt])
            if channel == "tt":
                _book_nonff((trueTauBkgS | leptonFakesS | signalsS) - {"zl"}, variations.tau_energy_scale(args.era))
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
    # Self-nice regardless of how this got invoked (run.py already wraps it in
    # `nice -n 19`, but this covers direct invocation too -- e.g. the 2018/Run2
    # path documented in the README, which calls this script directly). Safe
    # to call even when already niced (os.nice() clamps at the max of 19).
    os.nice(19)
    args = parse_arguments()
    log_file = args.output_file.replace(".root", ".log") if ".root" in args.output_file else f"{args.output_file}.log"
    logger = setup_logging(logger=logging.getLogger(__name__))
    variations.set_jet_wp(args.vs_jet_wp)
    variations.set_ff_type(args.ff_type)
    main(args)
