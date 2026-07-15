#!/usr/bin/env python3
"""
TauHarvest -- SM H->tautau analysis framework, main entry point.

Python control-script replacement for the former run.sh (Phase 6d, see
STATUS.md "## Phase 6d"). Same modes, same flags, same defaults, same
env-var-driven overrides as the bash version -- existing callers/docs should
switch from `source run.sh MODE [options]` to `python3 run.py MODE [options]`.

Usage:
    python3 run.py <MODE> [options]

Modes:
    XSEC          Build cross-section friend trees
    SHAPES        Produce shapes (with systematic variations)
    SHAPES-NOSYS  Produce nominal shapes only (fast)
    PLOT          Plot control shapes
    TRAIN-SHAPES  Produce shapes for NN training
    CONFIGS       Collect ntuple_processor configs (YAML) -- no histogram production
    GEN-TFF-CONFIGS  Regenerate TFF per-channel preselection YAMLs from unified config
    PRESEL        Run TauFakeFactors preselection (per channel)
    FF            Run TauFakeFactors fake factor calculation (per channel)
    FF-CORR       Run TauFakeFactors fake factor corrections (per channel)
    FF-MEASURE    Run the full FF measurement chain: GEN-TFF-CONFIGS -> PRESEL -> FF -> FF-CORR
                  (the four modes above still exist for single-step reruns)
    TRAIN         Run NN training via law (uncertainty-aware-training)
    TRAIN-DATASET Build training feather folds from ROOT shapes (plain Python, no law/condor)

Note on conda activation (see common/conda_env.py's module docstring for the
reasoning): only the modes that used `check_env()` in the bash version --
XSEC, SHAPES/SHAPES-NOSYS, TRAIN-SHAPES, CONFIGS, PRESEL -- activate the
`taukiktflow` conda env before running their python command, exactly as
before. PLOT/GEN-TFF-CONFIGS/FF/FF-CORR/TRAIN do not (same as the bash
version -- they run in whatever environment this script itself is invoked
under; PLOT in particular is expected to run under the separate
`environment-plotting.yml` env, not `taukiktflow`).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
from common.conda_env import run_in_conda  # noqa: E402

MODES = [
    "XSEC",
    "SHAPES",
    "SHAPES-NOSYS",
    "PLOT",
    "TRAIN-SHAPES",
    "CONFIGS",
    "GEN-TFF-CONFIGS",
    "PRESEL",
    "FF",
    "FF-CORR",
    "FF-MEASURE",
    "TRAIN",
    "TRAIN-DATASET",
]

HELP_EPILOG = """
Required environment variables (for shape production):
  NTUPLETAG          CROWN ntuple tag (e.g. htt_260417_2022-23)
  TAG                Output label tag (optional, e.g. 260417) -- accepted for
                      CLI-compat with the old bash script; unused by any mode.

Optional:
  ERA              (default: 2022postEE)
  CHANNELS         (default: et,mt,tt)
  VS_JET_WP        (default: Medium)
  VS_ELE_WP        (default: VVLoose, or Tight if CHANNELS == "et")
  FF_FRIENDS_DIR   Path to fake factor friend trees (enables FF mode in SHAPES)
  FF_CONFIG        Override config path for FF mode
  FF_CORR_CONFIG   Override config path for FF-CORR mode
  OUTPUT_DIR       (default: output)
  NTHREADS         (default: 4)
  NPROCS           (default: 1)
  TRAIN_TAG        Training version tag (default: 260507)
  TRAIN_TASK       law task name (default: RunAllCENNTConfusionMatrixWorkflow)
  CUDA_DEVICE      GPU device IDs for training (default: 0,1)
  WORKERS          law workers for training (default: 2)
  DATASET_DIR      Base dir for training datasets (default: /ceph/sgiappic/Htt_training/cennt_folds/coarse)
  UAT_CONFIG_DIR   Base dir for uncertainty-aware-training base configs

Any additional/unrecognized arguments are passed straight through to the
underlying python script, exactly like the old run.sh's trailing "$@".
"""


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="TauHarvest -- SM H->tautau analysis framework",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("mode_positional", nargs="?", default=None, metavar="MODE", help=f"one of: {', '.join(MODES)}")
    parser.add_argument("--mode", dest="mode_flag", default=None)
    parser.add_argument("--era", default=None)
    parser.add_argument("--channel", "--channels", dest="channels", default=None)
    parser.add_argument("--ntupletag", default=None)
    parser.add_argument("--tag", default=None)
    parser.add_argument("--vs-jet-wp", dest="vs_jet_wp", default=None)
    parser.add_argument("--vs-ele-wp", dest="vs_ele_wp", default=None)
    parser.add_argument("--nthreads", default=None)
    parser.add_argument("--nprocs", default=None)
    parser.add_argument("--output-dir", dest="output_dir", default=None)
    parser.add_argument("--ff-friends-dir", dest="ff_friends_dir", default=None)
    parser.add_argument("--ff-config", dest="ff_config", default=None)
    parser.add_argument("--ff-corr-config", dest="ff_corr_config", default=None)
    parser.add_argument("--presel-dir", dest="presel_dir", default=None)
    return parser


def parse_args(argv=None):
    parser = make_parser()
    args, extra = parser.parse_known_args(argv)
    return args, extra


def env_or(value, env_name, default):
    if value is not None:
        return value
    return os.environ.get(env_name, default)


def pythonpath_with_tff() -> str:
    existing = os.environ.get("PYTHONPATH", "")
    parts = [existing, str(REPO_ROOT), str(REPO_ROOT / "TauFakeFactors")]
    return ":".join(p for p in parts if p)


def run_plain(cmd_args, cwd=None, env_overrides=None):
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["nice", "-n", "19", *cmd_args], cwd=str(cwd or REPO_ROOT), env=env)


def run_conda(cmd_args, env_overrides=None):
    return run_in_conda(["nice", "-n", "19", *cmd_args], cwd=REPO_ROOT, env_overrides=env_overrides, check=False)


def mode_xsec(cfg, extra):
    from common.sample_paths import build_ul_sample_paths

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])
    print(f"[XSEC] Building cross-section friend trees for {cfg['ntupletag']}")
    if cfg["era"].startswith("2024") or cfg["era"].startswith("2025"):
        datasets_json = "TauFakeFactors/datasets/nanoAOD_v15/datasets.json"
    else:
        datasets_json = "TauFakeFactors/datasets/nanoAOD_v12/datasets.json"

    cmd = [
        "python",
        "friends/build_friend_tree.py",
        "--basepath",
        paths.kingmaker_basedir_xrootd,
        "--outputpath",
        f"root://cmsdcache-kit-disk.gridka.de/{paths.xsec_friends}",
        "--dataset-config",
        datasets_json,
        "--nthreads",
        str(cfg["nthreads"]),
        *extra,
    ]
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_shapes(cfg, extra, mode):
    from common.sample_paths import build_ul_sample_paths

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])

    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    outfile = output_dir / f"{cfg['era']}-{cfg['channels'].replace(',', '-', 1)}-shapes.root"

    extra_args = []
    ff_friends = []
    if cfg["ff_friends_dir"]:
        ff_friends = [
            "--et-friend-directory", cfg["ff_friends_dir"],
            "--mt-friend-directory", cfg["ff_friends_dir"],
            "--tt-friend-directory", cfg["ff_friends_dir"],
        ]
        extra_args += ["--ff-type", "fake_factor"]

    if cfg["presel_dir"]:
        extra_args += ["--presel-dir", cfg["presel_dir"]]

    if mode == "SHAPES-NOSYS":
        extra_args.append("--skip-systematic-variations")

    if not os.environ.get("DNN_FRIENDS_DIR"):
        extra_args.append("--no-dnn-categorization")

    print(f"[{mode}] Producing shapes: era={cfg['era']} channels={cfg['channels']}")
    cmd = [
        "python",
        "shapes/produce_shapes.py",
        "--era", cfg["era"],
        "--channels", cfg["channels"],
        "--vs-jet-wp", cfg["vs_jet_wp"],
        "--vs-ele-wp", cfg["vs_ele_wp"],
        "--directory", paths.ntuples,
        "--et-friend-directory", paths.xsec_friends,
        "--mt-friend-directory", paths.xsec_friends,
        "--tt-friend-directory", paths.xsec_friends,
        "--em-friend-directory", paths.xsec_friends,
        *ff_friends,
        "--output-file", str(outfile),
        "--num-processes", str(cfg["nprocs"]),
        "--num-threads", str(cfg["nthreads"]),
        "--xrootd",
        *extra_args,
        *extra,
    ]
    result = run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()})
    if result.returncode != 0:
        return result.returncode

    print(f"[{mode}] Running post-processing estimations on {outfile}")
    estimation_args = ["--do-ff"] if cfg["ff_friends_dir"] else []
    cmd = [
        "python",
        "shapes/do_estimations.py",
        "--era", cfg["era"],
        "--input", str(outfile),
        *estimation_args,
        *extra,
    ]
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_plot(cfg, extra):
    output_dir = Path(cfg["output_dir"])
    outfile = output_dir / f"{cfg['era']}-{cfg['channels'].replace(',', '-', 1)}-shapes.root"
    plot_dir = f"/web/sgiappic/public_html/CMS_HTT/{cfg['era']}/test/"
    variables = os.environ.get("VARIABLES", "m_vis,pt_1,pt_2,eta_1,eta_2,mt_1")

    print(f"[PLOT] Plotting shapes from {outfile}")
    cmd = [
        "python",
        "plotting/plot_shapes_control.py",
        "--input", str(outfile),
        "--output", plot_dir,
        "--era", cfg["era"],
        "--channels", cfg["channels"],
        "--variables", variables,
        *extra,
    ]
    return run_plain(cmd).returncode


def mode_train_shapes(cfg, extra):
    from common.sample_paths import build_ul_sample_paths

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])
    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    outfile = output_dir / f"{cfg['era']}-{cfg['channels'].replace(',', '-', 1)}-training-shapes.root"

    print(f"[TRAIN-SHAPES] Producing training shapes: era={cfg['era']} channels={cfg['channels']}")
    cmd = [
        "python",
        "shapes/produce_shapes.py",
        "--era", cfg["era"],
        "--channels", cfg["channels"],
        "--vs-jet-wp", cfg["vs_jet_wp"],
        "--vs-ele-wp", cfg["vs_ele_wp"],
        "--directory", paths.ntuples,
        "--et-friend-directory", paths.xsec_friends,
        "--mt-friend-directory", paths.xsec_friends,
        "--tt-friend-directory", paths.xsec_friends,
        "--em-friend-directory", paths.xsec_friends,
        "--output-file", str(outfile),
        "--num-processes", str(cfg["nprocs"]),
        "--num-threads", str(cfg["nthreads"]),
        "--xrootd",
        "--skip-systematic-variations",
        *extra,
    ]
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_configs(cfg, extra):
    from common.sample_paths import build_ul_sample_paths

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])
    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    outfile = output_dir / f"{cfg['era']}-{cfg['channels'].replace(',', '-', 1)}-config.yaml"

    print(f"[CONFIGS] Collecting ntuple_processor configs: era={cfg['era']} channels={cfg['channels']}")
    cmd = [
        "python",
        "shapes/produce_shapes.py",
        "--era", cfg["era"],
        "--channels", cfg["channels"],
        "--vs-jet-wp", cfg["vs_jet_wp"],
        "--vs-ele-wp", cfg["vs_ele_wp"],
        "--directory", paths.ntuples,
        "--et-friend-directory", paths.xsec_friends,
        "--mt-friend-directory", paths.xsec_friends,
        "--tt-friend-directory", paths.xsec_friends,
        "--em-friend-directory", paths.xsec_friends,
        "--output-file", str(outfile.with_suffix(".root")),
        "--collect-config-only",
        "--xrootd",
        "--config-output-file", str(outfile),
        *extra,
    ]
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_gen_tff_configs(cfg, extra):
    print("[GEN-TFF-CONFIGS] Regenerating TFF per-channel preselection YAMLs from unified config")
    print(f"[GEN-TFF-CONFIGS] era={cfg['era']} channels={cfg['channels']}")
    cmd = ["python", "config/generate_tff_configs.py", "--era", cfg["era"], "--channels", cfg["channels"]]
    return run_plain(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_presel(cfg, extra):
    # Phase 6e note (STATUS.md "## Phase 6e"): this used to also pass
    # `--columns <output_features>`, an argument preselection.py's argparse
    # doesn't define at all (it reads output_features from the config file
    # itself) -- that made every real PRESEL invocation fail with
    # "unrecognized arguments". Removed.
    print(f"[PRESEL] Running TauFakeFactors preselection: era={cfg['era']} channels={cfg['channels']}")
    for channel in cfg["channels"].split(","):
        print(f"[PRESEL] Processing channel {channel}")
        cmd = [
            "python",
            "TauFakeFactors/preselection.py",
            "--config-file", f"TauFakeFactors/configs/smhtt_ul/{cfg['era']}/preselection_{channel}.yaml",
            "--nthreads", str(cfg["nthreads"]),
            *extra,
        ]
        result = run_conda(
            cmd, env_overrides={"PYTHONPATH": f"{os.environ.get('PYTHONPATH', '')}:{REPO_ROOT / 'TauFakeFactors'}"}
        )
        if result.returncode != 0:
            return result.returncode
    return 0


def mode_ff(cfg, extra):
    # Phase 6e note: TauFakeFactors/configs/smhtt_ul/{era}/ ships one config
    # PER CHANNEL (fake_factors_et.yaml, fake_factors_mt.yaml, ...), never a
    # joined-multi-channel file -- the old default here
    # (`fake_factors_{channels}.yaml`) only ever matched a real file when
    # channels was a single channel. Now loops per channel, same as PRESEL.
    # cfg["ff_config"] (if set) still overrides for a single explicit file.
    print(f"[FF] Running TauFakeFactors fake factor calculation: era={cfg['era']} channels={cfg['channels']}")
    env_overrides = {"PYTHONPATH": f"{os.environ.get('PYTHONPATH', '')}:{REPO_ROOT / 'TauFakeFactors'}"}
    if cfg["ff_config"]:
        cmd = ["python", "TauFakeFactors/ff_calculation.py", "--config-file", cfg["ff_config"], *extra]
        return run_plain(cmd, env_overrides=env_overrides).returncode
    for channel in cfg["channels"].split(","):
        cmd = [
            "python", "TauFakeFactors/ff_calculation.py",
            "--config-file", f"TauFakeFactors/configs/smhtt_ul/{cfg['era']}/fake_factors_{channel}.yaml",
            *extra,
        ]
        result = run_plain(cmd, env_overrides=env_overrides)
        if result.returncode != 0:
            return result.returncode
    return 0


def mode_ff_corr(cfg, extra):
    # Phase 6e note: same per-channel-file issue as FF above, plus the old
    # default filename prefix was wrong (`ff_corrections_{ch}.yaml` -- the
    # real files are named `corrections_{ch}.yaml`), so this mode's default
    # never pointed at a file that exists. Fixed; cfg["ff_corr_config"] still
    # overrides for a single explicit config file.
    print(f"[FF-CORR] Running TauFakeFactors fake factor corrections: era={cfg['era']} channels={cfg['channels']}")
    env_overrides = {"PYTHONPATH": f"{os.environ.get('PYTHONPATH', '')}:{REPO_ROOT / 'TauFakeFactors'}"}
    if cfg["ff_corr_config"]:
        cmd = ["python", "TauFakeFactors/ff_corrections.py", "--config-file", cfg["ff_corr_config"], *extra]
        return run_plain(cmd, env_overrides=env_overrides).returncode
    for channel in cfg["channels"].split(","):
        cmd = [
            "python", "TauFakeFactors/ff_corrections.py",
            "--config-file", f"TauFakeFactors/configs/smhtt_ul/{cfg['era']}/corrections_{channel}.yaml",
            *extra,
        ]
        result = run_plain(cmd, env_overrides=env_overrides)
        if result.returncode != 0:
            return result.returncode
    return 0


def mode_ff_measure(cfg, extra):
    print(f"[FF-MEASURE] Running the full TauFakeFactors FF measurement chain: era={cfg['era']} channels={cfg['channels']}")
    print("[FF-MEASURE] (GEN-TFF-CONFIGS -> PRESEL -> FF -> FF-CORR, see run_fake_factor_measurement.py)")
    cmd = [
        "python", "run_fake_factor_measurement.py",
        "--era", cfg["era"],
        "--channels", cfg["channels"],
        "--nthreads", str(cfg["nthreads"]),
        *extra,
    ]
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_train_dataset(cfg, extra):
    # Local (non-condor) entry point for the dataset-preparation step of the
    # training pipeline. Plain Python, no law/luigi scheduler involved -- see
    # STATUS.md "## Phase 6c": trainings/create_training_dataset.py has never
    # used law (confirmed via git history + grep), so this mode is just a
    # discoverable wrapper around the script's existing plain-Python CLI,
    # mirroring condor/submit_training.py's direct-condor equivalent
    # (Phase 2c) for interactive/local use instead of batch submission.
    train_config = os.environ.get("TRAIN_CONFIG")
    if not train_config:
        print(
            "ERROR: TRAIN_CONFIG must be set to a per-(channel,era) training "
            "dataset config YAML (see trainings/create_training_dataset.py --config).",
            file=sys.stderr,
        )
        return 1
    base_dataset_dir = os.environ.get("BASE_DATASET_DIR", f"/ceph/{os.environ.get('USER', '')}/smhtt_ul_new/training_datasets")
    common_setup_config = os.environ.get("COMMON_SETUP_CONFIG", "")
    print(f"[TRAIN-DATASET] Building training dataset from {train_config} -> {base_dataset_dir}")

    cmd = [
        "python", "trainings/create_training_dataset.py",
        "--config", train_config,
        "--base-dataset-directory", base_dataset_dir,
    ]
    if common_setup_config:
        cmd += ["--common-setup-config", common_setup_config]
    cmd += extra
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_train(cfg, extra):
    # NOTE (Phase 6c / STATUS.md "## Phase 6c"): the uncertainty-aware-training
    # submodule's own `law run ...` workflow is a deliberate exception, not an
    # oversight -- Phase 6c decided to leave it untouched (submodule-internals
    # boundary: run.py carries zero task-graph logic of its own here, it only
    # forwards parameters to the submodule's own law CLI, same as PRESEL/FF/
    # FF-CORR shelling out to TauFakeFactors' own scripts). Only
    # create_training_dataset.py -- which never used law -- got a law-free
    # entry point, see mode_train_dataset above / TRAIN-DATASET mode.
    train_tag = os.environ.get("TRAIN_TAG", "260507")
    train_task = os.environ.get("TRAIN_TASK", "RunAllCENNTConfusionMatrixWorkflow")
    cuda_device = os.environ.get("CUDA_DEVICE", "0,1")
    workers = os.environ.get("WORKERS", "2")
    dataset_dir = os.environ.get("DATASET_DIR", "/ceph/sgiappic/Htt_training/cennt_folds/coarse")
    uat_config_dir = os.environ.get(
        "UAT_CONFIG_DIR", "/work/sgiappic/smhtt_ul/trainings/uncertainty-aware-training/datasets/smhtt/run3-coarse"
    )
    print(f"[TRAIN] task={train_task} tag={train_tag} channels={cfg['channels']}")

    uat_dir = REPO_ROOT / "trainings" / "uncertainty-aware-training"
    if not uat_dir.is_dir():
        print("ERROR: trainings/uncertainty-aware-training not found", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{env.get('PYTHONPATH', '')}:{REPO_ROOT}"
    subprocess.run(["law", "index", "-v"], cwd=str(uat_dir), env=env, check=True)

    for channel in cfg["channels"].split(","):
        print(f"[TRAIN] Running {train_task} for channel {channel}")
        cmd = [
            "law", "run", train_task,
            "--workers", workers,
            "--local-scheduler",
            "--version", f"{train_tag}_{channel}",
            "--log-level", "INFO",
            "--cuda-device", cuda_device,
            "--no-lock",
            f"--dataset-directory={dataset_dir}/{channel}/",
            f"--base-config-file={uat_config_dir}/smhtt_{channel}.yaml",
        ]
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

    # Fallback order matches the old bash script's `${VAR:-default}` semantics
    # exactly: an explicit --flag wins, else an inherited environment variable
    # (e.g. `ERA=2024 NTUPLETAG=... python3 run.py SHAPES`, same invocation
    # style the bash version supported since MODE/ERA/etc. were plain shell
    # variables), else the hardcoded default.
    channels = env_or(args.channels, "CHANNELS", "et,mt,tt")
    vs_ele_wp_default = "Tight" if channels == "et" else "VVLoose"

    cfg = {
        "era": env_or(args.era, "ERA", "2022postEE"),
        "channels": channels,
        "vs_jet_wp": env_or(args.vs_jet_wp, "VS_JET_WP", "Medium"),
        "vs_ele_wp": env_or(args.vs_ele_wp, "VS_ELE_WP", vs_ele_wp_default),
        "ntupletag": env_or(args.ntupletag, "NTUPLETAG", ""),
        "tag": env_or(args.tag, "TAG", ""),
        "output_dir": env_or(args.output_dir, "OUTPUT_DIR", "output"),
        "nthreads": env_or(args.nthreads, "NTHREADS", "4"),
        "nprocs": env_or(args.nprocs, "NPROCS", "1"),
        "presel_dir": env_or(args.presel_dir, "PRESEL_DIR", ""),
        "ff_friends_dir": env_or(args.ff_friends_dir, "FF_FRIENDS_DIR", ""),
        "ff_config": env_or(args.ff_config, "FF_CONFIG", ""),
        "ff_corr_config": env_or(args.ff_corr_config, "FF_CORR_CONFIG", ""),
    }

    needs_ntupletag = mode in ("XSEC", "SHAPES", "SHAPES-NOSYS", "TRAIN-SHAPES", "CONFIGS")
    if needs_ntupletag and not cfg["ntupletag"]:
        print("ERROR: NTUPLETAG must be set (CROWN ntuple tag, e.g. htt_260417_2022-23).", file=sys.stderr)
        return 1

    if mode == "XSEC":
        return mode_xsec(cfg, extra)
    if mode in ("SHAPES", "SHAPES-NOSYS"):
        return mode_shapes(cfg, extra, mode)
    if mode == "PLOT":
        return mode_plot(cfg, extra)
    if mode == "TRAIN-SHAPES":
        return mode_train_shapes(cfg, extra)
    if mode == "CONFIGS":
        return mode_configs(cfg, extra)
    if mode == "GEN-TFF-CONFIGS":
        return mode_gen_tff_configs(cfg, extra)
    if mode == "PRESEL":
        return mode_presel(cfg, extra)
    if mode == "FF":
        return mode_ff(cfg, extra)
    if mode == "FF-CORR":
        return mode_ff_corr(cfg, extra)
    if mode == "FF-MEASURE":
        return mode_ff_measure(cfg, extra)
    if mode == "TRAIN":
        return mode_train(cfg, extra)
    if mode == "TRAIN-DATASET":
        return mode_train_dataset(cfg, extra)

    raise AssertionError(f"unhandled mode {mode!r}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
