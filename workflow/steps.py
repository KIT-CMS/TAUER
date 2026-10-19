from __future__ import annotations

import getpass
import glob
import json
import os
import re
import shlex
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Callable

from common.sample_paths import build_shape_output_paths, output_run_dir, plot_output_dir
from condor.submit_taues_fit import DEFAULT_CATEGORIES
from common.analysis import ACTIVE_ANALYSIS, DATA_ERA_MERGE, ff_config_era

REPO_ROOT = Path(__file__).resolve().parent.parent
UAT = REPO_ROOT / "trainings/uncertainty-aware-training"
TRAIN_TASKS = {  # law wrapper task -> its .success files below the law output directory ({v} = law version <tag>_<channel>)
    "RunAllCENNTConfusionMatrixWorkflow": ["ConfusionMatrices_{v}/SMHtt/fold_combined/.success"],
    "RunAllCENNTWorkflow": ["CombinedModels_{v}/.success"],
    "RunAllCENNTTrainingWorkflow": ["CENNTTraining_{v}/SMHtt__fold0/.success", "CENNTTraining_{v}/SMHtt__fold1/.success"],
}
SETTINGS = Path.home() / ".config/tauer/settings.json"  # written by `tauer setup`
DEFAULT_CROWN_ANALYSIS = REPO_ROOT.parent / "KingMaker/CROWN/analysis_configurations/tau"
FF_CHANNELS = ("et", "mt", "tt")
NN_CHANNELS = ("et", "mt", "tt")  # channels of the DNN categorization
FRIEND_CONFIG = {"selection": "shapes_preparation", "ff": "sm_fake_factors"}
UNIT_FIELDS = {
    "era×channel": ("era", "channel"), "ffera×channel": ("ffera", "channel"), "era": ("era",),
    "channel": ("channel",), "era×category": ("era", "category"), "global": (),
}
ENV_LINES = {"tauer": "conda activate tauer", "cmssw": "source utils/setup_cmssw.sh"}


def settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def crown_analysis_dir():
    """KingMaker/CROWN/analysis_configurations/<CROWN analysis>: payloads go to its payloads/, its name is law's --analysis."""
    return Path(settings().get("crown_analysis_dir", DEFAULT_CROWN_ANALYSIS))


def kingmaker_dir():
    return crown_analysis_dir().parents[2]


@dataclass
class Step:
    name: str
    desc: str
    where: str  # condor | local | crown | handoff
    unit: str
    group: str  # menu group
    needs: tuple | Callable = ()
    params: tuple = ()
    channels: tuple | None = None
    check: str = "files"
    outputs: Callable | None = None  # (cfg, unit) -> glob patterns that must all match, None = not tracked
    inputs: Callable | None = None  # (cfg, unit) -> files whose mtime makes the outputs stale
    submitter: str | None = None
    argv: Callable | None = None  # (cfg, unit) -> submitter argv
    command: Callable | None = None  # (cfg, units) -> shell lines
    env: str = "tauer"


def opts(**kw):
    return [x for k, v in kw.items() if v for x in (f"--{k.replace('_', '-')}", str(v))]


def analysis_eras(cfg):
    # eras whose data is merged into another analysis era only exist as CROWN ntuples
    return [e for e in cfg["eras"] if not any(e in m for m in DATA_ERA_MERGE.values())]


def units(cfg, step):
    chans = [c for c in cfg["channels"] if c in (step.channels or cfg["channels"])]
    eras = cfg["eras"] if step.where == "crown" else analysis_eras(cfg)
    fferas = list(dict.fromkeys(ff_config_era(e) for e in eras))
    keys = {
        "era×channel": product(eras, chans), "ffera×channel": product(fferas, chans),
        "era": [(e,) for e in eras], "channel": [(c,) for c in chans],
        "era×category": product(eras, DEFAULT_CATEGORIES), "global": [()],
    }[step.unit]
    return [dict(zip(UNIT_FIELDS[step.unit], key)) for key in keys]


def label(u):
    return "/".join(u.values()) or "-"


def finalize(cfg):
    """Fill the derived/default keys every step reads."""
    cfg = {"analysis": ACTIVE_ANALYSIS, "user": getpass.getuser(), "ff_type": "fake_factor", "stxs_stage": "stage0", "extras": {}, **cfg}
    cfg["tag"] = cfg.get("tag") or cfg["ntupletag"]
    cfg["tag_arg"] = "" if cfg["tag"] == cfg["ntupletag"] else cfg["tag"]
    defaults = {"dc_analysis": "stxs_stage0_run3", "variable": "m_vis", "plot_variables": "m_vis,pt_1,pt_2,eta_1,eta_2,mt_1",
                "train_task": next(iter(TRAIN_TASKS)), "request_gpus": "1"}
    for key in ("selection_friend", "ff_friend", "additional_friends", "correction_tag", "process_selection", "special_analysis", "sample_list", "dc_analysis", "variable",
                "plot_variables", "fitdir", "dc_output_dir", "taues_fit_dir", "train_task", "request_gpus"):
        cfg[key] = cfg.get(key) or defaults.get(key, "")
    cfg["fitdir"] = cfg["fitdir"] or os.environ.get("FITDIR") or str(REPO_ROOT)
    cfg["dc_output_dir"] = cfg["dc_output_dir"] or f"{cfg['fitdir']}/output_{cfg['dc_analysis']}"
    paths = build_shape_output_paths(cfg["ntupletag"], user=cfg["user"])
    cfg["output_dir"] = paths.output
    cfg["taues_fit_dir"] = cfg["taues_fit_dir"] or f"{paths.base}/taues_fit"
    return cfg


def rep_era(cfg, ffera):
    return next(e for e in cfg["eras"] if ff_config_era(e) == ffera)


def shapes_file(cfg, u, qcd_label):
    return output_run_dir({**cfg, "era": u["era"]}, qcd_label, u["channel"]) / "shapes.root"


def qcd_label(cfg):
    return "ff" if cfg["ff_friend"] else "ss-os"


def shapes_path(cfg, u):
    return shapes_file(cfg, u, qcd_label(cfg))


def plot_files(cfg, u, qcd_label):
    plot_dir = plot_output_dir({**cfg, "era": u["era"]}, qcd_label)
    return [f"{plot_dir}{u['channel']}/Run{u['era']}_{u['channel']}__{v}.{ext}" for v in cfg["plot_variables"].split(",") for ext in ("png", "pdf")]


def gof_job(cfg, u):
    return f"{u['era']}_{u['channel']}_{cfg['variable']}"


def train_dir(cfg, u):
    # the law workflow hardcodes its output base (PRE_WORK in _law_CENNT_workflow.py), run.py passes no --directory
    base = re.search(r'PRE_WORK = "([^"]+)"', (UAT / "_law_CENNT_workflow.py").read_text()).group(1)
    return f"{base}routine_output/CENNTExperiments"


def train_outputs(cfg, u):
    return [f"{train_dir(cfg, u)}/{out.format(v=cfg['tag'] + '_' + u['channel'])}" for out in TRAIN_TASKS[cfg["train_task"]]]


def nn_sources(cfg, u):
    ch = u["channel"]
    return [(f"{train_dir(cfg, u)}/CombinedModels_{cfg['tag']}_{ch}/onnx_model/fold_combined/model.onnx", crown_analysis_dir() / f"payloads/DNN/{ch}/model.onnx")]


def ff_dir(cfg, u):
    return REPO_ROOT / "fake_factors/workdir" / cfg["tag"] / u["ffera"]


def btag_calc_dir(cfg, u):
    return REPO_ROOT / "btag_efficiencies/workdir" / cfg["ntupletag"] / u["era"] / (cfg["tag_arg"] or "") / u["channel"]


def ff_sources(cfg, u):
    ch = u["channel"]
    ctag = cfg.get("correction_tag") or "*"
    return [(f"{ff_dir(cfg, u)}/fake_factors/fake_factors_{ch}.json.gz", crown_analysis_dir() / f"payloads/fake_factors/sm/{u['ffera']}/fake_factors_{ch}.json.gz"),
            (f"{ff_dir(cfg, u)}/corrections/{ctag}/{ch}/FF_corrections_{ch}.json.gz", crown_analysis_dir() / f"payloads/fake_factors/sm/{u['ffera']}/FF_corrections_{ch}.json.gz")]


def btag_sources(cfg, u):
    return [(f"{btag_calc_dir(cfg, u)}/btag_efficiency.json.gz", crown_analysis_dir() / f"payloads/btag_efficiencies/{u['era']}/{u['channel']}/btag_efficiency.json.gz")]


def run_py(mode, cfg, us, *extra):
    grouped = {}
    for u in us:
        grouped.setdefault(u.get("era") or rep_era(cfg, u["ffera"]), []).append(u["channel"])
    return [shlex.join(["python", "run.py", mode, "--era", era, "--channels", ",".join(chs), *extra]) for era, chs in grouped.items()]


def crown_cmd(kind):
    def command(cfg, us):
        friend = [] if kind is None else ["--friend-tag", cfg[f"{kind}_friend"] or f"<{kind} friend tag>", "--friend-config", FRIEND_CONFIG[kind]]
        scopes = ",".join(dict.fromkeys(u["channel"] for u in us))
        return [f"cd {kingmaker_dir()} && source setup.sh KingMaker",
                shlex.join(["law", "run", "ProduceNtuples", "--analysis", crown_analysis_dir().name, "--config", "config", "--production-tag", cfg["ntupletag"],
                            "--sample-list", cfg["sample_list"] or "<sample list>", "--scopes", scopes, "--shifts", "All", "--workers", "50", *friend])]
    return command


def btag_ntuples_cmd(cfg, us):
    tag = cfg["ntupletag"] if cfg["ntupletag"].endswith("_btag") else f"{cfg['ntupletag']}_btag"
    return [f"# the ntuples {cfg['ntupletag']} have no jet vectors for the b-tag efficiencies: set measure_btag_efficiency = True in",
            f"# {crown_analysis_dir()}/config.py, produce new ntuples and select {tag} as ntuple tag of the b-tag steps",
            *crown_cmd(None)({**cfg, "ntupletag": tag}, us)]


def shapes_argv(cfg, u, ff=False, special=None):
    return ["--ntupletag", cfg["ntupletag"], "--eras", u["era"], "--channels", u["channel"], "--user", cfg["user"],
            *opts(selection_friend=cfg["selection_friend"], additional_friends=cfg["additional_friends"], stxs_stage=cfg["stxs_stage"], tag=cfg["tag_arg"],
                  process_selection=cfg.get("process_selection"), special_analysis=special or cfg.get("special_analysis")),
            *(["--ff-friend", cfg["ff_friend"], "--ff-type", cfg["ff_type"]] if ff else [])]


def estimations_argv(cfg, u, ff=False):
    return ["--ntupletag", cfg["ntupletag"], "--eras", u["era"], "--channels", u["channel"], "--user", cfg["user"],
            *opts(tag=cfg["tag_arg"], ff_friend=cfg["ff_friend"] if ff else None)]


def ff_argv(step_name):
    def argv(cfg, u):
        return ["--ntupletag", cfg["ntupletag"], "--eras", rep_era(cfg, u["ffera"]), "--channels", u["channel"], "--steps", step_name,
                "--split-by-channel", "--user", cfg["user"],
                *opts(selection_friend=cfg["selection_friend"] if step_name == "presel" else None, tag=cfg["tag_arg"],
                      additional_friends=cfg["additional_friends"] if step_name == "presel" else None, correction_tag=cfg.get("correction_tag") if step_name == "ff-corr" else None)]
    return argv


def btag_argv(step_name):
    def argv(cfg, u):
        return ["--ntupletag", cfg["ntupletag"], "--steps", step_name, "--eras", u["era"], "--user", cfg["user"],
                *opts(selection_friend=cfg["selection_friend"] if step_name == "presel" else None, tag=cfg["tag_arg"],
                      additional_friends=cfg["additional_friends"] if step_name == "presel" else None),
                *(["--channels", u["channel"]] if step_name == "presel" else [])]
    return argv


def shapes_arg(cfg, u):
    return str(shapes_path(cfg, u))


def datacard_cmd(cfg, us):
    ff = ["--ff-type", cfg["ff_type"]] if cfg["ff_friend"] else []
    return [f"export FITDIR={cfg['fitdir']}"] + [
        shlex.join(["python3", "datacards/produce_datacard.py", u["era"], u["channel"], cfg["dc_analysis"], shapes_arg(cfg, u), "--variable", cfg["variable"],
                    "--stxs-stage", cfg["stxs_stage"], "--output-dir", cfg["dc_output_dir"], *ff])
        for u in us]


def gof_cmd(cfg, us):
    # run_gof.py builds its own gof datacard and workspace (stage0, no extra options)
    return [f"export FITDIR={cfg['fitdir']}"] + [
        shlex.join(["python3", "datacards/run_gof.py", u["era"], u["channel"], cfg["variable"], shapes_arg(cfg, u), "saturated", "20", "0", "4"]) for u in us]


def workspace_cmd(cfg, us):
    return [f"export FITDIR={cfg['fitdir']}", shlex.join(["python3", "datacards/produce_workspace.py", ",".join(dict.fromkeys(u["era"] for u in us)), cfg["dc_analysis"], "4"])]


def impacts_cmd(cfg, us):
    return [f"export FITDIR={cfg['fitdir']}"] + [shlex.join(["python3", "datacards/run_impacts.py", u["era"], u["channel"], cfg["variable"], "4"]) for u in us]


def handoff_copies(sources):
    """(cfg, units) -> [(newest TAUER output, CROWN payload)] of the outputs that exist."""
    def copies(cfg, us):
        found = [(sorted(glob.glob(src), key=os.path.getmtime), dst) for u in us for src, dst in sources(cfg, u)]
        return [(srcs[-1], str(dst)) for srcs, dst in found if srcs]
    return copies


def training_dir(cfg):
    return build_shape_output_paths(cfg["ntupletag"], user=cfg["user"]).training


def nn_dataset_cmd(cfg, us):
    # one dataset per channel: run.py TRAIN reads <datasets>/<channel>/
    return [shlex.join(["python", "run.py", "TRAIN-DATASET", "--channels", u["channel"], "--ntupletag", cfg["ntupletag"], "--train-eras", ",".join(analysis_eras(cfg)),
                        "--base-dataset-dir", f"{training_dir(cfg)}/datasets/{u['channel']}"]) for u in us]


def taues_fit_argv(cfg, u):
    return ["--era", u["era"], "--categories", u["category"], "--input-file", str(shapes_file(cfg, {"era": u["era"], "channel": "mt"}, "ss-os")), "--output-dir", cfg["taues_fit_dir"], *opts(tag=cfg["tag_arg"])]


def plot_cmd(cfg, us):
    return [f"export VARIABLES={cfg['plot_variables']}", *run_py("PLOT", cfg, us, "--ntupletag", cfg["ntupletag"], *opts(tag=cfg["tag_arg"], ff_friend=cfg["ff_friend"]))]

STEPS = [
    Step("crown-ntuples", "CROWN ntuples (KingMaker)", "crown", "era×channel", "crown", params=("sample_list",), check="crown-ntuples", command=crown_cmd(None), env="kingmaker"),
    Step("crown-selection-friend", "CROWN selection friend", "crown", "era×channel", "crown", needs=("crown-ntuples",), params=("selection_friend", "sample_list"),
         check="crown-friend", command=crown_cmd("selection"), env="kingmaker"),
    Step("ff-gen-configs", "FF: generate TauFakeFactors configs", "local", "ffera×channel", "ff", channels=FF_CHANNELS,
         outputs=lambda cfg, u: [f"{REPO_ROOT}/fake_factors/configs/{cfg['analysis']}/{u['ffera']}/preselection_{u['channel']}.yaml"],
         inputs=lambda cfg, u: [REPO_ROOT / "common/datasets.yaml"], command=lambda cfg, us: run_py("GEN-TFF-CONFIGS", cfg, us)),
    Step("ff-presel", "FF: preselection", "condor", "ffera×channel", "ff", needs=("ff-gen-configs", "crown-selection-friend"), params=("selection_friend", "additional_friends", "tag"), channels=FF_CHANNELS,
         outputs=lambda cfg, u: [f"{build_shape_output_paths(cfg['ntupletag'], user=cfg['user']).fake_factors}/preselection/{u['ffera']}/{u['channel']}/*"],
         submitter="submit_ff", argv=ff_argv("presel")),
    Step("ff", "FF: fake factors", "condor", "ffera×channel", "ff", needs=("ff-presel",), params=("tag",), channels=FF_CHANNELS,
         outputs=lambda cfg, u: [f"{ff_dir(cfg, u)}/fake_factors/fake_factors_{u['channel']}.json*"], submitter="submit_ff", argv=ff_argv("ff")),
    Step("ff-corr", "FF: corrections", "condor", "ffera×channel", "ff", needs=("ff",), params=("tag", "correction_tag"), channels=FF_CHANNELS,
         outputs=lambda cfg, u: [ff_sources(cfg, u)[1][0]], submitter="submit_ff", argv=ff_argv("ff-corr")),
    Step("ff-handoff", "FF: payloads to CROWN", "handoff", "ffera×channel", "ff", needs=("ff-corr",), params=("correction_tag",), channels=FF_CHANNELS,
         check="handoff", outputs=ff_sources, command=handoff_copies(ff_sources), env=""),
    Step("crown-ff-friend", "CROWN fake-factor friend", "crown", "era×channel", "crown", needs=("crown-ntuples", "ff-handoff"), params=("ff_friend", "sample_list"),
         channels=FF_CHANNELS, check="crown-friend", command=crown_cmd("ff"), env="kingmaker"),
    Step("shapes", "Shapes (QCD, or fake factors if an FF friend is set)", "condor", "era×channel", "shapes",
         needs=lambda cfg: ("crown-selection-friend", *(("crown-ff-friend",) if cfg["ff_friend"] else ())),
         params=("selection_friend", "additional_friends", "ff_friend", "stxs_stage", "tag", "process_selection", "special_analysis"), check="shapes",
         submitter="submit_shapes", argv=lambda cfg, u: shapes_argv(cfg, u, ff=bool(cfg["ff_friend"]))),
    Step("estimations", "Estimations (QCD or fake factors)", "condor", "era×channel", "estimations", needs=("shapes",), params=("ff_friend", "tag"), check="estimations",
         submitter="submit_estimations", argv=lambda cfg, u: estimations_argv(cfg, u, ff=bool(cfg["ff_friend"]))),
    Step("plot", "Control plots", "local", "era×channel", "plot", needs=("estimations",), params=("ff_friend", "tag", "plot_variables"), command=plot_cmd,
         outputs=lambda cfg, u: plot_files(cfg, u, qcd_label(cfg)), inputs=lambda cfg, u: [shapes_path(cfg, u)]),
    Step("datacards", "Datacards", "local", "era×channel", "datacards", needs=("estimations",), params=("dc_analysis", "variable", "stxs_stage", "fitdir", "dc_output_dir"),
         env="cmssw", command=datacard_cmd, outputs=lambda cfg, u: [f"{cfg['dc_output_dir']}/{u['channel']}/{u['era']}/*.txt"], inputs=lambda cfg, u: [shapes_path(cfg, u)]),
    Step("workspace", "Combine workspace", "local", "era", "datacards", needs=("datacards",), params=("dc_analysis", "fitdir"), env="cmssw", command=workspace_cmd,
         outputs=lambda cfg, u: [f"{cfg['fitdir']}/output_{cfg['dc_analysis']}/{ch}/{u['era']}/ws.root" for ch in cfg["channels"]]),
    Step("gof", "Goodness of fit", "local", "era×channel", "datacards", needs=("estimations",), params=("variable", "fitdir"), env="cmssw", command=gof_cmd,
         outputs=lambda cfg, u: [f"{cfg['fitdir']}/output/gof/{gof_job(cfg, u)}/gof_saturated.json"], inputs=lambda cfg, u: [shapes_path(cfg, u)]),
    Step("impacts", "Impacts", "local", "era×channel", "datacards", needs=("gof",), params=("variable", "fitdir"), env="cmssw", command=impacts_cmd,
         outputs=lambda cfg, u: [f"{cfg['fitdir']}/output/impacts/{gof_job(cfg, u)}/impacts_{gof_job(cfg, u)}.json"]),
    Step("crown-btag-inputs", "CROWN ntuples with b-tag jet vectors", "crown", "era×channel", "crown", needs=("crown-ntuples",), params=("sample_list",),
         check="btag-inputs", command=btag_ntuples_cmd, env="kingmaker"),
    Step("btag-presel", "B-tag: preselection", "condor", "era×channel", "btag", needs=("crown-selection-friend", "crown-btag-inputs"), params=("selection_friend", "additional_friends", "tag"),
         outputs=lambda cfg, u: [f"{build_shape_output_paths(cfg['ntupletag'], user=cfg['user']).btag_efficiencies}/preselection/{u['era']}/{u['channel']}/*"],
         submitter="submit_btag_efficiency", argv=btag_argv("presel")),
    Step("btag-calc", "B-tag: efficiencies", "condor", "era×channel", "btag", needs=("btag-presel",), params=("tag",),
         outputs=lambda cfg, u: [f"{btag_calc_dir(cfg, u)}/btag_efficiency.json*"], submitter="submit_btag_efficiency", argv=btag_argv("calc")),
    Step("btag-handoff", "B-tag: payloads to CROWN", "handoff", "era×channel", "btag", needs=("btag-calc",), check="handoff", outputs=btag_sources, command=handoff_copies(btag_sources), env=""),
    Step("nn-configs", "NN: training configs", "condor", "era×channel", "nn", channels=NN_CHANNELS, needs=("crown-selection-friend", "crown-ff-friend"), params=("selection_friend", "additional_friends", "ff_friend", "tag"),
         outputs=lambda cfg, u: [f"{training_dir(cfg)}/configs/{u['era']}__{u['channel']}__config.yaml"], submitter="submit_train_configs",
         argv=lambda cfg, u: ["--ntupletag", cfg["ntupletag"], "--eras", u["era"], "--channels", u["channel"], "--user", cfg["user"], *opts(selection_friend=cfg["selection_friend"], ff_friend=cfg["ff_friend"], additional_friends=cfg["additional_friends"], tag=cfg["tag_arg"])]),
    Step("nn-dataset", "NN: training dataset", "local", "channel", "nn", channels=NN_CHANNELS, needs=("nn-configs",), params=("ff_friend",),
         outputs=lambda cfg, u: [f"{training_dir(cfg)}/datasets/{u['channel']}/folds/fold{fold}.feather" for fold in (0, 1)], command=nn_dataset_cmd),
    Step("nn-train", "NN: training (GPU)", "condor", "channel", "train", channels=NN_CHANNELS, needs=("nn-dataset",), params=("ff_friend", "tag", "train_task", "request_gpus"), outputs=train_outputs,
         submitter="submit_nn_train", argv=lambda cfg, u: ["--ntupletag", cfg["ntupletag"], "--channels", u["channel"], "--user", cfg["user"], "--train-task", cfg["train_task"],
                                                            "--request-gpus", cfg["request_gpus"], *opts(tag=cfg["tag_arg"])]),
    Step("nn-handoff", "NN: model to CROWN", "handoff", "channel", "train", channels=NN_CHANNELS, needs=("nn-train",), params=("tag",),
         check="handoff", outputs=nn_sources, command=handoff_copies(nn_sources), env=""),
    Step("taues-shapes", "TauES: shapes", "condor", "era×channel", "taues", needs=("crown-selection-friend",), params=("selection_friend", "additional_friends", "stxs_stage", "tag"), check="shapes",
         submitter="submit_shapes", argv=lambda cfg, u: shapes_argv(cfg, u, special="TauES")),
    Step("taues-fit", "TauES: fit", "condor", "era×category", "taues", needs=("taues-shapes",), params=("tag", "taues_fit_dir"),
         outputs=lambda cfg, u: [f"{cfg['taues_fit_dir']}/{u['category']}/**/higgsCombine*.root"], submitter="submit_taues_fit", argv=taues_fit_argv),
]
BY_NAME = {s.name: s for s in STEPS}
