#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
from utils.environment import pythonpath_with_tff, run_in_conda  # noqa: E402
from common.analysis import ACTIVE_ANALYSIS, ff_config_era  # noqa: E402

MODES = [
    "SHAPES",
    "PLOT",
    "TRAIN-SHAPES",
    "CONFIGS",
    "GEN-TFF-CONFIGS",
    "FF",
    "FF-CORR",
    "FF-MEASURE",
    "BTAG",
    "TRAIN",
    "TRAIN-DATASET",
]

FF_MEASURE_STEPS = ["gen-configs", "presel", "ff", "ff-corr"]
BTAG_DEFAULT_STEPS = ["presel", "calc"]

# Caps preselection.py's nested multiprocessing pools (unbounded by default -> OOMs
# condor jobs); outer=2 x inner=6 <= 12 concurrent RDataFrame workers.
_PRESEL_OUTER_WORKERS = "2"
_PRESEL_INNER_WORKERS = "6"

HELP_EPILOG = """
Full flag/env-var reference: README.md's "Flag / environment-variable
reference" table. Every flag has an env-var fallback (same name, upper-cased);
--flag wins, then the env var, then a hardcoded default. Unrecognized
arguments pass straight through to the underlying python script.
"""


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="TAUER -- SM H->tautau analysis framework",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", dest="mode_flag", default=None)
    parser.add_argument("--era", default=None)
    parser.add_argument("--channels", dest="channels", default=None)
    parser.add_argument("--ntupletag", default=None)
    parser.add_argument(
        "--tag", default=None,
        help="Label scoping the outputs of a run (default: --ntupletag): shapes output subdirectory, "
             "FF-MEASURE workdir name, BTAG workdir nesting, TRAIN law version. Env: TAG.",
    )
    parser.add_argument("--stxs-stage", dest="stxs_stage", default=None, choices=["stage0", "stage1p2"])
    parser.add_argument("--nthreads", default=None)
    parser.add_argument("--nprocs", default=None)
    parser.add_argument("--output-dir", dest="output_dir", default=None)
    parser.add_argument(
        "--ff-type", dest="ff_type", default=None, choices=["fake_factor", "ml_fake_factor"],
        help="Fake factor flavour of --ff-friend; ml_fake_factor books the machine-learned fake factor systematics. Env: FF_TYPE.",
    )
    parser.add_argument(
        "--ff-friend", dest="ff_friend", default=None,
        help="CROWN fake-factor FRIEND tree version tag, e.g. 'ff_260903'. Env: FF_FRIENDS_DIR. "
             "See README's flag reference.",
    )
    parser.add_argument(
        "--additional-friends", dest="additional_friends", default=None,
        help="Comma-separated extra CROWN FRIEND tree version tags/paths. Env: "
             "ADDITIONAL_FRIENDS_DIR. See README's flag reference.",
    )
    parser.add_argument("--ff-config", dest="ff_config", default=None)
    parser.add_argument("--ff-corr-config", dest="ff_corr_config", default=None)
    parser.add_argument(
        "--selection-friend", dest="selection_friend", default=None,
        help="CROWN selection-mask FRIEND tree version tag, e.g. 'selection_260817'. Env: "
             "SELECTION_FRIEND_DIR. See README's flag reference.",
    )
    parser.add_argument(
        "--ff-input-dir", dest="ff_input_dir", default=None,
        help="FF/FF-CORR: point at any preselection-shaped directory instead of TauFakeFactors' "
             "own preselection.py output.",
    )
    parser.add_argument(
        "--steps", dest="steps", default=None,
        help="FF-MEASURE: comma-separated subset/order of gen-configs,presel,ff,ff-corr (default: all four). "
             "BTAG: subset/order of gen-configs,presel,calc (default: presel,calc).",
    )
    parser.add_argument(
        "--use-cached-intermediary-steps", dest="use_cached_intermediary_steps",
        action="store_true", default=False,
        help="FF-MEASURE only: let ff/ff-corr reuse fake_factors/.RDF_CACHE. Off by default -- "
             "see README's flag reference for why.",
    )
    parser.add_argument(
        "--user", dest="user", default=None,
        help="Grid storage username for the --ntupletag-derived ntuple and output paths "
             "(default: getpass.getuser()). Condor callers must pass this explicitly.",
    )
    parser.add_argument(
        "--correction-tag", dest="correction_tag", default=None,
        help="FF-MEASURE only: override corrections_{channel}.yaml's correction_tag (nests "
             "the ff-corr step's output under an extra level, see ff_corrections.py). Env: "
             "CORRECTION_TAG.",
    )
    parser.add_argument("--train-task", dest="train_task", default=None, help="TRAIN only: law task name (default: RunAllCENNTConfusionMatrixWorkflow). Env: TRAIN_TASK.")
    parser.add_argument("--cuda-device", dest="cuda_device", default=None, help="TRAIN only: GPU device IDs (default: 0,1). Env: CUDA_DEVICE.")
    parser.add_argument("--workers", dest="workers", default=None, help="TRAIN only: law workers (default: 2). Env: WORKERS.")
    parser.add_argument(
        "--train-config", dest="train_config", default=None,
        help="TRAIN-DATASET only: a single, already-built create_training_dataset.py --config "
             "YAML. Env: TRAIN_CONFIG. Mutually exclusive with --train-configs-dir.",
    )
    parser.add_argument(
        "--train-configs-dir", dest="train_configs_dir", default=None,
        help="TRAIN-DATASET only: directory of {era}__{channel}__config.yaml files (from "
             "run.py CONFIGS / condor/submit_train_configs.py) to glob, filter by --channels/"
             "--train-eras, and merge across eras via trainings/adjust_config.py (default: derived "
             "from --ntupletag). Env: TRAIN_CONFIGS_DIR.",
    )
    parser.add_argument(
        "--train-eras", dest="train_eras", default=None,
        help="TRAIN-DATASET only: comma-separated eras to pull out of --train-configs-dir "
             "(default: every era present there). Env: TRAIN_ERAS.",
    )
    parser.add_argument(
        "--base-dataset-dir", dest="base_dataset_dir", default=None,
        help="TRAIN-DATASET/TRAIN: directory of the feather folds (default: derived from --ntupletag, "
             "see common.sample_paths.build_shape_output_paths). Env: BASE_DATASET_DIR.",
    )
    parser.add_argument(
        "--train-output-dir", dest="train_output_dir", default=None,
        help="TRAIN only: law output directory of the models (default: models/ next to the datasets on /ceph). Env: TRAIN_OUTPUT_DIR.",
    )
    parser.add_argument(
        "--common-setup-config", dest="common_setup_config", default=None,
        help="TRAIN-DATASET only: trainings/create_training_dataset.py's --common-setup-config "
             "(default when merging via --train-configs-dir: common/training_setup.yaml). Env: "
             "COMMON_SETUP_CONFIG.",
    )
    return parser


def parse_args(argv=None):
    # MODE is peeled off manually, not via an argparse positional -- a still-unfilled
    # positional could grab an unrelated later token (e.g. a --steps value) as MODE.
    argv = list(sys.argv[1:] if argv is None else argv)
    mode_positional = None
    if argv and not argv[0].startswith("-"):
        mode_positional = argv.pop(0)
    parser = make_parser()
    args, extra = parser.parse_known_args(argv)
    args.mode_positional = mode_positional
    return args, extra


def env_or(value, env_name, default):
    if value is not None:
        return value
    return os.environ.get(env_name, default)


def run_plain(cmd_args, cwd=None, env_overrides=None):
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["nice", "-n", "19", *cmd_args], cwd=str(cwd or REPO_ROOT), env=env)


def run_conda(cmd_args, env_overrides=None, conda_env=None):
    kwargs = {"cwd": REPO_ROOT, "env_overrides": env_overrides, "check": False}
    if conda_env:
        kwargs["conda_env"] = conda_env
    return run_in_conda(["nice", "-n", "19", *cmd_args], **kwargs)


def resolve_friend(ntupletag, tag_or_path, user=None):
    """Resolve a bare CROWN FRIEND tree VERSION TAG (e.g. "ff_260903") to its full
    directory via common.sample_paths.build_friend_dir(); a value containing '/' is
    used as a full path as-is (old calling convention). Mirrors
    condor/submit_shapes.py's own resolve_friend() closure."""
    from common.sample_paths import build_friend_dir

    return tag_or_path if "/" in tag_or_path else build_friend_dir(ntupletag, tag_or_path, user=user)


def friend_directory_args(ff_friends_dir="", additional_friend_dirs=()):
    """Friend-directory arguments for shapes/produce_shapes.py. All dirs a channel needs go
    into one --{channel}-friend-directory occurrence (nargs="+", not action="append" --
    a second occurrence would replace the first). additional_friend_dirs: every channel.
    ff_friends_dir: et/mt/tt only (em has no fake factors). Selection-mask friends are NOT handled here --
    see produce_shapes.py's own --selection-friend, which also flips on mask-based preselection, not just
    attaches a friend."""
    friend_dirs = {ch: [] for ch in ("et", "mt", "tt", "em")}
    if ff_friends_dir:
        for ch in ("et", "mt", "tt"):
            friend_dirs[ch].append(ff_friends_dir)
    for friend_dir in additional_friend_dirs:
        for ch in friend_dirs:
            friend_dirs[ch].append(friend_dir)
    args = []
    for ch, dirs in friend_dirs.items():
        if dirs:
            args += [f"--{ch}-friend-directory", *dirs]
    return args


def mode_shapes(cfg, extra):
    from common.sample_paths import build_ul_sample_paths, output_run_dir

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])

    # Nested output/[{tag}/]{qcd-label}/{era}/{channel}/shapes.root -- see
    # README's flag reference for why tag defaults to ntupletag.
    qcd_label = "ff" if cfg["ff_friends_dir"] else "ss-os"
    extra_args = []
    if cfg["ff_friends_dir"]:
        extra_args += ["--ff-type", cfg["ff_type"]]

    friend_args = friend_directory_args(
        ff_friends_dir=cfg["ff_friends_dir"],
        additional_friend_dirs=cfg["additional_friends"],
    )
    if cfg["selection_friend"]:
        extra_args_selection_friend = ["--selection-friend", cfg["selection_friend"]]
    else:
        extra_args_selection_friend = []

    directory_args = ["--directory", paths.ntuples]

    # --skip-systematics is not a separate mode -- passed through via `extra`.
    if not os.environ.get("DNN_FRIENDS_DIR"):
        extra_args.append("--no-dnn-categorization")

    if cfg["stxs_stage"]:
        extra_args += ["--stxs-stage", cfg["stxs_stage"]]

    for channel in cfg["channels"].split(","):
        run_dir = output_run_dir(cfg, qcd_label, channel)
        run_dir.mkdir(parents=True, exist_ok=True)
        outfile = run_dir / "shapes.root"

        def _produce(output_file, ff_only=False):
            cmd = [
                "python",
                "shapes/produce_shapes.py",
                "--era", cfg["era"],
                "--channels", channel,
                # Scopes ntuple_processor's validation_database/ cache by ntupletag --
                # without this, switching --ntupletag reuses another tag's stale file
                # list and raises "File ... not found in validation results." (booking.py:361).
                "--validation-tag", cfg["ntupletag"],
                "--validation-db-root", cfg["validation_dir"],
                *directory_args,
                *friend_args,
                *extra_args_selection_friend,
                "--output-file", str(output_file),
                "--nprocs", str(cfg["nprocs"]),
                "--nthreads", str(cfg["nthreads"]),
                "--xrootd",
                *extra_args,
                *(["--ff-only"] if ff_only else []),
                *extra,
            ]
            return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()})

        if qcd_label == "ff":
            # Reuses an existing ss-os run for the same tag/era/channels instead of
            # redoing it, via common/shapes_merge.py's merge_ff_reuse_if_needed() --
            # the same function condor/submit_shapes.py's ff jobs call.
            ss_os_file = output_run_dir(cfg, "ss-os", channel) / "shapes.root"
            if ss_os_file.exists():
                print(f"[SHAPES] Reusing existing ss-os shapes at {ss_os_file} -- booking only the "
                      f"FF-weighted systematics (--ff-only) and merging onto a copy of it, instead of "
                      f"redoing the full (expensive) shape production.")
                ff_only_file = run_dir / "shapes_ff_only.root"
                result = _produce(ff_only_file, ff_only=True)
                if result.returncode != 0:
                    return result.returncode
                from common.shapes_merge import merge_ff_reuse_if_needed

                def _run_hadd_conda(argv):
                    # run.py isn't conda-activated itself -- route hadd through run_conda()
                    # like every other subprocess here, not shapes_merge's plain-subprocess default.
                    return run_conda(argv, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode

                try:
                    merge_ff_reuse_if_needed(outfile, run_hadd=_run_hadd_conda)
                except RuntimeError as exc:
                    print(f"[SHAPES] {exc}", file=sys.stderr)
                    return 1
            else:
                print(f"[SHAPES] No existing ss-os shapes found at {ss_os_file}; producing full shapes "
                      f"(including FF systematics) from scratch.")
                result = _produce(outfile, ff_only=False)
                if result.returncode != 0:
                    return result.returncode
        else:
            print(f"[SHAPES] Producing shapes: era={cfg['era']} channel={channel}")
            result = _produce(outfile, ff_only=False)
            if result.returncode != 0:
                return result.returncode

        print(f"[SHAPES] Running post-processing estimations on {outfile}")
        # --do-ff needs FF friend trees; without them, fall back to --do-qcd's ss->os
        # extrapolation (shapes/estimations/qcd.py:qcd_estimation) -- both read the same
        # `_ss` histograms produce_shapes.py always books, so no production-side change.
        estimation_args = ["--do-ff"] if cfg["ff_friends_dir"] else ["--do-qcd"]
        cmd = [
            "python",
            "shapes/do_estimations.py",
            "--era", cfg["era"],
            "--input-file", str(outfile),
            *estimation_args,
            *extra,
        ]
        result = run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()})
        if result.returncode != 0:
            return result.returncode
    return 0


def mode_plot(cfg, extra):
    from common.sample_paths import output_run_dir, plot_output_dir

    qcd_label = "ff" if cfg["ff_friends_dir"] else "ss-os"
    # /web only works run locally on a node where it's mounted (not condor).
    plot_dir = plot_output_dir(cfg, qcd_label)
    variables = os.environ.get("VARIABLES", "m_vis,pt_1,pt_2,eta_1,eta_2,mt_1")

    for channel in cfg["channels"].split(","):
        # Same nested layout mode_shapes writes to (output/[{tag}/]{qcd-label}/{era}/{channel}/shapes.root).
        outfile = output_run_dir(cfg, qcd_label, channel) / "shapes.root"
        print(f"[PLOT] Plotting shapes from {outfile}")
        cmd = [
            "python",
            "plotting/plot_shapes_control.py",
            "--input-file", str(outfile),
            "--output-dir", plot_dir,
            "--era", cfg["era"],
            "--channels", channel,
            "--variables", variables,
            # An ff-labeled shapes.root has no QCD -- without --fake-factor,
            # plot_shapes_control.py's QCD-seeking default silently drops that background.
            *(["--fake-factor"] if cfg["ff_friends_dir"] else []),
            *extra,
        ]
        returncode = run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode
        if returncode != 0:
            return returncode
        _copy_index_php_into(Path(plot_dir))
    return 0


def _copy_index_php_into(plot_dir: Path):
    """Drops the CMS_HTT web-gallery index.php (plotting/index.php) into
    plot_dir and every subdirectory plot_shapes_control.py created under it
    (one per channel/category) -- /web needs one in each directory to browse
    it, and plot_shapes_control.py itself doesn't know about /web at all."""
    src = REPO_ROOT / "plotting" / "index.php"
    if not plot_dir.is_dir():
        return
    for d in [plot_dir, *(p for p in plot_dir.rglob("*") if p.is_dir())]:
        shutil.copy(src, d / "index.php")


def mode_train_shapes(cfg, extra):
    from common.sample_paths import build_ul_sample_paths

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])
    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    for channel in cfg["channels"].split(","):
        outfile = output_dir / f"{cfg['era']}-{channel}-training-shapes.root"
        print(f"[TRAIN-SHAPES] Producing training shapes: era={cfg['era']} channel={channel}")
        cmd = [
            "python",
            "shapes/produce_shapes.py",
            "--era", cfg["era"],
            "--channels", channel,
            "--validation-tag", cfg["ntupletag"],
            "--directory", paths.ntuples,
            *friend_directory_args(additional_friend_dirs=cfg["additional_friends"]),
            *(["--selection-friend", cfg["selection_friend"]] if cfg["selection_friend"] else []),
            "--output-file", str(outfile),
            "--nprocs", str(cfg["nprocs"]),
            "--nthreads", str(cfg["nthreads"]),
            "--xrootd",
            "--skip-systematics",
            *extra,
        ]
        result = run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()})
        if result.returncode != 0:
            return result.returncode
    return 0


def mode_configs(cfg, extra):
    from common.sample_paths import build_ul_sample_paths

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])
    # collect_config() prefixes the basename with {era}__{channel}__, the glob TRAIN-DATASET reads from its configs dir
    output_dir = Path(cfg["train_configs_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    outfile = output_dir / "config.yaml"

    print(f"[CONFIGS] Collecting ntuple_processor configs: era={cfg['era']} channels={cfg['channels']}")
    cmd = [
        "python",
        "shapes/produce_shapes.py",
        "--era", cfg["era"],
        "--channels", cfg["channels"],
        "--validation-tag", cfg["ntupletag"],
        "--directory", paths.ntuples,
        *friend_directory_args(additional_friend_dirs=cfg["additional_friends"]),
        *(["--selection-friend", cfg["selection_friend"]] if cfg["selection_friend"] else []),
        "--output-file", str(outfile.with_suffix(".root")),
        "--collect-config-only",
        "--no-dnn-categorization",
        "--xrootd",
        "--config-output-file", str(outfile),
        *extra,
    ]
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_gen_tff_configs(cfg, extra):
    print("[GEN-TFF-CONFIGS] Regenerating TFF per-channel preselection YAMLs from unified config")
    print(f"[GEN-TFF-CONFIGS] era={cfg['era']} channels={cfg['channels']}")
    cmd = ["python", "fake_factors/generate_configs.py", "--era", cfg["era"], "--channels", cfg["channels"]]
    return run_plain(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def _patched_ff_config(era: str, channel: str, config_kind: str, ff_input_dir: str) -> str:
    """For --ff-input-dir: copy fake_factors/configs/smhtt/{era}/{config_kind}_{channel}.yaml
    into a tmp dir alongside a patched common_settings.yaml (file_path/output_path -> ff_input_dir)
    -- load_config() always looks for common_settings.yaml next to --config-file, so this redirects
    ff_calculation.py/ff_corrections.py's input glob without touching the real files."""
    import shutil
    import tempfile
    import yaml

    # 2022/2023 halves share one combined FF config directory -- see analysis.ff_config_era.
    src_dir = REPO_ROOT / "fake_factors" / "configs" / ACTIVE_ANALYSIS / ff_config_era(era)
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"tff_config_{era}_{channel}_"))

    with open(src_dir / "common_settings.yaml") as f:
        common_cfg = yaml.safe_load(f)
    common_cfg["file_path"] = ff_input_dir
    common_cfg["output_path"] = ff_input_dir
    # Derive a stable workdir_name from ff_input_dir -- common_settings.yaml no longer
    # hardcodes one (Run3 eras), and ff_calculation.py's config["workdir_name"] would KeyError.
    common_cfg.setdefault("workdir_name", Path(ff_input_dir).name or era)
    with open(tmp_dir / "common_settings.yaml", "w") as f:
        yaml.safe_dump(common_cfg, f)

    config_src = src_dir / f"{config_kind}_{channel}.yaml"
    shutil.copy(config_src, tmp_dir / config_src.name)
    return str(tmp_dir / config_src.name)


def _adjust_binning(config_file: str, cuts_config_file: str | None, env_overrides: dict):
    """Recomputes equipopulated var_bins/split_categories in-place on `config_file` from the
    CURRENT preselected ntuples (SRlike region) -- must run before ff_calculation.py/
    ff_corrections.py read the same config, or stale committed var_bins vs. the current data's
    per-category statistics crash ff_functions.py's sparsify() with "Shape mismatch". Shared by
    FF/FF-CORR and FF-MEASURE."""
    cmd = [
        "python", "fake_factors/adjust_binning.py",
        "--config", config_file,
        "--cut-region", "SRlike",
    ]
    if cuts_config_file:
        cmd += ["--cuts-config", cuts_config_file]
    result = run_plain(cmd, env_overrides=env_overrides)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def mode_ff(cfg, extra):
    # One config PER CHANNEL under fake_factors/configs/smhtt/{era}/, never joined --
    # loop per channel. cfg["ff_config"] (if set) overrides for a single explicit file.
    print(f"[FF] Running TauFakeFactors fake factor calculation: era={cfg['era']} channels={cfg['channels']}")
    env_overrides = {"PYTHONPATH": f"{os.environ.get('PYTHONPATH', '')}:{REPO_ROOT / 'fake_factors'}"}
    if cfg["ff_config"]:
        cmd = ["python", "fake_factors/ff_calculation.py", "--config-file", cfg["ff_config"], *extra]
        return run_plain(cmd, env_overrides=env_overrides).returncode
    for channel in cfg["channels"].split(","):
        if cfg["ff_input_dir"]:
            config_file = _patched_ff_config(cfg["era"], channel, "fake_factors", cfg["ff_input_dir"])
            _adjust_binning(config_file, None, env_overrides=env_overrides)
        else:
            # Points straight at the committed repo yaml (no ntuple_path/output_path for
            # Run3 -- see common_settings.yaml's header comment -- so this branch doesn't
            # actually work for Run3 without --ff-input-dir regardless). Never run
            # adjust_binning here: it would mutate the checked-in config in place.
            config_file = f"fake_factors/configs/{ACTIVE_ANALYSIS}/{ff_config_era(cfg['era'])}/fake_factors_{channel}.yaml"
        cmd = ["python", "fake_factors/ff_calculation.py", "--config-file", config_file, *extra]
        result = run_plain(cmd, env_overrides=env_overrides)
        if result.returncode != 0:
            return result.returncode
    return 0


def mode_ff_corr(cfg, extra):
    # Same per-channel-file layout as FF above (real filenames are corrections_{ch}.yaml).
    print(f"[FF-CORR] Running TauFakeFactors fake factor corrections: era={cfg['era']} channels={cfg['channels']}")
    env_overrides = {"PYTHONPATH": f"{os.environ.get('PYTHONPATH', '')}:{REPO_ROOT / 'fake_factors'}"}
    if cfg["ff_corr_config"]:
        cmd = ["python", "fake_factors/ff_corrections.py", "--config-file", cfg["ff_corr_config"], *extra]
        return run_plain(cmd, env_overrides=env_overrides).returncode
    for channel in cfg["channels"].split(","):
        if cfg["ff_input_dir"]:
            config_file = _patched_ff_config(cfg["era"], channel, "corrections", cfg["ff_input_dir"])
            # corrections_{channel}.yaml's target_processes blocks don't carry their own
            # region cuts (SRlike_cuts/...) -- adjust_binning.py needs --cuts-config
            # pointing at fake_factors_{channel}.yaml, which does.
            cuts_config_file = _patched_ff_config(cfg["era"], channel, "fake_factors", cfg["ff_input_dir"])
            _adjust_binning(config_file, cuts_config_file, env_overrides=env_overrides)
        else:
            # See mode_ff's matching branch: doesn't work for Run3 without --ff-input-dir
            # anyway, and must never run adjust_binning against the committed repo yaml.
            config_file = f"fake_factors/configs/{ACTIVE_ANALYSIS}/{ff_config_era(cfg['era'])}/corrections_{channel}.yaml"
        cmd = ["python", "fake_factors/ff_corrections.py", "--config-file", config_file, *extra]
        result = run_plain(cmd, env_overrides=env_overrides)
        if result.returncode != 0:
            return result.returncode
    return 0


def _patched_tff_config(
    era: str, channel: str, config_kind: str, ntupletag: str | None, selection_friend: str | None,
    user: str | None = None, tag: str | None = None, correction_tag: str | None = None, extra_friends=(),
) -> str:
    """FF-MEASURE's config patcher (distinct from _patched_ff_config above, which only
    covers FF/FF-CORR's --ff-input-dir case): copies fake_factors/configs/smhtt's
    real {config_kind}_{channel}.yaml into a tmp dir alongside a patched
    common_settings.yaml, so ntupletag/selection_friend can redirect
    preselection.py/ff_calculation.py/ff_corrections.py's ntuple/output paths without
    touching the real files. ntupletag must move output_path/file_path/workdir_name
    together across all three steps, or they'd read/write mismatched trees. tag is the
    workdir_name (defaults to the ntupletag in main()). correction_tag
    overrides corrections_{channel}.yaml's own correction_tag (config_kind=="corrections"
    only) -- see ff_corrections.py's save_path nesting.
    selection_friend deliberately does NOT add a normalization friend here -- TauFakeFactors
    already computes those columns itself and attaching one would collide.
    """
    import yaml

    from common.sample_paths import build_shape_output_paths, build_ul_sample_paths

    src_dir = REPO_ROOT / "fake_factors" / "configs" / ACTIVE_ANALYSIS / ff_config_era(era)
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"tff_{config_kind}_config_{era}_{channel}_"))

    with open(src_dir / "common_settings.yaml") as f:
        common_cfg = yaml.safe_load(f)
    if ntupletag:
        common_cfg["ntuple_path"] = build_ul_sample_paths(ntupletag, era, user=user).kingmaker_basedir_xrootd
        common_cfg["output_path"] = common_cfg["file_path"] = build_shape_output_paths(ntupletag, user=user).fake_factors
        common_cfg["workdir_name"] = tag or ntupletag
    if selection_friend or extra_friends:
        common_cfg["friends"] = [*filter(None, [selection_friend]), *extra_friends]
    with open(tmp_dir / "common_settings.yaml", "w") as f:
        yaml.safe_dump(common_cfg, f)

    config_src = src_dir / f"{config_kind}_{channel}.yaml"
    if config_kind == "corrections" and correction_tag:
        with open(config_src) as f:
            corr_cfg = yaml.safe_load(f)
        corr_cfg["correction_tag"] = correction_tag
        with open(tmp_dir / config_src.name, "w") as f:
            yaml.safe_dump(corr_cfg, f)
    else:
        shutil.copy(config_src, tmp_dir / config_src.name)
    return str(tmp_dir / config_src.name)


def mode_ff_measure(cfg, extra):
    """Chains gen-configs -> presel -> ff -> ff-corr for TauFakeFactors' own measurement
    (see README's "Fake-factor measurement" section for usage). Output locations are
    unchanged from running those steps individually."""
    print(f"[FF-MEASURE] Running the full TauFakeFactors FF measurement chain: era={cfg['era']} channels={cfg['channels']}")
    steps = [s.strip() for s in cfg["steps"].split(",") if s.strip()] if cfg["steps"] else FF_MEASURE_STEPS
    channels = cfg["channels"].split(",")
    env_overrides = {"PYTHONPATH": pythonpath_with_tff()}
    # Correctness over speed: see --use-cached-intermediary-steps' help.
    cache_args = [] if cfg["use_cached_intermediary_steps"] else ["--ignore-cached-intermediary-steps"]

    if "gen-configs" in steps:
        result = run_plain([
            "python", "fake_factors/generate_configs.py",
            "--era", cfg["era"], "--channels", cfg["channels"],
        ])
        if result.returncode != 0:
            return result.returncode

    if "presel" in steps:
        presel_env = {
            **env_overrides,
            "TFF_PRESEL_OUTER_WORKERS": _PRESEL_OUTER_WORKERS,
            "TFF_PRESEL_INNER_WORKERS": _PRESEL_INNER_WORKERS,
        }
        for channel in channels:
            config_file = _patched_tff_config(
                cfg["era"], channel, "preselection", cfg["ntupletag"], cfg["selection_friend"], user=cfg["user"],
                tag=cfg["tag"], extra_friends=cfg["additional_friend_tags"],
            )
            result = run_plain([
                "python", "fake_factors/preselection.py",
                "--config-file", config_file,
                "--nthreads", str(cfg["nthreads"]),
            ], env_overrides=presel_env)
            if result.returncode != 0:
                return result.returncode

    if "ff" in steps:
        # fake_factors/configs/smhtt/{era}/ ships one config PER CHANNEL,
        # never a joined-multi-channel file -- loops per channel, same as
        # mode_ff below. cfg["ff_config"] (if set) still overrides for a
        # single explicit file.
        if cfg["ff_config"]:
            _adjust_binning(cfg["ff_config"], None, env_overrides)
            result = run_plain([
                "python", "fake_factors/ff_calculation.py",
                "--config-file", cfg["ff_config"], *cache_args,
            ], env_overrides=env_overrides)
            if result.returncode != 0:
                return result.returncode
        else:
            for channel in channels:
                config_file = _patched_tff_config(
                    cfg["era"], channel, "fake_factors", cfg["ntupletag"], None, user=cfg["user"],
                    tag=cfg["tag"],
                )
                _adjust_binning(config_file, None, env_overrides)
                result = run_plain([
                    "python", "fake_factors/ff_calculation.py",
                    "--config-file", config_file, *cache_args,
                ], env_overrides=env_overrides)
                if result.returncode != 0:
                    return result.returncode

    if "ff-corr" in steps:
        # Same per-channel-file note as above; corrections_{channel}.yaml's
        # target_processes blocks don't carry their own region cuts, so
        # adjust_binning.py needs --cuts-config pointing at
        # fake_factors_{channel}.yaml, which does.
        if cfg["ff_corr_config"]:
            _adjust_binning(cfg["ff_corr_config"], cfg["ff_config"] or None, env_overrides)
            result = run_plain([
                "python", "fake_factors/ff_corrections.py",
                "--config-file", cfg["ff_corr_config"], *cache_args,
            ], env_overrides=env_overrides)
            if result.returncode != 0:
                return result.returncode
        else:
            for channel in channels:
                config_file = _patched_tff_config(
                    cfg["era"], channel, "corrections", cfg["ntupletag"], None, user=cfg["user"],
                    tag=cfg["tag"], correction_tag=cfg["correction_tag"],
                )
                cuts_config_file = _patched_tff_config(
                    cfg["era"], channel, "fake_factors", cfg["ntupletag"], None, user=cfg["user"],
                    tag=cfg["tag"],
                )
                _adjust_binning(config_file, cuts_config_file, env_overrides)
                result = run_plain([
                    "python", "fake_factors/ff_corrections.py",
                    "--config-file", config_file, *cache_args,
                ], env_overrides=env_overrides)
                if result.returncode != 0:
                    return result.returncode

    return 0


def _btag_tagged_config(
    config_file: Path, ntupletag: str | None, selection_friend: str | None, tmp_root: Path,
    user: str | None = None, tag: str | None = None, extra_friends=(),
) -> Path:
    """Copy `config_file` (+ its common_settings.yaml) into a temp dir with the
    ntupletag-derived path overrides and/or the selection-friend/tag override
    written into the config itself, which helper.functions.load_config lets
    win over common_settings.yaml."""
    import yaml

    from common.sample_paths import XROOTD_REDIRECTOR, build_shape_output_paths, crown_ntuple_base

    src_dir = config_file.parent
    dst_dir = tmp_root / src_dir.name
    dst_dir.mkdir(parents=True, exist_ok=True)
    common = src_dir / "common_settings.yaml"
    if common.exists():
        shutil.copy(common, dst_dir / common.name)
        base = yaml.safe_load(common.read_text()) or {}
    else:
        base = {}
    cfg = yaml.safe_load(config_file.read_text()) or {}
    merged = {**base, **cfg}
    if ntupletag:
        cfg["ntuple_path"] = f"{XROOTD_REDIRECTOR}{crown_ntuple_base(ntupletag, user=user)}/CROWNRun"
        cfg["output_path"] = f"{build_shape_output_paths(ntupletag, user=user).btag_efficiencies}/"
        cfg["file_path"] = cfg["output_path"]
        cfg["ntupletag"] = ntupletag
        print(f"[BTAG] ntupletag={ntupletag}: ntuple_path={cfg['ntuple_path']} output_path={cfg['output_path']}")
    if selection_friend or extra_friends:
        cfg["friends"] = [*filter(None, [selection_friend]), *extra_friends]
        print(f"[BTAG] friends={cfg['friends']}")
    if tag and tag != ntupletag:
        cfg["tag"] = tag
        print(f"[BTAG] tag={tag}")
    dst = dst_dir / config_file.name
    dst.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return dst


def mode_btag(cfg, extra):
    """B-tag efficiency measurement -- see README's "B-tag efficiency measurement" section
    for usage. --ntupletag scopes ntuple_path/output_path/workdir so runs on different
    productions don't overwrite each other."""
    _config_root = REPO_ROOT / "btag_efficiencies" / "configs"
    _tff_root = REPO_ROOT / "fake_factors"
    channels = cfg["channels"].split(",")
    print(f"[BTAG] era={cfg['era']} channels={cfg['channels']}")

    steps = BTAG_DEFAULT_STEPS if not cfg["steps"] else [x.strip() for x in cfg["steps"].split(",") if x.strip()]
    tmp_root = Path(tempfile.mkdtemp(prefix="btag_eff_cfg_"))

    def _resolved(path: Path) -> Path:
        return _btag_tagged_config(path, cfg["ntupletag"], cfg["selection_friend"], tmp_root, cfg["user"], cfg["tag"], cfg["additional_friend_tags"])

    if "gen-configs" in steps:
        result = run_plain([
            "python", str(_config_root.parent / "generate_configs.py"),
            "--era", cfg["era"], "--channels", cfg["channels"],
        ])
        if result.returncode != 0:
            return result.returncode

    if "presel" in steps:
        for channel in channels:
            presel_config = _config_root / cfg["era"] / f"preselection_{channel}.yaml"
            if not presel_config.exists():
                print(f"[BTAG] No btag_efficiencies preselection config for era={cfg['era']} channel={channel}: {presel_config}", file=sys.stderr)
                return 1
            result = run_plain([
                "python", str(_tff_root / "preselection.py"),
                "--config-file", str(_resolved(presel_config)),
                "--nthreads", str(cfg["nthreads"]),
            ], env_overrides={"PYTHONPATH": pythonpath_with_tff()})
            if result.returncode != 0:
                return result.returncode

    if "calc" in steps:
        eff_config = _config_root / cfg["era"] / "btag_efficiency.yaml"
        if not eff_config.exists():
            print(f"[BTAG] No btag_efficiency.yaml for era={cfg['era']}: {eff_config}", file=sys.stderr)
            return 1
        result = run_plain([
            "python", str(REPO_ROOT / "btag_efficiencies" / "calculate_efficiency.py"),
            "--config-file", str(_resolved(eff_config)),
        ], env_overrides={"PYTHONPATH": pythonpath_with_tff()})
        if result.returncode != 0:
            return result.returncode

    shutil.rmtree(tmp_root, ignore_errors=True)
    return 0


def mode_train_dataset(cfg, extra):
    # Local (non-condor) wrapper around create_training_dataset.py's plain-Python CLI.
    # --train-configs-dir globs {era}__{channel}__config.yaml files and merges them across
    # eras via trainings/adjust_config.py; --train-config points at a single built YAML.
    train_config = cfg["train_config"]
    configs_dir = cfg["train_configs_dir"]
    base_dataset_dir = cfg["base_dataset_dir"]
    common_setup_config = cfg["common_setup_config"]

    if not train_config:
        if not configs_dir:
            print(
                "ERROR: set --train-config/TRAIN_CONFIG (a pre-built per-(channel,era) training "
                "dataset config YAML) or --train-configs-dir/TRAIN_CONFIGS_DIR (a directory of "
                "{era}__{channel}__config.yaml files from run.py CONFIGS / "
                "condor/submit_train_configs.py, to auto-merge across eras). See "
                "trainings/create_training_dataset.py --config and README's NN training section.",
                file=sys.stderr,
            )
            return 1

        channels = [c.strip() for c in cfg["channels"].split(",") if c.strip()]
        eras_filter = {e.strip() for e in (cfg["train_eras"] or "").split(",") if e.strip()}
        configs_path = Path(configs_dir)
        matched = []
        for path in sorted(configs_path.glob("*__*__*.yaml")):
            parts = path.stem.split("__", 2)
            if len(parts) < 2:
                continue
            era, channel = parts[0], parts[1]
            if era == "merged" or channel not in channels:
                continue
            if eras_filter and era not in eras_filter:
                continue
            matched.append(path)
        if not matched:
            eras_msg = f", eras={sorted(eras_filter)}" if eras_filter else ""
            print(
                f"ERROR: no {{era}}__{{channel}}__config.yaml files under {configs_dir} match "
                f"channels={channels}{eras_msg} -- run CONFIGS / condor/submit_train_configs.py "
                "first.",
                file=sys.stderr,
            )
            return 1

        print(f"[TRAIN-DATASET] Merging {len(matched)} per-(era,channel) config(s) from {configs_dir}:")
        for p in matched:
            print(f"[TRAIN-DATASET]   {p.name}")
        merge_setup_config = common_setup_config or write_training_setup(configs_path, channels)
        merged_config = configs_path / f"merged__{'-'.join(channels)}__config.yaml"
        adjust_cmd = [
            "python", "trainings/adjust_config.py",
            "--configs", *[str(p) for p in matched],
            "--modified-config", str(merged_config),
            "--common-setup-config", merge_setup_config,
        ]
        result = run_conda(adjust_cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()})
        if result.returncode != 0:
            return result.returncode
        train_config = str(merged_config)
        common_setup_config = merge_setup_config

    print(f"[TRAIN-DATASET] Building training dataset from {train_config} -> {base_dataset_dir}")
    cmd = [
        "python", "trainings/create_training_dataset.py",
        "--config", train_config,
        "--base-dataset-dir", base_dataset_dir,
    ]
    if common_setup_config:
        cmd += ["--common-setup-config", common_setup_config]
    cmd += extra
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def uat_config_dir(stage) -> Path:
    """The training's class and input definitions: stage0 ggh/qqh in run3-coarse, the stage-1.2 bins in run3-fine."""
    default = REPO_ROOT / "trainings/uncertainty-aware-training/datasets" / ACTIVE_ANALYSIS / ("run3-fine" if stage == "stage1p2" else "run3-coarse")
    return Path(os.environ.get("UAT_CONFIG_DIR", default))


def write_training_setup(directory: Path, channels: list) -> str:
    """common/training_setup.yaml plus the signal labels of both stages and only the inputs of both trainings,
    one file per channel set: one label per stage-0 unit the shapes book, and the stage-1.2 classes of
    common/training_stxs_classes.yaml, per event from the HTXS stage-1.2 bin (analyses/<analysis>/trainings/training_labels.py)."""
    import importlib
    import yaml

    flags = {unit["key"]: f"is_{'_'.join(unit['datasets'])}__{unit['selection']}"  # the config's is_<dataset>__<process> flag of the unit
             for unit in importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.common.stxs_tools").signal_units("stage0").values()}
    labels = {f"is_{key}_htautau": [flag] for key, flag in flags.items()}
    stage1p2 = REPO_ROOT / "common/training_stxs_classes.yaml"
    for ch in channels:
        for c in (yaml.safe_load(stage1p2.read_text()) or {}).get(ch, []) if stage1p2.exists() else []:
            labels[c["label"]] = [f"{flags[c['mode']]}_bin{b}_selection" for b in c["bins"]]
    setup = yaml.safe_load((REPO_ROOT / "common/training_setup.yaml").read_text())
    setup["dataset_modifications"]["labels"]["renaming_map"].update(labels)
    # only the inputs of the stage-0 and stage-1.2 trainings: every stored column costs memory in the 2022-2025 folds
    setup["training_variables"] = list(dict.fromkeys(v for ch in channels for stage in ("stage0", "stage1p2")
                                                     if (uat := uat_config_dir(stage) / f"smhtt_{ch}.yaml").exists()
                                                     for v in yaml.safe_load(uat.read_text()).get("training_variables", [])))
    path = directory / f"training_setup_{'-'.join(channels)}.yaml"
    path.write_text(yaml.safe_dump(setup, sort_keys=False))
    return str(path)


def mode_train(cfg, extra):
    # The uncertainty-aware-training submodule's own `law run ...` workflow is left
    # untouched deliberately -- run.py just forwards parameters to its law CLI, same as
    # FF/FF-CORR shelling out to TauFakeFactors' own scripts.
    train_tag = cfg["tag"]
    train_task, cuda_device, workers = cfg["train_task"], cfg["cuda_device"], cfg["workers"]
    dataset_dir, output_dir = (Path(cfg[key]).resolve() for key in ("base_dataset_dir", "train_output_dir"))
    config_dir = uat_config_dir(cfg["stxs_stage"])
    missing = [ch for ch in cfg["channels"].split(",") if not (config_dir / f"smhtt_{ch}.yaml").exists()]
    if missing:
        print(f"ERROR: no training config for {','.join(missing)} in {config_dir} (smhtt_<channel>.yaml)", file=sys.stderr)
        return 1
    print(f"[TRAIN] task={train_task} tag={train_tag} channels={cfg['channels']}")

    uat_dir = REPO_ROOT / "trainings" / "uncertainty-aware-training"
    if not uat_dir.is_dir():
        print("ERROR: trainings/uncertainty-aware-training not found", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{env.get('PYTHONPATH', '')}:{REPO_ROOT}"
    subprocess.run(["nice", "-n", "19", "law", "index", "-v"], cwd=str(uat_dir), env=env, check=True)

    import yaml
    from common.analysis import get_center_of_mass, get_data_eras, get_luminosity
    from plotting.plot_shapes_control import CHANNEL_LABELS

    for channel in cfg["channels"].split(","):
        print(f"[TRAIN] Running {train_task} for channel {channel}")
        # plot header from the era flags the model is trained with (merged data eras included)
        eras = [v[3:] for v in yaml.safe_load((config_dir / f"smhtt_{channel}.yaml").read_text())["training_variables"] if v.startswith("is_20")]
        years = sorted({e[:4] for era in eras for e in get_data_eras(era)})
        com = get_center_of_mass(eras[0])
        lumi_text = f"{sum(get_luminosity(e) for e in eras):.1f} fb$^{{-1}}$ ({'–'.join(dict.fromkeys([years[0], years[-1]]))}, {com:g} TeV)"
        cmd = [
            "nice", "-n", "19",
            "law", "run", train_task,
            "--workers", workers,
            "--local-scheduler",
            "--version", f"{train_tag}_{channel}",
            "--log-level", "INFO",
            "--cuda-device", cuda_device,
            "--no-lock",
            f"--dataset-directory={dataset_dir}/{channel}/folds/",
            f"--base-config-file={config_dir}/smhtt_{channel}.yaml",
            # everything on /ceph next to the datasets: the law defaults are one shared config file and the old smhtt_ul checkout
            f"--dataset-config-file={dataset_dir}/{channel}/training_config_{train_tag}_{channel}.yaml",
            f"--directory={output_dir}",
        ]
        if train_task == "RunAllCENNTConfusionMatrixWorkflow":
            cmd += [f"--title-left={CHANNEL_LABELS.get(channel, channel)}", f"--title-right={lumi_text}"]
        result = subprocess.run(cmd, cwd=str(uat_dir), env=env)
        if result.returncode != 0:
            return result.returncode
    return 0


def main(argv=None) -> int:
    args, extra = parse_args(argv)
    mode = args.mode_flag or args.mode_positional

    if not mode or mode not in MODES:
        make_parser().print_help()
        return 0 if mode is None else 1

    # --flag wins, then the env var, then the hardcoded default -- see README's flag reference.
    channels = env_or(args.channels, "CHANNELS", "et,mt,tt")

    cfg = {
        "era": env_or(args.era, "ERA", "2022postEE"),
        "channels": channels,
        "stxs_stage": env_or(args.stxs_stage, "STXS_STAGE", None),
        "ntupletag": env_or(args.ntupletag, "NTUPLETAG", ""),
        "tag": env_or(args.tag, "TAG", None),
        "output_dir": env_or(args.output_dir, "OUTPUT_DIR", None),
        "nthreads": env_or(args.nthreads, "NTHREADS", "4"),
        "nprocs": env_or(args.nprocs, "NPROCS", "1"),
        "validation_dir": None,
        "ff_friends_dir": env_or(args.ff_friend, "FF_FRIENDS_DIR", ""),
        "ff_type": env_or(args.ff_type, "FF_TYPE", "fake_factor"),
        "additional_friends": env_or(args.additional_friends, "ADDITIONAL_FRIENDS_DIR", ""),
        "ff_config": env_or(args.ff_config, "FF_CONFIG", ""),
        "ff_corr_config": env_or(args.ff_corr_config, "FF_CORR_CONFIG", ""),
        "ff_input_dir": env_or(args.ff_input_dir, "FF_INPUT_DIR", ""),
        "selection_friend": env_or(args.selection_friend, "SELECTION_FRIEND_DIR", ""),
        "steps": env_or(args.steps, "STEPS", None),
        "use_cached_intermediary_steps": args.use_cached_intermediary_steps,
        "user": env_or(args.user, "USER_OVERRIDE", None),
        "correction_tag": env_or(args.correction_tag, "CORRECTION_TAG", None),
        "train_task": env_or(args.train_task, "TRAIN_TASK", "RunAllCENNTConfusionMatrixWorkflow"),
        "cuda_device": env_or(args.cuda_device, "CUDA_DEVICE", "0,1"),
        "workers": env_or(args.workers, "WORKERS", "2"),
        "train_config": env_or(args.train_config, "TRAIN_CONFIG", None),
        "train_configs_dir": env_or(args.train_configs_dir, "TRAIN_CONFIGS_DIR", None),
        "train_eras": env_or(args.train_eras, "TRAIN_ERAS", None),
        "base_dataset_dir": env_or(args.base_dataset_dir, "BASE_DATASET_DIR", None),
        "train_output_dir": env_or(args.train_output_dir, "TRAIN_OUTPUT_DIR", None),
        "common_setup_config": env_or(args.common_setup_config, "COMMON_SETUP_CONFIG", ""),
    }

    # bare tags for the TauFakeFactors preselection configs, which resolve friend tags next to the ntuples themselves
    cfg["additional_friend_tags"] = [tag.strip() for tag in cfg["additional_friends"].split(",") if tag.strip()]
    needs_ntupletag = mode in ("SHAPES", "TRAIN-SHAPES", "CONFIGS")
    steps = [x.strip() for x in cfg["steps"].split(",") if x.strip()] if cfg["steps"] else None
    if mode == "FF-MEASURE":
        needs_ntupletag = bool({"presel", "ff", "ff-corr"} & set(steps or FF_MEASURE_STEPS))
    if mode == "BTAG":
        needs_ntupletag = bool({"presel", "calc"} & set(steps or BTAG_DEFAULT_STEPS))
    if mode == "TRAIN":
        needs_ntupletag = not cfg["base_dataset_dir"]
    if mode == "TRAIN-DATASET":
        needs_ntupletag = not (cfg["base_dataset_dir"] and (cfg["train_config"] or cfg["train_configs_dir"]))
    if needs_ntupletag and not cfg["ntupletag"]:
        print("ERROR: NTUPLETAG must be set (CROWN ntuple tag, e.g. htt_260417_2022-23).", file=sys.stderr)
        return 1
    if mode in ("SHAPES", "TRAIN-SHAPES", "CONFIGS") and not cfg["selection_friend"]:
        print("ERROR: SELECTION_FRIEND_DIR/--selection-friend must be set (CROWN's shapes_preparation friend tag).", file=sys.stderr)
        return 1

    if cfg["ntupletag"]:
        from common.sample_paths import build_shape_output_paths

        shape_paths = build_shape_output_paths(cfg["ntupletag"], user=cfg["user"])
        if cfg["tag"] is None:
            cfg["tag"] = cfg["ntupletag"]
        if cfg["output_dir"] is None:
            cfg["output_dir"] = shape_paths.output
        cfg["validation_dir"] = shape_paths.validation
        # signals booked per production mode (stage0) for both stages: the stage-1.2 labels come per event from the HTXS fine bin
        cfg["train_configs_dir"] = cfg["train_configs_dir"] or f"{shape_paths.training}/configs/stage0"
        cfg["base_dataset_dir"] = cfg["base_dataset_dir"] or f"{shape_paths.training}/datasets/stage0"
        cfg["train_output_dir"] = cfg["train_output_dir"] or f"{shape_paths.training}/models"
        # --ff-friend/FF_FRIENDS_DIR: a bare tag (no '/') resolves against this
        # ntupletag, same as --additional-friends/ADDITIONAL_FRIENDS_DIR below
        # (each comma-separated entry resolved independently) -- see
        # resolve_friend().
        if cfg["ff_friends_dir"]:
            cfg["ff_friends_dir"] = resolve_friend(cfg["ntupletag"], cfg["ff_friends_dir"])
        cfg["additional_friends"] = [
            resolve_friend(cfg["ntupletag"], tag.strip())
            for tag in cfg["additional_friends"].split(",")
            if tag.strip()
        ]
    else:
        cfg["tag"] = cfg["tag"] or "default"
        cfg["output_dir"] = cfg["output_dir"] or "output"
        cfg["validation_dir"] = "validation_database"
        cfg["additional_friends"] = []

    if mode == "SHAPES":
        return mode_shapes(cfg, extra)
    if mode == "PLOT":
        return mode_plot(cfg, extra)
    if mode == "TRAIN-SHAPES":
        return mode_train_shapes(cfg, extra)
    if mode == "CONFIGS":
        return mode_configs(cfg, extra)
    if mode == "GEN-TFF-CONFIGS":
        return mode_gen_tff_configs(cfg, extra)
    if mode == "FF":
        return mode_ff(cfg, extra)
    if mode == "FF-CORR":
        return mode_ff_corr(cfg, extra)
    if mode == "FF-MEASURE":
        return mode_ff_measure(cfg, extra)
    if mode == "BTAG":
        return mode_btag(cfg, extra)
    if mode == "TRAIN":
        return mode_train(cfg, extra)
    if mode == "TRAIN-DATASET":
        return mode_train_dataset(cfg, extra)

    raise AssertionError(f"unhandled mode {mode!r}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
