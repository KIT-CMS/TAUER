#!/usr/bin/env python3
"""
TauKITFlow -- SM H->tautau analysis framework, main entry point.

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
    PRESEL        Run the preselection (signals + backgrounds, per channel) into
                  --presel-dir, defaulting to
                  build_shape_output_paths(NTUPLETAG).preselection -- TauKITFlow's
                  own (shapes/preselect.py), read from that same default by both
                  SHAPES (--presel-dir) and FF/FF-CORR (--ff-input-dir)
    FF            Run TauFakeFactors fake factor calculation (per channel)
    FF-CORR       Run TauFakeFactors fake factor corrections (per channel)
    FF-MEASURE    Standalone TauFakeFactors measurement chain (GEN-TFF-CONFIGS ->
                  TauFakeFactors' OWN preselection.py -> FF -> FF-CORR). Note its
                  preselection step is TauFakeFactors', NOT run.py's PRESEL above --
                  in this pipeline use PRESEL then FF/FF-CORR --ff-input-dir instead.
    TRAIN         Run NN training via law (uncertainty-aware-training)
    TRAIN-DATASET Build training feather folds from ROOT shapes (plain Python, no law/condor)

Note on conda activation (see common/conda_env.py's module docstring for the
reasoning): the modes that used `check_env()` in the bash version --
XSEC, SHAPES/SHAPES-NOSYS, TRAIN-SHAPES, CONFIGS -- activate the
`taukitflow` conda env before running their python command, exactly as
before. PRESEL activates `fake_factors` instead (it reuses TauFakeFactors'
helper modules, whose deps -- ruamel.yaml, XRootD-client -- `taukitflow`
does not declare). GEN-TFF-CONFIGS/FF/FF-CORR/TRAIN do not (same as the bash version --
they run in whatever environment this script itself is invoked under). PLOT
used to require a separate `environment-plotting.yml` (`taukitflow-plotting`)
env just to get ROOT -- `environment.yml` now declares `root` directly
(condor/submit_plotting.py's jobs already ran PLOT under plain `taukitflow`
successfully, which is what confirmed ROOT already worked there), so PLOT
now activates the one `taukitflow` env too; the separate env/yml no longer
exist.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
# TauFakeFactors/ too: config/logging_setup_configs.py imports its CustomLogging
# package, so this script's own imports below need it -- pythonpath_with_tff()
# only fixes up the *child* processes' environment.
sys.path.insert(1, str(REPO_ROOT / "TauFakeFactors"))
from common.conda_env import run_in_conda  # noqa: E402
from config.analysis import ff_config_era  # noqa: E402

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
  TAG                Run-tag, distinct from NTUPLETAG; defaults to NTUPLETAG.
                      Used by SHAPES/SHAPES-NOSYS/PLOT to nest output under
                      output/{TAG}/{ss-os,ff}/{era}/{channel}/shapes.root.
                      The default already makes an ss-os run and a later
                      --ff-friends-dir run for the same NTUPLETAG share a
                      tree (so the ff run finds and hadd's onto the ss-os
                      run's output instead of redoing it) -- only set this
                      explicitly for a second, independent run that should
                      NOT build on the earlier one.

Optional:
  ERA              (default: 2022postEE)
  CHANNELS         (default: et,mt,tt)
  VS_JET_WP        (default: Medium)
  VS_ELE_WP        (default: per-channel, matching smhtt_ul's Run3 configs --
                    Tight for et, VVLoose otherwise; set this to force the
                    same WP for every channel instead)
  FORCE_LEGACY_CUTS  Set to 1 to never select on CROWN's precomputed selection
                    masks (presel_mask/sel_os/sel_ss/ff_*) and always build the
                    cuts as strings from config/cuts.yaml. Same as
                    --force-legacy-cuts. Only needed for A/B validation of the
                    two paths: PRESEL/SHAPES detect the masks per input and fall
                    back to the cut strings automatically on old ntuples.
  MASK_FRIENDS_DIR   Base dir of CROWN's selection-mask FRIEND trees, for
                    productions that wrote the masks next to the ntuples
                    (CROWN selection_friends.py) rather than into them
                    (selection_config.py). Same as --mask-friends-dir. Unset
                    for masks-in-the-ntuple and maskless productions: PRESEL
                    and SHAPES detect both without any flag.
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
        description="TauKITFlow -- SM H->tautau analysis framework",
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
    parser.add_argument("--nworkers", default=None)
    parser.add_argument("--nprocs", default=None)
    parser.add_argument("--output-dir", dest="output_dir", default=None)
    parser.add_argument("--ff-friends-dir", dest="ff_friends_dir", default=None)
    parser.add_argument("--ff-config", dest="ff_config", default=None)
    parser.add_argument("--ff-corr-config", dest="ff_corr_config", default=None)
    parser.add_argument(
        "--presel-dir", dest="presel_dir", default=None,
        help="The central preselection tree: PRESEL writes it, SHAPES/"
             "SHAPES-NOSYS/TRAIN-SHAPES read it. Defaults on both sides to "
             "build_shape_output_paths(ntupletag).preselection "
             "(/ceph/$USER/TauKITFlow_shapes/$NTUPLETAG/preselection), so "
             "SHAPES picks up PRESEL's output automatically. Pass an empty "
             "string to make SHAPES read raw CROWN ntuples instead.",
    )
    parser.add_argument(
        "--force-legacy-cuts", dest="force_legacy_cuts", action="store_true", default=None,
        help="Never select on CROWN's precomputed selection-mask branches (presel_mask, "
             "sel_os/sel_ss, ff_*); always build the cuts as strings from config/cuts.yaml. "
             "Passed through to shapes/preselect.py (PRESEL) and shapes/produce_shapes.py "
             "(SHAPES/SHAPES-NOSYS/TRAIN-SHAPES/CONFIGS). Without it those tools detect the "
             "masks per input themselves and fall back automatically on old, maskless "
             "ntuples -- this flag is the A/B-validation escape hatch, not something a "
             "normal run needs. Env: FORCE_LEGACY_CUTS=1.",
    )
    parser.add_argument(
        "--mask-friends-dir", dest="mask_friends_dir", default=None,
        help="Base dir of CROWN's selection-mask FRIEND trees, for productions that wrote the "
             "masks (presel_mask, sel_os/sel_ss, ff_*) next to the ntuples "
             "(CROWN selection_friends.py) instead of into them (selection_config.py), e.g. "
             "/store/user/$USER/CROWN/ntuples/$NTUPLETAG/CROWNFriends/selection/. Passed to "
             "PRESEL (shapes/preselect.py --mask-friends) and, when SHAPES reads raw CROWN "
             "ntuples, to shapes/produce_shapes.py as an extra --{channel}-friend-directory. "
             "Leave unset for masks-in-the-ntuple or maskless productions -- both are detected "
             "and handled without it. Env: MASK_FRIENDS_DIR.",
    )
    parser.add_argument(
        "--ff-input-dir", dest="ff_input_dir", default=None,
        help="For FF/FF-CORR: override common_settings.yaml's file_path/output_path "
             "(via a generated tmp config, TFF's real YAML on disk is never touched) "
             "to point at a central-preselection dir (e.g. "
             "build_shape_output_paths(ntupletag).preselection) instead of TFF's own "
             "preselection.py output.",
    )
    return parser


def parse_args(argv=None):
    parser = make_parser()
    args, extra = parser.parse_known_args(argv)
    return args, extra


def _truthy(value) -> bool:
    """Interpret an env-var-or-flag value as a boolean.

    `--force-legacy-cuts` sets True; the env-var fallback delivers a string,
    where the usual "0"/"false"/"no"/"" spellings must mean *off* (an
    inherited `FORCE_LEGACY_CUTS=0` meaning "on" would be a nasty surprise).
    """
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


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


def run_conda(cmd_args, env_overrides=None, conda_env=None):
    kwargs = {"cwd": REPO_ROOT, "env_overrides": env_overrides, "check": False}
    if conda_env:
        kwargs["conda_env"] = conda_env
    return run_in_conda(["nice", "-n", "19", *cmd_args], **kwargs)


def crown_friend_tag(path):
    """CROWN friend tag of `path`: the segment after CROWNFriends/CROWNMultiFriends.

    Mirrors shapes/utils.py::friend_tag (and ntuple_processor's booking), kept
    local because shapes.utils imports ntuple_processor/ROOT, which this driver
    deliberately never loads. Falls back to the last path segment.
    """
    segments = [s for s in str(path).split("/") if s]
    for marker in ("CROWNFriends", "CROWNMultiFriends"):
        if marker in segments:
            i = segments.index(marker)
            if i + 1 < len(segments):
                return segments[i + 1]
    return segments[-1] if segments else ""


def friend_directory_args(xsec_friends, mask_friends_dir="", ff_friends_dir=""):
    """Friend-directory arguments for shapes/produce_shapes.py.

    The generic, "inclusive" friends go into one --{channel}-friend-directory
    occurrence per channel, listing EVERY friend base dir that channel needs:
    produce_shapes.py declares those options as nargs="+" without
    action="append", so a second occurrence of the same flag *replaces* the
    first and listing the dirs together is the only way to attach more than
    one friend per channel.

    * xsec friends -- every channel, always (MC weight columns).
    * selection-mask friends -- every channel, when CROWN wrote the masks as a
      friend tree (selection_friends.py) instead of into the ntuple. They are
      what makes detect_masks() see the masks and what the booked cut
      expressions then read (unqualified `presel_mask`/`sel_*`/`ff_*`).

    Fake-factor friends go into the same per-channel lists (et/mt/tt only --
    em has no fake factors and the FF production writes no files for it), but
    their ROLE is declared separately with --ff-friends-tag, which carries the
    CROWN friend tag of the FF directory. filter_friends() uses that to drop
    them for signal samples instead of guessing from the directory being
    *named* something like "fake_factors_...".
    """
    friend_dirs = {ch: [xsec_friends] for ch in ("et", "mt", "tt", "em")}
    if mask_friends_dir:
        for ch in friend_dirs:
            friend_dirs[ch].append(mask_friends_dir)
    if ff_friends_dir:
        for ch in ("et", "mt", "tt"):
            friend_dirs[ch].append(ff_friends_dir)
    args = [
        arg
        for ch, dirs in friend_dirs.items()
        for arg in (f"--{ch}-friend-directory", *dirs)
    ]
    if ff_friends_dir:
        args += ["--ff-friends-tag", crown_friend_tag(ff_friends_dir)]
    return args


def mode_xsec(cfg, extra):
    from common.sample_paths import build_ul_sample_paths

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])
    print(f"[XSEC] Building cross-section friend trees for {cfg['ntupletag']}")
    if cfg["era"].startswith("2024") or cfg["era"].startswith("2025") or cfg["era"].startswith("2026"):
        datasets_json = "datasets/nanoAOD_v15/datasets.json"
    else:
        datasets_json = "datasets/nanoAOD_v12/datasets.json"

    cmd = [
        "python",
        "xsec/build_friend_tree.py",
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

    # Nested output/{tag}/{qcd-label}/{era}/{channels}/shapes.root -- tag
    # defaults to ntupletag (see cfg["tag"] construction above), so an ss-os
    # run and a later --ff-friends-dir run land in the same tree by default
    # and the ff run can find the ss-os run's output below without any extra
    # config. qcd-label mirrors which estimation --ff-friends-dir selects
    # (same "ff" if ff_friends_dir else "ss-os" logic as estimation_args
    # below).
    channels_label = cfg["channels"].replace(",", "-", 1)
    qcd_label = "ff" if cfg["ff_friends_dir"] else "ss-os"
    run_dir = Path(cfg["output_dir"]) / cfg["tag"] / qcd_label / cfg["era"] / channels_label
    run_dir.mkdir(parents=True, exist_ok=True)
    outfile = run_dir / "shapes.root"

    extra_args = []
    if cfg["ff_friends_dir"]:
        extra_args += ["--ff-type", "fake_factor"]

    # Selection-mask friends only when reading raw CROWN ntuples: the
    # preselection tree carries the masks as ordinary branches (PRESEL keeps
    # them in its Snapshot), so a --presel-dir run must not look for a friend
    # next to it.
    friend_args = friend_directory_args(
        paths.xsec_friends,
        mask_friends_dir="" if cfg["presel_dir"] else cfg["mask_friends_dir"],
        ff_friends_dir=cfg["ff_friends_dir"],
    )

    directory_args = ["--directory", paths.ntuples]
    if cfg["presel_dir"]:
        # --directory and --presel-dir are mutually exclusive in
        # shapes/produce_shapes.py -- now that --presel-dir actually exists
        # there (it didn't before; this passthrough was dead/would have
        # crashed with "unrecognized arguments" the moment PRESEL_DIR was
        # ever set), drop --directory instead of passing both.
        directory_args = ["--presel-dir", cfg["presel_dir"]]

    if mode == "SHAPES-NOSYS":
        extra_args.append("--skip-systematic-variations")

    if not os.environ.get("DNN_FRIENDS_DIR"):
        extra_args.append("--no-dnn-categorization")

    if cfg["vs_ele_wp"]:
        extra_args += ["--vs-ele-wp", cfg["vs_ele_wp"]]

    if cfg["force_legacy_cuts"]:
        extra_args.append("--force-legacy-cuts")

    def _produce(output_file, ff_only=False):
        cmd = [
            "python",
            "shapes/produce_shapes.py",
            "--era", cfg["era"],
            "--channels", cfg["channels"],
            "--vs-jet-wp", cfg["vs_jet_wp"],
            # Scopes ntuple_processor's on-disk validation_database/ cache by
            # ntupletag (default "default" otherwise) -- without this, switching
            # --ntupletag reuses another tag's stale, tag-specific file list
            # under the same era_channel_dataset.yaml cache key and every real
            # lookup against the new tag's (different) file paths raises
            # "File ... not found in validation results." (booking.py:361).
            "--validation-tag", cfg["ntupletag"],
            "--validation-db-root", cfg["validation_dir"],
            *directory_args,
            *friend_args,
            "--output-file", str(output_file),
            "--num-processes", str(cfg["nprocs"]),
            "--num-threads", str(cfg["nthreads"]),
            # Only use xrootd for raw CROWN ntuples (served by the CMS xrootd
            # endpoint). Preselected files live on the user's /ceph space which
            # that server does not serve, so skip --xrootd there.
            *(["--xrootd"] if not cfg["presel_dir"] else []),
            *extra_args,
            *(["--ff-only"] if ff_only else []),
            *extra,
        ]
        return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()})

    if qcd_label == "ff":
        # Same tag/era/channels, ss-os label -- the sibling non-FF run this
        # ff run builds on instead of redoing, IF it already exists (same
        # ntupletag/tag by default -- see cfg["tag"]).
        ss_os_file = Path(cfg["output_dir"]) / cfg["tag"] / "ss-os" / cfg["era"] / channels_label / "shapes.root"
        if ss_os_file.exists():
            print(f"[{mode}] Reusing existing ss-os shapes at {ss_os_file} -- booking only the "
                  f"FF-weighted variations (--ff-only) and merging onto a copy of it, instead of "
                  f"redoing the full (expensive) shape production.")
            ff_only_file = run_dir / "shapes_ff_only.root"
            result = _produce(ff_only_file, ff_only=True)
            if result.returncode != 0:
                return result.returncode
            # hadd merges histograms present in both inputs and copies over
            # histograms unique to either -- correct here because ss_os_file
            # and ff_only_file have disjoint histogram-name sets by
            # construction (--ff-only only books what a normal run books
            # when args.ff_type != "none", which a plain ss-os run never
            # booked in the first place).
            hadd_result = run_conda(
                ["hadd", "-f", str(outfile), str(ss_os_file), str(ff_only_file)],
                env_overrides={"PYTHONPATH": pythonpath_with_tff()},
            )
            if hadd_result.returncode != 0:
                return hadd_result.returncode
            ff_only_file.unlink(missing_ok=True)
        else:
            print(f"[{mode}] No existing ss-os shapes found at {ss_os_file}; producing full shapes "
                  f"(including FF variations) from scratch.")
            result = _produce(outfile, ff_only=False)
            if result.returncode != 0:
                return result.returncode
    else:
        print(f"[{mode}] Producing shapes: era={cfg['era']} channels={cfg['channels']}")
        result = _produce(outfile, ff_only=False)
        if result.returncode != 0:
            return result.returncode

    print(f"[{mode}] Running post-processing estimations on {outfile}")
    # Matches smhtt_ul: the fake-factor method (--do-ff) is only usable once
    # FF friend trees are available; without them, fall back to the same
    # same-sign-data to opposite-sign-data QCD multijet extrapolation
    # (--do-qcd, shapes/estimations/qcd.py:qcd_estimation) smhtt_ul used by
    # default. Both read from the `same_sign` histograms produce_shapes.py
    # already books unconditionally for et/mt/tt (see its `_book(... ,
    # [variations.same_sign])` calls), so no shape-production change is
    # needed -- only which estimation to run on top of them.
    estimation_args = ["--do-ff"] if cfg["ff_friends_dir"] else ["--do-qcd"]
    # Merges the "qqh" (pure VBF) and "vh_as_qqh" (hadronic-decay WminusH/WplusH/ZH
    # events reclassified as qqH via HTXS_stage_0, see shapes/produce_shapes.py)
    # histograms produced above back into one physical qqH125 shape.
    estimation_args.append("--do-qqh-procs")
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
    # Same nested layout mode_shapes writes to (output/{tag}/{qcd-label}/{era}/{channels}/shapes.root).
    channels_label = cfg["channels"].replace(",", "-", 1)
    qcd_label = "ff" if cfg["ff_friends_dir"] else "ss-os"
    outfile = Path(cfg["output_dir"]) / cfg["tag"] / qcd_label / cfg["era"] / channels_label / "shapes.root"
    # plot_shapes_control.py itself builds <plot_dir>/<era>/<channel>/<ext>/...
    # -- do not bake era into plot_dir here, or it gets nested twice. tag/
    # qcd-label are nested here (mirroring output/'s layout) so ss-os and ff
    # plots for the same era/channel don't collide, and so the validation
    # cache lookup implied by a shared tag stays consistent between them.
    plot_dir = f"/web/sgiappic/public_html/CMS_HTT/{cfg['tag']}/{qcd_label}/"
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
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_train_shapes(cfg, extra):
    from common.sample_paths import build_ul_sample_paths

    paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])
    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    outfile = output_dir / f"{cfg['era']}-{cfg['channels'].replace(',', '-', 1)}-training-shapes.root"

    print(f"[TRAIN-SHAPES] Producing training shapes: era={cfg['era']} channels={cfg['channels']}")
    vs_ele_wp_args = ["--vs-ele-wp", cfg["vs_ele_wp"]] if cfg["vs_ele_wp"] else []
    legacy_cuts_args = ["--force-legacy-cuts"] if cfg["force_legacy_cuts"] else []
    cmd = [
        "python",
        "shapes/produce_shapes.py",
        "--era", cfg["era"],
        "--channels", cfg["channels"],
        "--vs-jet-wp", cfg["vs_jet_wp"],
        "--validation-tag", cfg["ntupletag"],
        *vs_ele_wp_args,
        "--directory", paths.ntuples,
        *friend_directory_args(paths.xsec_friends, mask_friends_dir=cfg["mask_friends_dir"]),
        "--output-file", str(outfile),
        "--num-processes", str(cfg["nprocs"]),
        "--num-threads", str(cfg["nthreads"]),
        "--xrootd",
        "--skip-systematic-variations",
        *legacy_cuts_args,
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
    vs_ele_wp_args = ["--vs-ele-wp", cfg["vs_ele_wp"]] if cfg["vs_ele_wp"] else []
    legacy_cuts_args = ["--force-legacy-cuts"] if cfg["force_legacy_cuts"] else []
    cmd = [
        "python",
        "shapes/produce_shapes.py",
        "--era", cfg["era"],
        "--channels", cfg["channels"],
        "--vs-jet-wp", cfg["vs_jet_wp"],
        "--validation-tag", cfg["ntupletag"],
        *vs_ele_wp_args,
        "--directory", paths.ntuples,
        *friend_directory_args(paths.xsec_friends, mask_friends_dir=cfg["mask_friends_dir"]),
        "--output-file", str(outfile.with_suffix(".root")),
        "--collect-config-only",
        "--xrootd",
        "--config-output-file", str(outfile),
        *legacy_cuts_args,
        *extra,
    ]
    return run_conda(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_gen_tff_configs(cfg, extra):
    print("[GEN-TFF-CONFIGS] Regenerating TFF per-channel preselection YAMLs from unified config")
    print(f"[GEN-TFF-CONFIGS] era={cfg['era']} channels={cfg['channels']}")
    cmd = ["python", "config/generate_tff_configs.py", "--era", cfg["era"], "--channels", cfg["channels"]]
    return run_plain(cmd, env_overrides={"PYTHONPATH": pythonpath_with_tff()}).returncode


def mode_presel(cfg, extra):
    """
    The analysis' preselection step: TauKITFlow's own, via
    shapes/preselect.py -- a full replacement for TauFakeFactors'
    preselection.py, which this pipeline does not use at all (that file is
    untouched on disk and still works for running TauFakeFactors standalone;
    see run_fake_factor_measurement.py's "presel" step, which is that
    separate standalone path).

    Writes ONE flat preselection tree to cfg["presel_dir"], which defaults to
    build_shape_output_paths(NTUPLETAG).preselection -- the same default
    SHAPES reads from, so the two line up without either being told where it
    is (--presel-dir/PRESEL_DIR overrides it on both sides). Consumed
    directly by BOTH shapes/produce_shapes.py (--presel-dir) and
    TauFakeFactors' ff_calculation.py/ff_corrections.py (--ff-input-dir, see
    mode_ff/mode_ff_corr) -- no second CROWN-shaped mirror of it is needed.
    """
    from common.sample_paths import build_shape_output_paths, build_ul_sample_paths

    ul_paths = build_ul_sample_paths(cfg["ntupletag"], cfg["era"])
    output_dir = cfg["presel_dir"] or build_shape_output_paths(cfg["ntupletag"]).preselection

    print(f"[PRESEL] Preselection: era={cfg['era']} channels={cfg['channels']} -> {output_dir}")
    for channel in cfg["channels"].split(","):
        print(f"[PRESEL] Processing channel {channel}")
        cmd = [
            "python", "shapes/preselect.py",
            "--era", cfg["era"],
            "--channel", channel,
            "--output-dir", output_dir,
            "--directory", ul_paths.ntuples,
            "--xsec-friends", ul_paths.xsec_friends,
            *(["--mask-friends", cfg["mask_friends_dir"]] if cfg["mask_friends_dir"] else []),
            "--nthreads", str(cfg["nthreads"]),
            "--nworkers", str(cfg["nworkers"]),
            *(["--force-legacy-cuts"] if cfg["force_legacy_cuts"] else []),
            *extra,
        ]
        # process_background_process() lazily imports TauFakeFactors'
        # helper.filters/helper.functions (gen-mode split + output naming,
        # reused so the output layout matches byte-for-byte), which need the
        # `fake_factors` env's deps (ruamel.yaml, XRootD-client) -- the
        # `taukitflow` env does not declare those in environment.yml.
        result = run_conda(
            cmd,
            env_overrides={"PYTHONPATH": f"{os.environ.get('PYTHONPATH', '')}:{REPO_ROOT / 'TauFakeFactors'}"},
            conda_env="fake_factors",
        )
        if result.returncode != 0:
            return result.returncode
    return 0


def _patched_ff_config(era: str, channel: str, config_kind: str, ff_input_dir: str) -> str:
    """
    For --ff-input-dir: build a tmp config dir containing an unmodified copy
    of TauFakeFactors/configs/smhtt_ul/{era}/{config_kind}_{channel}.yaml
    plus a *patched* common_settings.yaml (file_path/output_path overridden
    to ff_input_dir) -- TauFakeFactors/helper/functions.py::load_config()
    always looks for common_settings.yaml in the same directory as
    --config-file, so this is enough to redirect ff_calculation.py/
    ff_corrections.py's input glob without ever touching the real files
    under TauFakeFactors/configs/.
    """
    import shutil
    import tempfile
    import yaml

    # 2022preEE/2022postEE (and the 2023 halves) share one set of FF configs,
    # kept in the combined `2022` / `2023` directory -- see analysis.ff_config_era.
    src_dir = REPO_ROOT / "TauFakeFactors" / "configs" / "smhtt_ul" / ff_config_era(era)
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"tff_config_{era}_{channel}_"))

    with open(src_dir / "common_settings.yaml") as f:
        common_cfg = yaml.safe_load(f)
    common_cfg["file_path"] = ff_input_dir
    common_cfg["output_path"] = ff_input_dir
    with open(tmp_dir / "common_settings.yaml", "w") as f:
        yaml.safe_dump(common_cfg, f)

    config_src = src_dir / f"{config_kind}_{channel}.yaml"
    shutil.copy(config_src, tmp_dir / config_src.name)
    return str(tmp_dir / config_src.name)


def mode_ff(cfg, extra):
    # Phase 6e note: TauFakeFactors/configs/smhtt_ul/{era}/ ships one config
    # PER CHANNEL (fake_factors_et.yaml, fake_factors_mt.yaml, ...), never a
    # joined-multi-channel file -- the old default here
    # (`fake_factors_{channels}.yaml`) only ever matched a real file when
    # channels was a single channel. Now loops per channel.
    # cfg["ff_config"] (if set) still overrides for a single explicit file.
    print(f"[FF] Running TauFakeFactors fake factor calculation: era={cfg['era']} channels={cfg['channels']}")
    env_overrides = {"PYTHONPATH": f"{os.environ.get('PYTHONPATH', '')}:{REPO_ROOT / 'TauFakeFactors'}"}
    if cfg["ff_config"]:
        cmd = ["python", "TauFakeFactors/ff_calculation.py", "--config-file", cfg["ff_config"], *extra]
        return run_plain(cmd, env_overrides=env_overrides).returncode
    for channel in cfg["channels"].split(","):
        if cfg["ff_input_dir"]:
            config_file = _patched_ff_config(cfg["era"], channel, "fake_factors", cfg["ff_input_dir"])
        else:
            config_file = f"TauFakeFactors/configs/smhtt_ul/{ff_config_era(cfg['era'])}/fake_factors_{channel}.yaml"
        cmd = ["python", "TauFakeFactors/ff_calculation.py", "--config-file", config_file, *extra]
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
        if cfg["ff_input_dir"]:
            config_file = _patched_ff_config(cfg["era"], channel, "corrections", cfg["ff_input_dir"])
        else:
            config_file = f"TauFakeFactors/configs/smhtt_ul/{ff_config_era(cfg['era'])}/corrections_{channel}.yaml"
        cmd = ["python", "TauFakeFactors/ff_corrections.py", "--config-file", config_file, *extra]
        result = run_plain(cmd, env_overrides=env_overrides)
        if result.returncode != 0:
            return result.returncode
    return 0


def mode_ff_measure(cfg, extra):
    print(f"[FF-MEASURE] Running the full TauFakeFactors FF measurement chain: era={cfg['era']} channels={cfg['channels']}")
    print("[FF-MEASURE] (GEN-TFF-CONFIGS -> TauFakeFactors' own preselection.py -> FF -> FF-CORR,")
    print("[FF-MEASURE]  see run_fake_factor_measurement.py -- NOT run.py's PRESEL mode)")
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
    # forwards parameters to the submodule's own law CLI, same as FF/
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
    subprocess.run(["nice", "-n", "19", "law", "index", "-v"], cwd=str(uat_dir), env=env, check=True)

    for channel in cfg["channels"].split(","):
        print(f"[TRAIN] Running {train_task} for channel {channel}")
        cmd = [
            "nice", "-n", "19",
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

    cfg = {
        "era": env_or(args.era, "ERA", "2022postEE"),
        "channels": channels,
        "vs_jet_wp": env_or(args.vs_jet_wp, "VS_JET_WP", "Medium"),
        # None (not a hardcoded "VVLoose"/"Tight") unless the user overrides it
        # via --vs-ele-wp/VS_ELE_WP: shapes/produce_shapes.py applies the
        # correct per-channel smhtt_ul Run3 default itself (Tight for et,
        # VVLoose otherwise, config.analysis.vs_ele_wp_for()) for every
        # channel in cfg["channels"], which a single value here can't do once
        # more than one channel is requested at once (e.g. the "et,mt,tt"
        # default).
        "vs_ele_wp": env_or(args.vs_ele_wp, "VS_ELE_WP", None),
        "ntupletag": env_or(args.ntupletag, "NTUPLETAG", ""),
        # Run-tag (distinct from --ntupletag): defaults to ntupletag itself
        # (filled in below, once ntupletag is known) so an ss-os run and a
        # later --ff-friends-dir run for the same ntupletag automatically
        # land in the same output/{tag}/{qcd-label}/... tree -- and the ff
        # run finds/hadd's onto the ss-os run's output -- with no extra
        # config needed. Only override --tag/TAG explicitly when you want a
        # second, independent SHAPES attempt for the same ntupletag that
        # should NOT reuse/build on an earlier run's output.
        "tag": env_or(args.tag, "TAG", None),
        # None (not a hardcoded "output"/CWD-relative "validation_database")
        # unless the user overrides via --output-dir/OUTPUT_DIR or
        # --presel-dir/PRESEL_DIR -- filled in below, once ntupletag is known,
        # from common.sample_paths.build_shape_output_paths(ntupletag), the
        # single source of truth for the unified
        # /ceph/$USER/TauKITFlow_shapes/$ntupletag/{preselection,crown,output,validation}
        # tree (replacing the previously scattered bare "output"/CWD-relative
        # "validation_database" defaults).
        "output_dir": env_or(args.output_dir, "OUTPUT_DIR", None),
        "nthreads": env_or(args.nthreads, "NTHREADS", "4"),
        # PRESEL only: how many sample jobs run concurrently, each with
        # `nthreads` ROOT threads (shapes/preselect.py --nworkers).
        "nworkers": env_or(args.nworkers, "NWORKERS", "4"),
        "nprocs": env_or(args.nprocs, "NPROCS", "1"),
        "presel_dir": env_or(args.presel_dir, "PRESEL_DIR", None),
        "validation_dir": None,
        "ff_friends_dir": env_or(args.ff_friends_dir, "FF_FRIENDS_DIR", ""),
        "ff_config": env_or(args.ff_config, "FF_CONFIG", ""),
        "ff_corr_config": env_or(args.ff_corr_config, "FF_CORR_CONFIG", ""),
        "ff_input_dir": env_or(args.ff_input_dir, "FF_INPUT_DIR", ""),
        # Empty unless the production shipped CROWN's selection masks as a
        # friend tree -- see --mask-friends-dir. Masks-in-the-ntuple and
        # maskless productions need no value here.
        "mask_friends_dir": env_or(args.mask_friends_dir, "MASK_FRIENDS_DIR", ""),
        # store_true with default=None so an unset flag still falls through to
        # the env var, matching every other option's `${VAR:-default}`
        # semantics above (a plain store_true would default to False and
        # shadow FORCE_LEGACY_CUTS).
        "force_legacy_cuts": _truthy(env_or(args.force_legacy_cuts, "FORCE_LEGACY_CUTS", None)),
    }

    needs_ntupletag = mode in (
        "XSEC", "SHAPES", "SHAPES-NOSYS", "TRAIN-SHAPES", "CONFIGS", "PRESEL",
    )
    if needs_ntupletag and not cfg["ntupletag"]:
        print("ERROR: NTUPLETAG must be set (CROWN ntuple tag, e.g. htt_260417_2022-23).", file=sys.stderr)
        return 1

    if cfg["ntupletag"]:
        from common.sample_paths import build_shape_output_paths

        shape_paths = build_shape_output_paths(cfg["ntupletag"])
        if cfg["tag"] is None:
            cfg["tag"] = cfg["ntupletag"]
        if cfg["output_dir"] is None:
            cfg["output_dir"] = shape_paths.output
        if cfg["presel_dir"] is None:
            # Default to the ONE central preselection tree,
            # /ceph/$USER/TauKITFlow_shapes/$ntupletag/preselection -- the same
            # path PRESEL writes to (mode_presel below) -- so SHAPES reads
            # PRESEL's output with no --presel-dir needed. Override with
            # --presel-dir/PRESEL_DIR (on PRESEL it moves the output, on
            # SHAPES the input); pass an empty string to opt out entirely and
            # go back to reading raw CROWN ntuples (mode_shapes's
            # `if cfg["presel_dir"]:` branch).
            cfg["presel_dir"] = shape_paths.preselection
        cfg["validation_dir"] = shape_paths.validation
    else:
        cfg["tag"] = cfg["tag"] or "default"
        cfg["output_dir"] = cfg["output_dir"] or "output"
        cfg["presel_dir"] = cfg["presel_dir"] or ""
        cfg["validation_dir"] = "validation_database"

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
