<table>
  <tr>
    <td><img src="docs/TAUER_logo.png" alt="TAUER logo" width="200"></td>
    <td><h1>TAUER: Tau Analyses Utility for Estimation and Reconstruction</h1></td>
  </tr>
</table>

- [Environment setup](#environment-setup)
  - [1. `tauer` conda env — everything except CMSSW/Combine](#1-tauer-conda-env--everything-except-cmsswcombine)
  - [2. CMSSW / `cmsenv` — Combine, datacards, GoF/Impacts, tauES fit](#2-cmssw--cmsenv--combine-datacards-gofimpacts-taues-fit)
  - [Submodules](#submodules)
- [`tauer` workflow UI](#tauer-workflow-ui)
  - [The interactive session](#the-interactive-session)
  - [Commands](#commands)
- [Pipeline](#pipeline)
  - [1. SHAPES — shape production](#1-shapes--shape-production)
  - [2. PLOT — control plots](#2-plot--control-plots)
  - [3. TRAIN-SHAPES — shapes for DNN training input](#3-train-shapes--shapes-for-dnn-training-input)
  - [4. CONFIGS — collect ntuple\_processor configs for the NN training](#4-configs--collect-ntuple_processor-configs-for-the-nn-training)
  - [5. Fake-factor measurement: FF → FF-CORR](#5-fake-factor-measurement-ff--ff-corr)
  - [STXS signal split (`--stxs-stage`)](#stxs-signal-split---stxs-stage)
  - [6. Datacards / Combine](#6-datacards--combine)
  - [7. TauES measurement](#7-taues-measurement)
  - [8. B-tag efficiency measurement](#8-b-tag-efficiency-measurement)
  - [9. NN training](#9-nn-training)
- [HTCondor submission](#htcondor-submission)
  - [Splitting a job by process group](#splitting-a-job-by-process-group)
  - [Checking sample availability on the GridKA dCache](#checking-sample-availability-on-the-gridka-dcache)
- [Run2 (2018), tauES and embedding support](#run2-2018-taues-and-embedding-support)
- [Additional details](#additional-details)
  - [Repository layout](#repository-layout)
  - [Flag / environment-variable reference](#flag--environment-variable-reference)

This framework interfaces with the ntuple producer [CROWN](https://github.com/KIT-CMS/CROWN)
to extend the full analysis chain: background estimations, histogram creation, systematics 
booking, neural network training for signal classification, plotting, and 
[CMS Combine](https://cms-analysis.github.io/HiggsAnalysis-CombinedLimit/v11.1.0/) 
datacard creation. On top of this, b-jets efficiencies calculation and tau energy scale correction
derivations are included.

The generic infrastructure works for any CROWN-based tau analysis; what's actually
being analyzed (signal processes, DNN categorization, measurement-specific binning) is
pluggable, selected via `TAUER_ANALYSIS` (see `analyses/`).

The external dependencies are:

- **CROWN / KingMaker** — ntuple production; consumed as input.
- **CombineHarvester / Combine / CMSSW** — the statistical-fit toolkit; reached via
  `cmsenv`.
- **`ntuple_processor`** (git submodule, `KIT-CMS/ntuple_processor`) — the RDataFrame
  booking/optimization layer `shapes/produce_shapes.py` builds on. Deliberately kept
  external: it's a small, actively-maintained shared tool, not analysis-specific glue.
- **`fake_factors`** (git submodule, `KIT-CMS/TauFakeFactors`) — the fake-factor
  measurement code itself (`preselection.py`/`ff_calculation.py`/`ff_corrections.py`).
  TAUER generates its config and drives it, but does not reimplement it.
- **`sample_database`** (git submodule, `KIT-CMS/KingMaker_sample_database`) — the sample database
  shared with CROWN.
- **`trainings/uncertainty-aware-training`** (git submodule) — the actual NN training-loop
  task graph. Supports systematics aware and cross-entropy trainig.
- **`CustomLogging`** (git submodule, `KIT-CMS/CustomLogging`) — unified logging style.

**Validated eras:** 2022preEE, 2022postEE, 2023preBPix, 2023postBPix, 2024, 2025 (Run3,
full production support) — plus a validated Run2 **2018** path for tauES/embedding
studies. 

**Channels:** `et` (e+τh), `mt` (μ+τh), `tt` (τh+τh), `em` (e+μ).

---

## Environment setup

There are **two separate environments**, used for different pipeline stages — mixing them
in the same shell session breaks things.

### 1. `tauer` conda env — everything except CMSSW/Combine

```bash
conda env create -f environment.yml   # creates the "tauer" env
conda activate tauer
```

One environment now covers the whole pipeline: shape production, plotting, condor
submission, the fake-factor measurement, and NN training.

### 2. CMSSW / `cmsenv` — Combine, datacards, GoF/Impacts, tauES fit

```bash
source utils/setup_cmssw.sh          
export FITDIR=/path/to/combine/workdir
```

Needed for anything related to datacards and fits.

Both environments are set up by `utils/environment.py` when `run.py`, the condor jobs or the datacard scripts need them;
`utils/setup_tauer.sh` does the same for running a script by hand.

### Submodules

```bash
git submodule update --init --recursive
```

Initializes `fake_factors/`, `ntuple_processor/`, `sample_database/`, and `CustomLogging/`.
`trainings/uncertainty-aware-training/` is also a submodule; only needed for `run.py TRAIN`.

---

## `tauer` workflow UI

`tauer` is a terminal UI and a workflow manager on top of `run.py` and the `condor/submit_*.py` scripts. It asks what you want to run, checks which outputs already exist, includes the missing steps those need and submits or prints them.

```bash
conda activate tauer
bash utils/install_tauer_command.sh      # once: links $CONDA_PREFIX/bin/tauer
tauer                                    # interactive session
```

On first use it asks where `KingMaker/CROWN/analysis_configurations/<CROWN analysis>` is: the payloads are copied into its `payloads/`, the KingMaker
commands run next to it (saved in `~/.config/tauer/settings.json`, change it with `tauer setup`). The XRootD checks of the CROWN outputs need a valid grid proxy.

### The interactive session

1. **Analysis** (`analyses/<name>`), then the **steps**, grouped as b-tag, FF, NN, shapes to fits, TauES and CROWN.
2. **Eras** and **channels**. With only CROWN steps there is no era
   question: the eras come from the sample list, and the check covers the eras of the production.
3. **Ntuple tag** and **friend tags**, chosen from the tags on the ntuple path or typed. The FF friend is optional (skip it for the ss-os QCD method);
   additional friends are attached to every step that reads ntuples.
4. The **options** of the selected steps (STXS stage, run tag, process groups, sample list, ...), then one line of **extra options** that is added
   as-is to the commands of the selected steps; it is checked against the condor submitters and asked again if they reject it.
5. The **status tree**: every selected step and the upstream steps it still waits for, per era/channel unit:

   | state | meaning |
   |---|---|
   | `done` | outputs exist (and, for CROWN friends, one friend file per ntuple file) |
   | `missing` / `partial` | not produced / only some outputs |
   | `waiting` / `blocked` | cannot start yet: a step it needs is not done (`waiting`: that step is selected too, `blocked`: it will be added by tauer) |
   | `stale` | done, but an input is newer than the output |
   | `other-options` | done with different options (tag, friends, STXS stage, extra options) than the current ones |
   | `queued` / `running` / `held` / `failed` | condor jobs submitted by tauer |

6. Then, in pipeline order:
   - **condor steps** (FF, shapes, estimations, b-tag, NN configs, NN training, TauES) are submitted through their `condor/submit_*.py`, one confirmation
     per step; if you decline, tauer prints the commands to run the same jobs locally; a dry run (`condor_submit -dry-run`) writes nothing;
   - **local steps** (plots, datacards, workspace, GoF, impacts, NN dataset, FF config generation) are not run: tauer prints the exact commands to copy and run yourself;
   - **CROWN steps** (ntuples, selection / FF friends) print the `law run ProduceNtuples ...` command to run in KingMaker;
   - **payload handoffs** (the FF and b-tag results and the trained NN model to CROWN's `payloads/`) list the files and copy them after a confirmation.
7. If jobs were submitted, the session ends in `tauer status --watch`; Ctrl+C stops watching, the jobs keep running.

The answers are remembered in `~/.config/tauer/last_inputs.json` and used as defaults of the next session. Every condor submission made by tauer
keeps its usual directory, `condor/run/<ntupletag>/[<tag>/]<stage>/<timestamp>/`, where tauer also writes a `tauer.json` with the submitted units
and job ids; `tauer status` finds the jobs through these files.

### Commands

**`tauer status [<id>]`** shows the status tree of every tauer session with submitted jobs, or only of the given one. For failed jobs it shows the
error and asks whether to resubmit them, for held jobs whether to release or remove them, and it offers to submit the steps whose inputs are now done.
Every action asks for a confirmation; a rejected submission prints the commands to run those jobs locally instead.

**`tauer status [<id>] --watch [MIN]`** (alias `tauer watch [<id>] [--interval MIN]`) redraws the status of the jobs still in the queue every `MIN`
minutes (5 by default) until none is left, without asking anything. For sessions whose condor submissions were approved at the start, it submits the
steps that became ready and resubmits failed jobs (up to 3 attempts, not after a `condor_rm`); CROWN, local and payload steps still need `tauer status`.

**`tauer clean`** asks for each tauer session whether to stop tracking it: its `tauer.json` files are deleted, so `tauer status`
no longer shows it. The condor run directories, logs and outputs are kept, and jobs still in the queue keep running.

**`tauer setup`** changes the location of the CROWN analysis configuration asked on first use.

## Pipeline

All modes below run through the single entry point **`run.py`** (the [`tauer` guided workflow](#tauer-guided-workflow) drives the same commands). Run `python3 run.py --help` 
for the authoritative, always-up-to-date flag list; what follows is a practical walkthrough in pipeline order. The full flag table and the repository
layout are at the end, under [Additional details](#additional-details). The figure below shows the graph of how the different elements of CROWN and TAUER are intertwined and the usual workflow of analyses.

```bash
python3 run.py <MODE> [options]
```

The ROOT outputs of a production (shapes and preselected ntuples) are collected below
`/ceph/$USER/TAUER_shapes/<ntupletag>/` (the fake-factor and b-tag results, json files and plots, are in `fake_factors/workdir/` and
`btag_efficiencies/workdir/`):

```
/ceph/$USER/TAUER_shapes/<ntupletag>/
├── output/[<tag>/]<ss-os|ff>/<era>/<channel>/   shapes (SHAPES, estimations)
├── validation/                                 ntuple_processor validation database
├── fake_factors/preselection/<ff-era>/<channel>/   FF preselected ntuples
├── btag_efficiencies/preselection/<era>/<channel>/ b-tag preselected ntuples
└── training/{configs,datasets}/                 NN training configs and feather folds
```

![TAUER pipeline: CROWN inputs, the steps of each workflow and the results that return to CROWN](docs/pipeline.svg)

### 1. SHAPES — shape production

This pipeline has no preselection step of its own: `SHAPES`/`TRAIN-SHAPES`/`CONFIGS` always
read raw CROWN ntuples directly plus CROWN's shapes friend
(`--selection-friend` below), which now computes selection masks and weights directly. The figure below illustrates how this works between CROWN and TAUER.

![The CROWN selection friend: the weight chain, the masks and which step reads each column](docs/selection_friend.svg)

```bash
python3 run.py SHAPES --ntupletag <ntupletag> --era <era> --channels <channels> \
  --selection-friend <selection-tag> --ff-friend <ff-tag> --ff-type fake_factor \
  --stxs-stage stage0                                  # full systematic shapes
python3 run.py SHAPES --ntupletag <ntupletag> --era <era> --channels <channels> \
  --selection-friend <selection-tag> --skip-systematics   # nominal-only, faster iteration
```

Runs `shapes/produce_shapes.py` (booking/execution via the `ntuple_processor` submodule),
then `shapes/do_estimations.py` for fake-factor/QCD/embedding post-processing, writing

```
/ceph/$USER/TAUER_shapes/<ntupletag>/output/[<tag>/]<ss-os|ff>/<era>/<channel>/shapes.root
```

The `<tag>/` level only appears when `--tag` differs from `--ntupletag`.

Pass `--selection-friend <tag>` (`SELECTION_FRIEND_DIR` env var) to attach CROWN's
selection-mask friend trees and switch preselection over to
CROWN's precomputed, per-shift `presel_mask` branches instead of individual
cut strings. Leave unset for masks-in-the-ntuple productions, which are still auto-detected.

`<tag>` defaults to `<ntupletag>`; `<ss-os|ff>` follows whether `FF_FRIENDS_DIR`/
`--ff-friend` is set, which also selects `do_estimations.py`'s `--do-qcd` vs `--do-ff`. Pass
`--ff-friend <tag>` (`FF_FRIENDS_DIR` env var) with CROWN's fake-factor friend VERSION TAG
to resolve it the same way as `--selection-friend` (a bare tag resolves to
`.../CROWN/ntuples/<ntupletag>/CROWNFriends/<tag>/`, a value containing `/` is used as a full
path as-is). `--additional-friends <tag1,tag2,...>` (`ADDITIONAL_FRIENDS_DIR` env var) attaches
any number of extra friend tags/paths to every channel.

The `same_sign` histograms both estimations need are booked unconditionally, so an FF run
reuses an existing ss-os run for the same tag/era/channels: it books only the FF-weighted
systematics (`--ff-only`) and `hadd`s them onto a copy of the ss-os file rather than repeating
the expensive event loop. The FF weight is read per event from the friend tree during the
event loop, so it cannot be applied to already-filled histograms afterwards — hence the
second, scoped pass.

### 2. PLOT — control plots

```bash
conda activate tauer
python3 run.py PLOT --ntupletag <ntupletag> --era <era> --channels <channels>
```

Runs `plotting/plot_shapes_control.py` (mplhep/CMS-style) against the shapes ROOT file
`SHAPES` produced, writing PNG/PDF control plots to
`/web/$USER/public_html/CMS_HTT/<ss-os|ff>/<era>/<ntupletag>/[<tag>/]<channel>/`.

Writing straight to `/web` (this local PLOT mode's default) only works
when run on a node where `/web` is actually mounted (a portal/login node). It does **not** work
from `condor/submit_plotting.py` jobs -- Condor execute-node containers only bind-mount `/work`,
`/ceph`, `/cvmfs`, not `/web`.

### 3. TRAIN-SHAPES — shapes for DNN training input

```bash
python3 run.py TRAIN-SHAPES --ntupletag <ntupletag> --era <era> --channels <channels> --selection-friend <selection-tag>
```

Same production step as SHAPES but nominal-only with training-specific binning; feeds
`TRAIN-DATASET` below.

### 4. CONFIGS — collect ntuple_processor configs for the NN training

```bash
python3 run.py CONFIGS --ntupletag <ntupletag> --era <era> --channels <channels> --selection-friend <selection-tag>
```

Runs `produce_shapes.py --collect-config-only`: it books the same graphs as `SHAPES` but, instead of
filling histograms, dumps for every sample the ntuple paths, the cuts, the weights and the variables into
`<era>__<channel>__config.yaml` (default: `/ceph/$USER/TAUER_shapes/<ntupletag>/training/configs/`).
These files are the input of the NN training dataset (`TRAIN-DATASET`, step 9, which merges them across eras).
It is **not** needed for shapes, fake factors or datacards; run it only before building a training dataset
(`condor/submit_train_configs.py` is the batch version, one job per era and channel). It is also a quick way to
check the sample/selection/cut wiring without an event loop.

### 5. Fake-factor measurement: FF → FF-CORR

The fake factors are measured from its own submodule. `run.py FF-MEASURE` chains
`GEN-TFF-CONFIGS → TauFakeFactors' own preselection.py → FF →
FF-CORR`.

Run `GEN-TFF-CONFIGS` first after any `common/datasets.yaml` edit — it's the
build step that regenerates the FF `preselection_{ch}.yaml` (samples, `presel_mask`) from central
config.

`--ntupletag` is required whenever `--steps` includes `presel`/`ff`/`ff-corr` (the
default): `fake_factors/configs/smhtt/{2022,2023,2024,2025}/common_settings.yaml`
intentionally carry no `ntuple_path`/`output_path`/`file_path`/`workdir_name` any more —
those are always resolved from `--ntupletag` (plus `--selection-friend` for the CROWN
selection-mask friend tree), via a generated tmp config, so switching ntupletag can never
silently mix output from two different productions. `<ff-era>` below is the TauFakeFactors config
year (`2022`, `2023`, `2024`, `2025`, see `common.analysis.ff_config_era`), `<tag>` defaults to `<ntupletag>`:

- preselected ntuples: `/ceph/$USER/TAUER_shapes/<ntupletag>/fake_factors/preselection/<ff-era>/<channel>/`
- `ff` results: `fake_factors/workdir/<tag>/<ff-era>/fake_factors/` (`fake_factors_<channel>.json[.gz]`, plots in `<channel>/`)
- `ff-corr` results: `fake_factors/workdir/<tag>/<ff-era>/corrections/[<correction_tag>/]`

```bash
python3 run.py FF-MEASURE --era <era> --channels <channels> --steps presel,ff,ff-corr \
  --ntupletag <ntupletag> --selection-friend <selection-tag>
```

2022/2023 share one combined TauFakeFactors config per year (`configs/smhtt/2022/`,
`configs/smhtt/2023/` — see `common.analysis.ff_config_era`), covering both era halves'
samples via per-sample `era_overrides`; one run with either half's `--era` value already
processes both halves together, so don't run this once per half.

### STXS signal split (`--stxs-stage`)

`--stxs-stage {stage0,stage1p2}` (shapes, GoF inputs and datacards alike) books the signals either per production mode (`ggH_htt125`, `qqH_htt125`, `VH_htt125`, `ttH_htt125`)
 or per `<PROCESS>_<STXS_BIN>` of the [CMS STXS Run 3 recommendations](https://gitlab.cern.ch/cms-analysis/hig/stxs-run3-recommendations).
The ntuples are always stage-0: the split is a cut on the HTXS stage-1.2 bin and on the sample family
(`stxs_family`) written by CROWN's `STXSNormalization` into the weights friend.

- Normalization: CROWN's norm table takes the xsec x B(tautau) x generator-filter efficiency and the per-bin
  fraction rescaling to the recommended values from `sample_database/aux_data/stxs_nick_table.json`, built by
  `python -m analyses.smhtt.common.stxs_tools`. The recommendations are read from `$STXS_RECOMMENDATIONS_DIR`.
- Building the nick table: the per-bin fractions f_MC come from the unfiltered samples (pooled over eras, ggH NNLOPS-weighted) and are
  applied to the filtered nicks of `analyses/smhtt/common/signals.yaml`. `signal_nicks` adds the unfiltered nicks of the signal families on its own (skipping
  2025, a copy of 2024, and the non-ReNano 2024 nick where a ReNano one exists); they are scanned but never booked as signals. Eras sharing a dbs
  (2025/2026 and 2024) reuse the same scan.
  ```bash
  python3 condor/submit_stxs_table.py [--dry-run]                       # one job per 25 files, chunks in condor/run/stxs_table/scans
  python3 condor/submit_stxs_table.py --missing-only                    # resubmit only the chunks without an output file
  python -m analyses.smhtt.common.stxs_tools --scan-dir condor/run/stxs_table/scans   # build the table (fails if a chunk is missing)
  cp sample_database/aux_data/stxs_nick_table.json ../KingMaker/sample_database/aux_data/   # CROWN reads its own copy
  ```
- Uncertainties: `THU_*`, `pdf_Higgs_*`, `alphaS_*` are flat lnN: per `<PROCESS>_<STXS_BIN>` in stage1p2, and in stage0 the average of
  the bin values weighted by the recommended sigma x fraction. `CMS_LHEScaleWeight_*` are shapes from the per-bin normalized
  `LHEScaleWeight[0]/[8]` with the correlation scheme of the recommendations. `BR_htt` is a single lnN.
- Datacard bins are named `RECO__hig-26-018__<category>_<era>`.

### 6. Datacards / Combine

```bash
source utils/setup_cmssw.sh
export FITDIR=/path/to/combine/workdir

python3 datacards/produce_datacard.py <era> <channel> <analysis> <shapes.root> --variable <variable> \
  --stxs-stage stage0 --ff-type fake_factor --output-dir <datacard-dir>
python3 datacards/produce_workspace.py <era> <analysis> <cores>

# Goodness-of-fit / Impacts (single-variable, single-category workflow):
python3 datacards/produce_datacard.py <era> <channel> gof <shapes.root> --variable <variable> \
  --stxs-stage stage0 --embedding true --jetfakes true --output-dir <datacard-dir>
python3 datacards/produce_workspace.py <era> gof --channels <channel> --variable <variable>
python3 datacards/run_gof.py <era> <channel> <variable> <shapes.root> saturated 20 0 4
python3 datacards/run_impacts.py <era> <channel> <variable> 4
```

`<analysis>` is the categorization scheme (e.g. `stxs_stage0_run3`). `--stxs-stage` is the same flag as in the shapes
and must match them, also for GoF: the signal shifts are booked under the names they carry in the datacards. `--output-dir`
sets where the cards are written.

`<shapes.root>` is the output of `run.py SHAPES` for the era and channel, read directly by the datacards: its histograms are
`<variable>/<channel>[_<category>][_ss|_ar]/<process>[_<systematic>]` (`shapes/naming.py`), the `<channel>_<category>` directories being the
Combine bins and `_ss`/`_ar` the same-sign and anti-isolated inputs of the QCD and fake factor estimates. `--variable` is the discriminant; GoF uses a control-variable run, whose single bin is `<channel>`.

`produce_datacard.py` enters CMSSW and runs `datacards/make_datacards.py` (the
category/systematics/CardWriter logic); `run_gof.py`/`run_impacts.py` drive
`combine`/`combineTool.py`. Run `--help` on each for the exact arguments.

### 7. TauES measurement

```bash
source utils/setup_cmssw.sh
python3 tau_es/run_taues_category.py --era <era> --channels mt --category <category> \
  --input-file <taues-shapes.root> --output-dir <fit-dir> [--variable m_vis]
```

Chains `tau_es/make_taues_datacard.py` (builds a Combine datacard with a continuous `taues`
RooMorphing parameter) → `tau_es/run_taues_fit.py workspace` → `tau_es/run_taues_fit.py fit`
(`combine -M MultiDimFit`) for one (era, category) — categories are `DM0`, `DM1`, `DM10_11`,
`Inclusive`. The input is the `shapes.root` of `run.py SHAPES --special-analysis TauES`, read directly
(`<variable>/mt_<category>/<process>[_<systematic>]`, the shift-point templates as `EMB_<shift>`).

### 8. B-tag efficiency measurement

```bash
conda activate tauer
python3 run.py BTAG --era <era> --channels <channels> --ntupletag <btag-ntupletag> --selection-friend <selection-tag> --steps presel,calc
```

`--steps presel` runs `fake_factors/preselection.py` (reused as-is) against
`btag_efficiencies/configs/{era}/preselection_{channel}.yaml`; `--steps calc` runs
`btag_efficiencies/calculate_efficiency.py`. Add `gen-configs` to rebuild the
preselection YAML from central config first (needed after a CROWN selection change).
The ntuple path (including your username) and the output/workdir paths are derived from
`--ntupletag`: the preselected ntuples go to `/ceph/$USER/TAUER_shapes/<ntupletag>/btag_efficiencies/preselection/<era>/<channel>/`,
the efficiencies (json and plots) to `btag_efficiencies/workdir/<ntupletag>/<era>/[<tag>/]<channel>/btag_efficiency.json[.gz]`
(`--tag` adds the extra level only when it differs from `--ntupletag`).

The measurement reads the jet vectors `jet_pt_vec`, `jet_eta_vec`, `jet_hadronflavour_vec`, `jet_btag_value_vec` (column names in
`btag_efficiencies/configs/{era}/btag_efficiency.yaml`), which CROWN only writes for MC with `measure_btag_efficiency = True` in
`analysis_configurations/tau/config.py`: the b-tag ntuples are a separate production with that flag on.

### 9. NN training

1. Per-(era, channel) ntuple_processor configs (cuts/weights/paths/variables) -- one
  condor job per (era, channel); `--collect-config-only` means these never book real
  histograms.

```bash
python3 condor/submit_train_configs.py --ntupletag <ntupletag> --eras <eras> --channels <channels> \
  --ff-friend <ff-tag> --selection-friend <selection-tag>
  ```

2. Merge those per-era configs across eras (per channel) and build the feather folds.
```bash
python3 run.py TRAIN-DATASET --channels <channels> --ntupletag <ntupletag>
  ```

3. NN training loop, locally or as one condor job with the same law command and output layout (`--request-gpus N` adds `request_gpus`, the job
   uses the GPUs condor assigns).
```bash
python3 run.py TRAIN --channels <channels> --ntupletag <ntupletag> \
  --train-task RunAllCENNTConfusionMatrixWorkflow --cuda-device 0,1 --workers 2
python3 condor/submit_nn_train.py --channels <channels> --ntupletag <ntupletag> --request-gpus 2 [--dry-run]
```

The training covers et/mt/tt only (the channels of the DNN categorization, `analyses/<analysis>/shapes/selection/category_selection.py`), and the
configs must be collected with the FF friend attached (`--ff-friend`).

`TRAIN-DATASET` still accepts the original, lower-level interface --
`--train-config`/`TRAIN_CONFIG=<path>` to a single, already-built
`create_training_dataset.py --config` YAML, bypassing the glob-and-merge entirely -- for
anyone who already has one. `--train-eras`/`TRAIN_ERAS` (comma-separated) additionally
restricts which eras are pulled out of `--train-configs-dir` if you don't want every era
present there merged in.

---

## HTCondor submission

Every batch-shaped stage has a direct HTCondor submitter under `condor/` — plain Python
(`condor/common.py`'s `JobSpec`/`SubmissionPlan`/`submit()`), shelling out to `condor_submit`
directly. All scripts default `--eras`/`--channels` to `common.analysis.RUN3_ERAS`/`get_channels()`, 
and support `--dry-run` (validates real classads via `condor_submit -dry-run` without queuing).

```bash
python3 condor/submit_shapes.py --ntupletag <ntupletag> --eras <eras> --channels <channels> \
  --selection-friend <selection-tag> --ff-friend <ff-tag> --ff-type fake_factor \
  --stxs-stage stage0 --dry-run                          # one job per (era, channel)
python3 condor/submit_estimations.py --ntupletag <ntupletag> --eras <eras> --channels <channels> \
  --ff-friend <ff-tag> --dry-run                         # run AFTER submit_shapes.py finishes
python3 condor/submit_plotting.py --ntupletag <ntupletag> --eras <eras> --channels <channels> \
  --dry-run                                              # one job per (era, channel)
python3 condor/submit_train_configs.py --ntupletag <ntupletag> --eras <eras> --channels <channels> \
  --selection-friend <selection-tag> --dry-run           # one job per (era, channel)
python3 condor/submit_training.py --master-config <merged-config-from-adjust_config.py> \
  --ntupletag <ntupletag> --eras <eras> --channels <channels> --dry-run
                                                          # condor fan-out of the SAME merge that
                                                          # run.py TRAIN-DATASET does locally --
                                                          # use this one instead when the merged
                                                          # config is large enough to want the
                                                          # per-(era,channel) split parallelized
python3 condor/submit_nn_dataset.py --ntupletag <ntupletag> --channels <channels> --train-eras <eras> --dry-run
                                                          # run.py TRAIN-DATASET, one job per channel (all eras of
                                                          # a channel in one job: combine_folds merges every part)
python3 condor/submit_nn_train.py --ntupletag <ntupletag> --channels <channels> --request-gpus 1 --dry-run
                                                          # run.py TRAIN (law) as one condor job, GPUs via --request-gpus
python3 condor/submit_btag_efficiency.py --ntupletag <btag-ntupletag> --selection-friend <selection-tag> \
  --steps presel --eras <eras> --channels <channels> --dry-run   # --steps calc: one job per era
python3 condor/submit_taues_fit.py --era <era> --input-file <taues-shapes.root> \
  --output-dir <fit-dir> --categories <categories> --dry-run
python3 condor/submit_ff.py --ntupletag <ntupletag> --selection-friend <selection-tag> \
  --steps presel,ff,ff-corr --eras <eras> --dry-run      # one job per era (--split-by-channel:
                                                         # one per era x channel)
```

`submit_ff.py` collapses eras sharing a TauFakeFactors config era onto one job (2022preEE +
2022postEE both measure the single "2022" fake-factor set from the same inputs/output paths
-- submitting both would race two identical jobs on the same preselection files instead of
splitting the work, so only the first of each pair is queued).

`submit_shapes.py --no-era-merge 2025` runs the job with `TAUER_NO_DATA_ERA_MERGE=2025` set
in its environment, un-merging that one analysis era's extra `DATA_ERA_MERGE` eras (e.g.
2025 without 2026's data folded in) for a one-off check — see
`common.analysis.get_data_eras()`.

### Splitting a job by process group

One flag drives both which processes get produced and how many condor jobs that takes:

```bash
python3 condor/submit_shapes.py --ntupletag <ntupletag> --eras <era> --channels <channel> \
  --selection-friend <selection-tag> --process-selection "data,ztt+zl+zj,ttt+ttl+ttj,vvt+vvl+vvj,w,ggh+qqh+tth+vh" \
  --dry-run
```

Comma-separated process groups: each group either a single process or several joined
with `+`. Splits each (era, channel) into one condor job per group — cluster large/expensive
samples (data, or any single sample that alone saturates `--request-memory-mb`) into their
own one-process group, and bundle small/cheap samples (same-family MC, signal samples)
together to cut job/slot count instead of maximizing granularity. Omit the flag for the old
one-job-per-(era, channel) behavior covering `produce_shapes.py`'s own default process set.

When splitting, each job writes `shapes__<group>.root` next to the usual `shapes.root` path
(processes race-writing the same file otherwise) plus an `expected_processes.json` manifest,
so `plotting/plot_shapes_control.py` can tell an intentionally-narrow selection apart from an
incomplete batch. No manual merge step needed: `shapes/do_estimations.py` auto-detects and
`hadd`s the parts the first time it runs after the batch finishes (safe because disjoint
processes produce disjoint histogram names). For ff runs, these groups are what get split
into the ff-only-or-not jobs — ss-os reuse still applies per group.

`--dnn-categorization` opts into the DNN-based categorization (needs a DNN friend tree this
script has no option to attach — use `DNN_FRIENDS_DIR` with `run.py` locally instead).
Omitted (the default), `--no-dnn-categorization` is passed to `produce_shapes.py`, avoiding
an RDataFrame compile-time failure on `nn_predicted_class` when no DNN friend is attached.

The condor batch/log dir is under `condor/run/<ntupletag>/[<tag>/]shapes/<timestamp>/`.

`--request-cpus` is also passed through as `produce_shapes.py --nprocs` (real worker
processes, not `--nthreads`/ROOT's in-process `EnableImplicitMT`, which stays fixed at 1)
— a condor `RequestCpus` allocation is a cgroup CPU share, not automatically usable by threads
inside one PID, so separate worker processes are what actually uses the requested cores.

---

### Checking sample availability on the GridKA dCache

`condor/submit_dcache_check.py` stats the `/store/...` path of every file of a list of sample nicks on
`root://cmsdcache-kit-disk.gridka.de` (needs a grid proxy and `../KingMaker/sample_database`). Only the
"not found" error (3011) counts as missing, other errors are reported separately.

```bash
python3 condor/submit_dcache_check.py --samples-file <nicks.txt> [--dry-run]   # one nick per line, one job per 1000 files
python3 condor/submit_dcache_check.py --samples-file <nicks.txt> --missing-only   # resubmit the chunks without an output file
python3 condor/submit_dcache_check.py --samples-file <nicks.txt> --merge          # per-nick report, works on partial results
```

The chunks and the output of `--merge` (`report.json`, `missing_files.txt`, `missing_dbs.txt`) are in
`condor/run/dcache_check/<nicks file name>/`. Add the lines of `missing_dbs.txt` to `rucio rule add ... cms:<dbs>` to
request the datasets on `T1_DE_KIT_Disk`. Use the same `--files-per-job` for `--missing-only`.

## Run2 (2018), tauES and embedding support

Run3 (all 6 eras, all 4 channels where data exists) is the primary, fully validated
production target. Run2/tauES/embedding support is real but narrower.

- **Run2 in the code:** the Run2 branches exist (2018 samples in `common/datasets.yaml` and lumi in `common/analysis.py`, the Run2 systematic
  names, the embedded weight chain, CROWN's Run2 weight chain), but the entry points are Run3-only:
  `common/sample_paths.py` rejects any non-Run3 era, so `run.py`, the condor submitters, `FF-MEASURE` and `BTAG` cannot
  build their ntuple paths for 2018. The fake-factor and btag configs of the Run2 eras still carry the removed
  `mc_weights` and are kept for reference only. Calling `shapes/produce_shapes.py` directly bypasses the path check but
  has not been run since the CROWN-friend refactor.
- **TauES is not tied to Run3:** nothing in the TauES shape code (`--special-analysis TauES`, `tau_es/`) restricts the
  era; it needs the embedded samples, which are the 2018 ones, and is mt-only. The path check above is the only
  reason it cannot be started through `run.py`/condor for 2018.

- **2018/mt is validated end-to-end against a reference production**: a real bin-by-bin
  control-shape comparison (`plotting/compare_control_shapes.py`) gives **36/36 histograms
  agreeing within 3σ** (12 processes × `m_vis`/`pt_1`/`pt_2`, max n_sigma 0.21, max rel_diff
  3.02% on one low-statistics process). `et`/`tt`/`em` channels and 2016/2017 eras have **no
  validation data available** and are not validated.
- **Embedding** (tau-embedded data samples) is real and validated for 2018/mt: the embedded
  weight chain (`emb_genweight`/`emb_idsel_wgt_*`/`emb_triggersel_wgt`/...) matches the
  reference production bit-for-bit.
- **TauES measurement** (`tau_es/`): the shape-production mechanism
  (`--special-analysis TauES`, 100-point -12.0%..+8.0% shift grid) is validated against real
  2018 embedded data (Phase 2a: per-shift branch scaling confirmed to <0.01%; one full shift
  point end-to-end validated with zero differences). The **datacard-construction and fit
  code** (`tau_es/make_taues_datacard.py`, `tau_es/run_taues_fit.py`) is new and has been
  validated to run correctly and produce a sane fit **only against a hand-built synthetic
  shape file**, not a real 100-shift-point production run — producing that would be a
  multi-hour real job that hadn't been executed by the time this was written. **No numeric
  tauES measurement against real data exists yet.** Whoever runs one next should follow the
  chain in "TauES measurement" above, starting from a real
  `shapes/produce_shapes.py --special-analysis TauES` run.
- 2016/2017: no validation data available at all; not supported in practice even though
  nothing in the code hard-blocks them.

---

## Additional details

### Repository layout

```
TAUER/
├── run.py                         # Main pipeline entry point 
├── environment.yml                # `tauer` conda env
├── docs/                          # logo and the graphs shown in this README (pipeline.svg, selection_friend.svg)
│
├── common/                        # Shared analysis code and its configuration
│   ├── analysis.py                #   eras, per-era luminosity, samples, background processes (datacard name, dataset key, groups), masks
│   ├── datasets.yaml              #   data (per channel) and simulated background samples per era (read by analysis.py)
│   ├── variables.yaml             #   variable list for control plots, NN training and FF preselection
│   ├── training_setup.yaml        #   NN training dataset setup (label map, selections, skipped processes)
│   ├── systematics.py             #   single source of the systematics, used by shapes and datacards
│   ├── binning.py                 #   control-plot binning and categorization helpers (NOT selection logic)
│   ├── booking.py                 #   ntuple_processor booking glue (config formatter, file paths, helper dicts)
│   ├── sample_paths.py            #   CROWN ntuple/friend-tree paths, shapes output directory
│   └── shapes_merge.py            #   merging of split shapes jobs, expected_processes.json
│
├── analyses/                      # Pluggable per-analysis code, selected via TAUER_ANALYSIS; same layout as the top level
│   └── smhtt/                     # SM STXS H->tautau
│       ├── common/
│       │   ├── signals.yaml                   #   signal sample names per era
│       │   ├── binning.py                     #   extra binning for the control-plot variables
│       │   └── stxs_tools.py                  #   STXS Run 3 recommendations loader, signal units, per-nick normalization table
│       ├── shapes/
│       │   ├── selection/
│       │   │   ├── process_selection.py       #   signal Selections generated per stage-0/stage-1.2 unit
│       │   │   ├── category_selection.py      #   SR/CR category definitions, DNN_CLASS_MAPPING
│       │   │   └── systematics.py              #   LHEScaleWeight + non-flat THU weights of the STXS Run 3 scheme
│       │   └── estimations/estimations.py     #   qqH component merge (qqH + VH) for do_estimations
│       ├── datacards/
│       │   ├── systematics.py                 #   datacard signal names per STXS stage, signal uncertainties
│       │   └── combine_model.py               #   Combine physics model and POI mapping
│       ├── plotting/plot_stxs.py              #   per-STXS-bin signal-strength plots
│       └── trainings/training_labels.py       #   NN training labels per STXS bin
│
├── shapes/                         # Shape production
│   ├── produce_shapes.py           #   reads raw CROWN ntuples directly and attaches CROWN's shapes_preparation friends
│   ├── do_estimations.py           #   fake-factor/QCD/embedding estimations
│   ├── naming.py                   #   histogram paths <variable>/<bin>/<process>[_<systematic>] (Combine layout)
│   ├── utils.py                    #   dataset/file helpers, tauES dataset booking
│   ├── selection/                  #   executable, era/channel-conditional selection logic
│   │   ├── channel_selection.py    #     CROWN SR_mask / SR_mask_ss selection
│   │   ├── process_selection.py    #     generic background (DY/TT/VV/W) weight/cut logic
│   │   └── systematics.py           #     generic systematic (Up/Down) definitions
│   ├── special/                    #   njets splitted shapes, ttbar and DY weigths from em channel
│   └── estimations/                #   defaults.py, fakefactors.py, qcd.py, ttbar_emb.py
│
├── plotting/
│   ├── plot_shapes_control.py      #   mplhep/CMS-style control plots
│   ├── process_ordering.py         #   background stack ordering/colors
│   └── compare_control_shapes.py   #   bin-by-bin shape comparator
│
├── datacards/                      # Combine datacards and fits
│   ├── make_datacards.py           #   CombineHarvester driver (runs inside CMSSW)
│   ├── categories.py, systematics.py, tools.py, compare_datacards.py
│   ├── produce_datacard.py         #   enters CMSSW and runs make_datacards.py (analysis or gof cards)
│   ├── produce_workspace.py        #   T2W of the analysis cards, or the single-r GoF workspace
│   └── run_gof.py, run_impacts.py  #   GoF test / impacts with combine/combineTool.py
│
├── btag_efficiencies/                # B-tag efficiency measurement
│   ├── calculate_efficiency.py       #   the actual efficiency-map calculation
│   ├── generate_configs.py           #   regenerates preselection YAMLs from central config
│   └── configs/{era}/                #   per-era preselection/measurement YAMLs
│
├── tau_es/                           # TauES measurement
│   ├── energy_scales.py              #   canonical 100-point shift grid (-12.0%..+8.0%, 0.2%)
│   ├── taues_categories.py  #   DM0/DM1/DM10_11/Inclusive categorization (mt only)
│   ├── make_taues_datacard.py        #   builds the Combine datacard (taues RooMorphing fit)
│   ├── run_taues_fit.py              #   workspace + MultiDimFit subcommands
│   └── run_taues_category.py         #   chains the above for one (era, category); condor unit
│
├── condor/                           # Direct HTCondor submission of each step
│   ├── common.py                     #   JobSpec/SubmissionPlan/wrapper-script/submit() machinery
│   ├── submit_shapes.py, submit_plotting.py, submit_train_configs.py, submit_training.py
│   ├── submit_btag_efficiency.py, submit_taues_fit.py, submit_ff.py, submit_estimations.py
│   ├── submit_stxs_table.py, submit_dcache_check.py, submit_nn_train.py
│   └── run/                          #   generated per-invocation wrapper/submit/log files
│
├── trainings/                        # DNN training pipeline
│   ├── create_training_dataset.py    #   ROOT shapes -> per-event feather folds
│   ├── adjust_config.py, plot_losses.py, src/
│   └── uncertainty-aware-training/   #   submodule: the actual NN training-loop task graph
│
├── workflow/                         # `tauer` guided workflow (cli.py, steps.py, status.py, tracker.py, tauer entry script)
│
├── utils/                            # Environment setup
│   ├── environment.py                #   tauer conda env, CMSSW and LCG environments: run_in_conda(), run_in_cmsenv(),
│   │                                 #   get_fitdir(), the condor job environment and the conda re-exec of the condor scripts
│   ├── setup_tauer.sh                #   sources the `tauer` env and PYTHONPATH, for running scripts by hand
│   ├── setup_cmssw.sh                #   sources `cmsenv`
│   └── install_tauer_command.sh      #   links the `tauer` command into the active conda env
│
├── fake_factors/                     # submodule: Fake-factor measurement code
│   └── generate_configs.py           #   generates preselection configs
├── ntuple_processor/                 # submodule: RDataFrame booking/optimization layer
├── sample_database/                  # submodule: sample database (KIT-CMS/KingMaker_sample_database)
└── CustomLogging/                    # submodule: shared logging helpers (KIT-CMS/CustomLogging)

```

### Flag / environment-variable reference

Every flag below also has an environment-variable fallback (same name, upper-cased,
underscored): `--flag` wins, then the env var, then the hardcoded default. Unrecognized
arguments pass straight through to the underlying python script (e.g. `shapes/produce_shapes.py`).

| Flag | Env var | Default | Notes |
|---|---|---|---|
| — | `TAUER_ANALYSIS` | `smhtt` | Which pluggable analysis (`analyses/<name>/`) supplies signal processes, DNN categorization, and measurement-specific binning. Read directly, no `--flag` (set the env var).  |
| `--ntupletag` | `NTUPLETAG` | *(required for SHAPES/TRAIN-SHAPES/CONFIGS, and FF-MEASURE unless `--steps` is gen-configs-only)* | CROWN ntuple production tag. |
| `--tag` | `TAG` | `--ntupletag` | Run-tag, distinct from ntupletag. Left at the default, an ss-os run and a later `--ff-friend` run share one output tree. Set explicitly only for a second, independent run that should *not* build on the earlier one — nests output under `output/{tag}/{ss-os,ff}/{era}/{channel}/shapes.root`. Also the FF-MEASURE workdir name, the BTAG workdir nesting and the TRAIN law version. |
| `--era` | `ERA` | `2022postEE` | |
| `--channels` | `CHANNELS` | `et,mt,tt` | Comma-separated; every channel is run independently and has its own output directory. |
| `--stxs-stage` | `STXS_STAGE` | `stage0` | Signal granularity (`stage0` per production mode, `stage1p2` per STXS bin), see below. Same flag for shapes and datacards. |
| `--selection-friend` | `SELECTION_FRIEND_DIR` | **required** for SHAPES/TRAIN-SHAPES/CONFIGS | CROWN shapes_preparation FRIEND tree version tag. Attaches the friend to every channel: `SR_mask`/`SR_mask_ss`/`presel_mask` drive the plain OS/SS/preselection cuts, `gen_category_{T,J,L}` drives the DY/TT/VV T/J/L split, and its single fused `weight` branch drives `MC_base_process_selection` for et/mt/tt/em. |
| `--ff-friend` | `FF_FRIENDS_DIR` | unset | CROWN fake-factor FRIEND tree version tag. Attached to et/mt/tt only (em has no fake factors); enables FF mode (`SHAPES --ff-type fake_factor`, `do_estimations --do-ff`). Unset falls back to the ss-os same-sign QCD extrapolation. |
| `--additional-friends` | `ADDITIONAL_FRIENDS_DIR` | unset | Comma-separated CROWN FRIEND tree version tags (or full paths), same resolution rule as above, e.g. the FastMTT friend. FF-MEASURE and BTAG add the (bare) tags to the preselection's `friends`. |
| `--ff-config` | `FF_CONFIG` | unset | Override config path for FF mode. |
| `--ff-corr-config` | `FF_CORR_CONFIG` | unset | Override config path for FF-CORR mode. |
| `--ff-input-dir` | `FF_INPUT_DIR` | unset | For FF/FF-CORR: point at any preselection-shaped directory instead of TauFakeFactors' own `preselection.py` output. |
| `--output-dir` | `OUTPUT_DIR` | derived from `--ntupletag` (`common.sample_paths.build_shape_output_paths`) | |
| `--nthreads` | `NTHREADS` | `4` | |
| `--nprocs` | `NPROCS` | `1` | |
| `--steps` | `STEPS` | FF-MEASURE: all four steps, in order; BTAG: `presel,calc` | Comma-separated subset/order of `gen-configs,presel,ff,ff-corr` (FF-MEASURE) or `gen-configs,presel,calc` (BTAG). |
| `--use-cached-intermediary-steps` | — | off | FF-MEASURE only: let ff/ff-corr reuse `fake_factors/.RDF_CACHE` snapshots. |
| `--train-task` | `TRAIN_TASK` | `RunAllCENNTConfusionMatrixWorkflow` | TRAIN only: law task name. |
| `--cuda-device` | `CUDA_DEVICE` | `0,1` | TRAIN only: GPU device IDs. |
| `--workers` | `WORKERS` | `2` | TRAIN only: law workers. |
| — | `UAT_CONFIG_DIR` | — | Base dir for uncertainty-aware-training base configs. |
