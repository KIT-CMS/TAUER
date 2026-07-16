# TauKITFlow

SM H→ττ analysis framework. It runs the full shape-based analysis chain — CROWN ntuples →
shapes → estimations → control plots / Combine datacards / DNN training — for the
KIT-CMS H→ττ measurement.

TauKITFlow is **not** a fork of `smhtt_ul` or a wrapper around it: every analysis-specific
step that used to live in a sibling repo or a compiled CMSSW binary (shape production
selection logic, the Combine-datacard construction step, the tauES measurement, the b-tag
efficiency measurement) has been ported into this repo as plain Python, reading a single
central `config/*.yaml`. The only things left as genuinely external dependencies are:

- **CROWN / KingMaker** — ntuple production; out of scope for this repo, consumed as
  read-only input.
- **CombineHarvester / Combine / CMSSW** — the statistical-fit toolkit; reached via
  `cmsenv`, never vendored in.
- **`ntuple_processor`** (git submodule, `KIT-CMS/ntuple_processor`) — the RDataFrame
  booking/optimization layer `shapes/produce_shapes.py` builds on. Deliberately kept
  external: it's a small, actively-maintained shared tool also used by `smhtt_ul`, not
  analysis-specific glue (see `STATUS.md`, Phase 6f).
- **TauFakeFactors** (git submodule, `KIT-CMS/TauFakeFactors`) — the fake-factor
  measurement code itself (`preselection.py`/`ff_calculation.py`/`ff_corrections.py`).
  TauKITFlow generates its config from central `config/*.yaml` and drives it, but does not
  reimplement it.
- **`trainings/uncertainty-aware-training`** (git submodule) — the actual NN training-loop
  task graph (still `law`-orchestrated internally; TauKITFlow's own code around it is plain
  Python, see "NN training" below).

Everything else that historically lived in one of those places for no good reason
(b-tag efficiency measurement, tauES calculation, Combine-datacard construction) has been
"dismantled, not wrapped" into its own purpose-named top-level directory inside this repo.

**Supported eras:** 2022preEE, 2022postEE, 2023preBPix, 2023postBPix, 2024, 2025 (Run3,
full production support) — plus a validated Run2 **2018** path for tauES/embedding
studies (see "Run2 (2018), tauES and embedding support" below; 2016/2017 are not
supported).
**Channels:** `et` (e+τh), `mt` (μ+τh), `tt` (τh+τh), `em` (e+μ, partial coverage).

---

## Repository layout

```
TauKITFlow/
├── run.py                        # Main pipeline entry point (all MODEs, see below)
├── run_fake_factor_measurement.py # Chains GEN-TFF-CONFIGS -> PRESEL -> FF -> FF-CORR
├── environment.yml                # `taukitflow` conda env (shape production/training)
├── environment-plotting.yml       # Separate env for PLOT (adds ROOT to the plotting stack)
│
├── config/                        # Central, single-sourced analysis config
│   ├── analysis.py                #   getters: get_luminosity, get_preselection_cuts,
│   │                               #   get_channel_selection_cuts, get_mc_weights,
│   │                               #   get_channels, RUN3_ERAS, RUN2_ERAS, SIGNAL_SAMPLES, ...
│   ├── samples.yaml                #   sample lists, per-era luminosity
│   ├── cuts.yaml                   #   preselection + channel-selection cut strings (data)
│   ├── weights.yaml                #   MC weight strings (data)
│   ├── variables.yaml              #   variable list for control plots/DNN
│   ├── generate_tff_configs.py     #   regenerates TauFakeFactors' preselection YAMLs
│   │                               #   from the central YAMLs above (config-sync tool)
│   ├── logging_setup_configs.py
│   └── shapes/                     #   data tables / thin adapter shims (NOT selection logic)
│       ├── control_binning.py, gof_binning.py, taues_measurement_binning.py
│       │    # binning-edge arrays (np arrays don't serialize cleanly to YAML)
│       └── tff_adapter.py          #   reads TauFakeFactors' generated preselection YAML
│
├── shapes/                         # Shape production
│   ├── produce_shapes.py           #   main entry point: ntuple_processor booking/execution
│   ├── preselect.py                #   downstream preselection skim (CROWN-directory-compatible
│   │                               #   output; reused by both signal and, via TFF, background)
│   ├── do_estimations.py           #   post-processing: fake-factor/QCD/embedding estimations
│   ├── convert_to_synced_shapes.py #   bridges produce_shapes.py output -> Combine-ready synced
│   │                               #   shape file (consumed by combine_datacards/, tau_es/)
│   ├── utils.py                    #   dataset/file helpers, tauES dataset booking
│   ├── selection/                  #   executable, era/channel-conditional selection logic
│   │   ├── channel_selection.py    #     trigger/tau-ID/veto cuts (reads config/cuts.yaml)
│   │   ├── process_selection.py    #     per-process MC weight strings (reads config/weights.yaml)
│   │   ├── category_selection.py   #     SR/CR category definitions, DNN_CLASS_MAPPING
│   │   └── variations.py           #     systematic variation (Up/Down) definitions
│   └── estimations/                 #   fakefactors.py, qcd.py, ttbar_emb.py, additionals.py
│
├── plotting/
│   ├── plot_shapes_control.py      #   mplhep/CMS-style control plots (Run2+Run3 era labels)
│   ├── process_ordering.py         #   background stack ordering/colors
│   └── compare_control_shapes.py   #   bin-by-bin shape comparator (new vs. legacy ROOT file)
│
├── combine_datacards/               # Combine-datacard construction (absorbed from
│   │                                 # CombineHarvester/SMRun2Legacy; pure Python, no C++)
│   ├── make_datacards.py           #   main entry point: category/process/systematics ->
│   │                                 #   ExtractShapes -> AddSystematics -> CardWriter
│   ├── categories.py, processes.py, systematics.py, tools.py
│   └── compare_datacards.py         #   datacard-level comparator
├── datacards/                       # Thin CLI wrappers chaining combine_datacards/ + real
│   │                                 # Combine/CMSSW binaries (produce_datacard.py etc. call
│   │                                 # combine_datacards/make_datacards.py; run_gof.py/
│   │                                 # run_impacts.py drive combineTool.py/combine themselves)
│   ├── produce_datacard.py, produce_workspace.py
│   └── produce_gof_datacard.py, produce_gof_workspace.py, run_gof.py, run_impacts.py
│
├── btag_efficiencies/                # B-tag efficiency measurement (extracted out of the
│   │                                 # TauFakeFactors submodule — it measures a detector-level
│   │                                 # quantity, unrelated to fake-factor derivation)
│   ├── run_btag_efficiency.py       #   single entry point, --step {preselect,calculate,all}
│   ├── calculate_efficiency.py       #   the actual efficiency-map calculation
│   ├── generate_configs.py           #   regenerates preselection YAMLs from central config
│   └── configs/{era}/                #   per-era preselection/measurement YAMLs
│
├── tau_es/                           # TauES measurement (extracted from smhtt_ul's
│   │                                 # tauID_SFs_dev branch / CombineHarvester's `origin/tauES`)
│   ├── energy_scales.py              #   canonical 100-point shift grid (-12.0%..+8.0%, 0.2%)
│   ├── make_taues_datacard.py        #   builds the Combine datacard (taues RooMorphing fit)
│   ├── run_taues_fit.py              #   workspace + MultiDimFit subcommands
│   └── run_taues_category.py         #   chains the above for one (era, category); condor unit
│
├── condor/                           # Direct HTCondor submission (no law/luigi task graph)
│   ├── common.py                     #   JobSpec/SubmissionPlan/wrapper-script/submit() machinery
│   ├── submit_shapes.py, submit_plotting.py, submit_training.py
│   ├── submit_btag_efficiency.py, submit_taues_fit.py
│   └── run/                          #   generated per-invocation wrapper/submit/log files (gitignored)
│
├── common/                           # Generic utilities (not analysis config, not selection logic)
│   ├── cmsenv.py                     #   run_in_cmsenv()/get_fitdir() -- shells out to
│   │                                 #   utils/setup_cmssw.sh once, for datacards/*.py & tau_es/
│   ├── conda_env.py                  #   run_in_conda() -- activates `taukitflow`, for run.py
│   ├── lcg_env.py                    #   get_output_features() under the CVMFS LCG view (PRESEL)
│   ├── sample_paths.py               #   Run3 CROWN ntuple/friend-tree path construction
│   ├── helper_collection.py          #   ObjBuildingDict/NestedDefaultDict/STXS helpers
│   └── ntuple_processor_config_helper.py  # booking-graph glue for ntuple_processor
│
├── friends/
│   └── build_friend_tree.py          # XSEC friend-tree production (used by `run.py XSEC`)
│
├── trainings/                        # DNN training pipeline
│   ├── create_training_dataset.py    #   ROOT shapes -> per-event feather folds (plain Python)
│   ├── adjust_config.py, plot_losses.py, setup.yaml, src/
│   └── uncertainty-aware-training/   #   submodule: the actual NN training-loop task graph (law)
│
├── utils/
│   ├── setup_cmssw.sh                # sources `cmsenv` (CMSSW_15_0_2) -- kept as bash, see below
│   └── setup_root.sh                 # sources the CVMFS LCG ROOT view -- kept as bash, see below
│
├── TauFakeFactors/                   # submodule: fake-factor measurement code
├── ntuple_processor/                 # submodule: RDataFrame booking/optimization layer
├── output/, logs/, validation_database/  # generated/working directories (gitignored)
└── STATUS.md                         # cross-session narrative log of how this repo got here
                                       # (phase-by-phase decisions/validation numbers) --
                                       # this README is the "how do I use it today" reference
```

A few placements worth calling out because they weren't obvious the first time:

- **`shapes/selection/`** (not `config/shapes/`) holds the four modules that are
  *executable, era/channel-conditional logic* (`channel_selection.py`,
  `process_selection.py`, `category_selection.py`, `variations.py`) — they read their cut
  *values* from `config/cuts.yaml`/`config/weights.yaml`, but the branching logic itself is
  Python, not YAML, because it's genuinely conditional (per-era WP overrides, STXS
  stitching-weight calculation, etc.), not flat data. `config/shapes/` still holds pure data
  tables (binning-edge arrays) and a thin adapter shim, but not selection logic.
- **`common/`** (not `utils/`) holds generic, non-analysis-specific utility code
  (`helper_collection.py`, `ntuple_processor_config_helper.py`, the env-wrapper modules).
  It's deliberately not `utils/` — a script invoked directly (as `run.py`/condor wrappers do)
  puts its own directory first on `sys.path`, and `shapes/utils.py` (an unrelated flat module)
  would shadow a top-level `utils` package for exactly that invocation style.
- **`combine_datacards/`** vs. **`datacards/`**: `combine_datacards/` is the actual
  category/process/systematics/datacard-construction logic (absorbed from
  CombineHarvester/SMRun2Legacy's Python bindings usage); `datacards/` is the thin CLI layer
  that chains it with the real external `combineCards.py`/`combineTool.py`/`combine` binaries.

---

## Environment setup

There are **three separate environments**, used for different pipeline stages — mixing them
in the same shell session breaks things (see `common/conda_env.py`'s and
`common/cmsenv.py`'s module docstrings for the concurrency reasoning: sourcing the CVMFS LCG
ROOT view sets `PYTHONHOME` to the LCG interpreter, and a subsequent `conda activate` puts
conda's Python first on `PATH` without clearing `PYTHONHOME` — the mismatch crashes Python at
startup with `Fatal Python error: init_fs_encoding`).

### 1. `taukitflow` conda env — shape production, training, condor submission

```bash
conda env create -f environment.yml   # creates the "taukitflow" env
conda activate taukitflow
```

Includes ROOT + XRootD bindings, `numpy`/`scipy`/`pandas`/`uproot`/`awkward`/`mplhep`/
`scikit-learn`/`tensorflow`/`keras`. This is what `run.py`'s XSEC/SHAPES/SHAPES-NOSYS/
TRAIN-SHAPES/CONFIGS/PRESEL/FF-MEASURE/TRAIN-DATASET modes activate automatically via
`common/conda_env.py` — you generally don't need to `conda activate` it yourself before
running `run.py`, only for running the underlying scripts (`shapes/produce_shapes.py`, etc.)
directly.

### 2. `environment-plotting.yml` env — PLOT mode only

```bash
conda env create -f environment-plotting.yml
conda activate taukitflow-plotting
```

Same scientific-Python stack as `taukitflow` plus `root` (needed because
`plotting/plot_shapes_control.py` reads histograms via `ROOT` directly), kept as a **separate**
env from `taukitflow` on purpose (see `run.py`'s module docstring) — `run.py PLOT` does not
auto-activate any conda env; activate `taukitflow-plotting` yourself first.

### 3. CMSSW / `cmsenv` — Combine, datacards, GoF/Impacts, tauES fit

```bash
source utils/setup_cmssw.sh          # override CMSSW_BASE_DIR/CMSSW_RELEASE/SCRAM_ARCH first
                                      # if your checkout isn't at the script's default
export FITDIR=/path/to/combine/workdir   # where datacards/workspaces get read/written;
                                          # defaults to $(pwd) if unset
```

Needed for anything importing `CombineHarvester.CombineTools` or invoking `combine`/
`combineTool.py`/`text2workspace.py`/`combineCards.py`: `combine_datacards/*.py`,
`datacards/*.py`, `tau_es/{make_taues_datacard,run_taues_fit,run_taues_category}.py`. This is
a real environment-mutation shim (sources CMSSW's `cmsenv`), so it's kept as bash rather than
ported to Python (`subprocess.run` can't mutate its own parent shell's `PATH`/`PYTHONPATH`) —
`common/cmsenv.py` is the one place Python code shells back out to it.

**`utils/setup_root.sh`** is the third, similar bash shim (sources a CVMFS LCG ROOT view,
`LCG_102` or `LCG_106` depending on hostname) — used only lazily, by `run.py`'s PRESEL mode
via `common/lcg_env.py`, to read `config.analysis.get_output_features()` under an
interpreter that has `pyyaml`. You should not normally need to source it yourself.

### 4. `fake_factors` conda env — TauFakeFactors' own scripts

`TauFakeFactors/preselection.py`/`ff_calculation.py`/`ff_corrections.py` (and
`btag_efficiencies/calculate_efficiency.py`, which reuses TFF's `helper` package) import
`ruamel.yaml`, which is **not** in `taukitflow`. A separate `fake_factors` conda env (see
`TauFakeFactors/environment.yml`) has the right dependencies. `run.py`'s PRESEL/FF/FF-CORR/
FF-MEASURE modes invoke these scripts via a plain `subprocess.run` with whatever Python is on
`PATH` — activate `fake_factors` yourself before running them (this is a pre-existing
requirement, not something this framework's own code manages for you).

### Submodules

```bash
git submodule update --init --recursive
```

Initializes `TauFakeFactors/` and `ntuple_processor/`. `trainings/uncertainty-aware-training/`
is also a submodule; only needed for `run.py TRAIN` (the actual NN training-loop, not the
dataset-prep step).

---

## Pipeline: entry points, in the order they're meant to run

All modes below run through the single entry point **`run.py`** (the Phase 6d Python
replacement for the old `run.sh` — same modes, same flags, same env-var-fallback precedence:
`--flag` wins, then an inherited environment variable, then a hardcoded default). Run
`python3 run.py --help` for the authoritative, always-up-to-date flag list; what follows is a
practical walkthrough in pipeline order.

```bash
python3 run.py <MODE> [options]
# or, with explicit env vars instead of flags (both styles are equivalent):
ERA=2024 NTUPLETAG=htt_260602_2024-25_v5 CHANNELS=mt python3 run.py SHAPES
```

### 1. XSEC — build cross-section friend trees

```bash
NTUPLETAG=htt_260602_2024-25_v5 ERA=2024 python3 run.py XSEC
```

Runs `xsec/build_friend_tree.py` (needs `taukitflow`, auto-activated) against the CROWN
production, writing `crossSectionPerEventWeight`/`negative_events_fraction`/
`numberGeneratedEventsWeight` friend trees under `.../CROWNFriends/xsec/`. Required before any
real MC shape production — these branches are not present on the bare CROWN ntuple.

### 2. SHAPES / SHAPES-NOSYS — shape production

```bash
NTUPLETAG=htt_260602_2024-25_v5 ERA=2024 CHANNELS=mt VS_JET_WP=Medium \
  python3 run.py SHAPES              # full systematic-variation shapes
NTUPLETAG=htt_260602_2024-25_v5 ERA=2024 CHANNELS=mt \
  python3 run.py SHAPES-NOSYS        # nominal-only, faster iteration
```

Runs `shapes/produce_shapes.py` (booking/execution via the `ntuple_processor` submodule),
then `shapes/do_estimations.py` for fake-factor/QCD/embedding post-processing, writing
`output/<era>-<channels>-shapes.root`. Pass `FF_FRIENDS_DIR=...` to also enable the
fake-factor friend-tree path. **Note:** `--directory` (and the store path this mode builds
for you) must be the bare `/store/user/.../CROWNRun` path, not a full `root://host/...` URL,
when reading via xrootd — `run.py`/`condor/submit_shapes.py` already build it correctly;
this only matters if you invoke `shapes/produce_shapes.py` directly.

For 2018 (Run2/tauES) production, `run.py`'s built-in path-construction
(`common/sample_paths.py`) is Run3-only — invoke `shapes/produce_shapes.py` directly with the
real store path instead, e.g.:

```bash
python3 shapes/produce_shapes.py --era 2018 --channels mt --vs-jet-wp Medium \
  --vs-ele-wp VVLoose --xrootd \
  --directory /store/user/jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNRun \
  --mt-friend-directory /store/user/jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNFriends/xsec \
  --process-selection emb --skip-systematic-variations
```

(the `--mt-friend-directory ... /CROWNFriends/xsec` is required for real MC background
processes for 2018 — `numberGeneratedEventsWeight`/`crossSectionPerEventWeight`/
`negative_events_fraction` live in a friend tree there, not as bare branches, same convention
as Run3.)

### 3. PLOT — control plots

```bash
conda activate taukitflow-plotting
ERA=2024 CHANNELS=mt VARIABLES=m_vis,pt_1,pt_2 python3 run.py PLOT
```

Runs `plotting/plot_shapes_control.py` (mplhep/CMS-style) against the shapes ROOT file
`SHAPES`/`SHAPES-NOSYS` produced, writing PNG/PDF control plots.

### 4. TRAIN-SHAPES — shapes for DNN training input

```bash
NTUPLETAG=htt_260602_2024-25_v5 ERA=2024 CHANNELS=mt python3 run.py TRAIN-SHAPES
```

Same production step as SHAPES but nominal-only with training-specific binning; feeds
`TRAIN-DATASET` below.

### 5. CONFIGS — collect ntuple_processor configs without producing histograms

```bash
NTUPLETAG=htt_260602_2024-25_v5 ERA=2024 CHANNELS=mt python3 run.py CONFIGS
```

Useful for debugging the sample/selection/cut wiring without a real RDataFrame run.

### 6. Fake-factor measurement: GEN-TFF-CONFIGS → PRESEL → FF → FF-CORR (or FF-MEASURE)

```bash
python3 run_fake_factor_measurement.py --era 2024 --channels et,mt,tt   # chains all 4 steps
# equivalently, step by step (each also exists as its own run.py mode for granular reruns):
python3 run.py GEN-TFF-CONFIGS --era 2024 --channels et,mt,tt   # regenerate TFF YAMLs
conda activate fake_factors
python3 run.py PRESEL   --era 2024 --channels et,mt,tt          # TauFakeFactors/preselection.py
python3 run.py FF       --era 2024 --channels et,mt,tt          # TauFakeFactors/ff_calculation.py
python3 run.py FF-CORR  --era 2024 --channels et,mt,tt          # TauFakeFactors/ff_corrections.py
```

Also `run.py FF-MEASURE --era 2024 --channels et,mt,tt` runs the same chain in one call.
Always run `GEN-TFF-CONFIGS` first after any `config/cuts.yaml`/`config/weights.yaml` edit —
it's the build step that keeps TauFakeFactors' own generated YAMLs in sync with central
config; nothing runs it automatically on every edit.

### 7. Datacards / Combine (needs `cmsenv`, see Environment setup above)

```bash
source utils/setup_cmssw.sh
export FITDIR=/path/to/combine/workdir

python3 datacards/produce_datacard.py 2024 mt stxs_stage0_run3     # era channel analysis
python3 datacards/produce_workspace.py 2024 stxs_stage0_run3 4     # eras analysis [cores]

# Goodness-of-fit / Impacts (single-variable, single-category workflow):
python3 datacards/produce_gof_datacard.py 2024 mt m_vis --embedding --jetfakes
python3 datacards/produce_gof_workspace.py 2024 mt m_vis
python3 datacards/run_gof.py 2024 mt m_vis <synced_shape_file> saturated 20 htt_260602_2024-25_v5 0 4
python3 datacards/run_impacts.py 2024 mt m_vis 4
```

`datacards/*.py` are thin CLI wrappers around `combine_datacards/make_datacards.py` (the
category/process/systematics/CardWriter logic) plus real external
`combineCards.py`/`combineTool.py`/`combine` binary invocations (`run_gof.py`/
`run_impacts.py`). Run `--help` on each for the exact positional-argument order (it varies
per script — some take `ntuple_tag` last, `produce_gof_datacard.py` also takes
`--use-asimov`/`--embedding`/`--jetfakes` flags).

### 8. TauES measurement (needs `cmsenv`; validated mechanism, see gap note below)

```bash
source utils/setup_cmssw.sh
python3 tau_es/run_taues_category.py --era 2018 --channel mt --category Inclusive \
  --input-file output/2018-mt-taues-synced.root --output-folder output/taues_fits
```

Chains `tau_es/make_taues_datacard.py` (builds a Combine datacard with a continuous `taues`
RooMorphing parameter) → `tau_es/run_taues_fit.py workspace` → `tau_es/run_taues_fit.py fit`
(`combine -M MultiDimFit`) for one (era, category) — categories are `DM0`, `DM1`, `DM10_11`,
`Inclusive`. The synced input file comes from
`shapes/produce_shapes.py --special-analysis TauES` →
`shapes/do_estimations.py --special TauES` →
`shapes/convert_to_synced_shapes.py --special TauES`.

### 9. B-tag efficiency measurement

```bash
conda activate fake_factors
python3 btag_efficiencies/run_btag_efficiency.py --era 2024 --channel mt --step all
```

`--step preselect` runs `TauFakeFactors/preselection.py` (reused as-is) against
`btag_efficiencies/configs/{era}/preselection_{channel}.yaml`; `--step calculate` runs
`btag_efficiencies/calculate_efficiency.py`. Pass `--regenerate-configs` to rebuild the
preselection YAML from central config first (needed after a `config/cuts.yaml` edit).

### 10. NN training

```bash
NTUPLETAG=htt_260602_2024-25_v5 ERA=2024 CHANNELS=mt python3 run.py TRAIN-SHAPES

TRAIN_CONFIG=trainings/setup.yaml BASE_DATASET_DIR=/ceph/$USER/smhtt_ul_new/training_datasets \
  python3 run.py TRAIN-DATASET       # plain Python, no law/condor -- builds feather folds

TRAIN_TASK=RunAllCENNTConfusionMatrixWorkflow CUDA_DEVICE=0,1 \
  python3 run.py TRAIN               # shells out to `law run ...` inside
                                      # trainings/uncertainty-aware-training/ (submodule-owned
                                      # task graph, deliberately left as-is -- see STATUS.md
                                      # Phase 6c)
```

`TRAIN-DATASET` (`trainings/create_training_dataset.py`) has never used `law` — it's a plain
`argparse` script; `run.py` just gives it a discoverable mode. `TRAIN` is the only remaining
`law`-based step in this whole framework, and it's entirely inside the
`uncertainty-aware-training` submodule, not TauKITFlow's own code.

---

## HTCondor submission

Every batch-shaped stage has a direct HTCondor submitter under `condor/` — plain Python
(`condor/common.py`'s `JobSpec`/`SubmissionPlan`/`submit()`), shelling out to `condor_submit`
directly. No `law.contrib.htcondor` task graph is used (see `condor/common.py`'s module
docstring for the reasoning: `law` is used exactly once elsewhere in this repo, for a local
task graph inside the training submodule, and standing up a whole new HTCondor workflow
system for "one job per (era, channel)" fan-out would be disproportionate). All scripts
default `--eras`/`--channels` to `config.analysis.RUN3_ERAS`/`get_channels()`, and support
`--dry-run` (validates real classads via `condor_submit -dry-run` without queuing).

```bash
python3 condor/submit_shapes.py   --ntupletag htt_260602_2024-25_v5 --eras 2024,2025 \
  --channels et,mt,tt --vs-jet-wp Medium --dry-run       # one job per (era, channel)
                                                          # (--split-by-process for finer fan-out)
python3 condor/submit_plotting.py --input-dir output --eras 2024 --channels et,mt \
  --output-dir /web/$USER/public_html/CMS_HTT --dry-run  # one job per (era, channel)
python3 condor/submit_training.py --master-config trainings/full_dataset_config.yaml \
  --eras 2024,2025 --channels et,mt,tt \
  --base-dataset-directory /ceph/$USER/training_datasets --dry-run
python3 condor/submit_btag_efficiency.py --step preselect --eras 2024,2025 \
  --channels et,mt,tt --dry-run                          # --step calculate: one job per era
python3 condor/submit_taues_fit.py --era 2018 --input-file output/2018-mt-taues-synced.root \
  --output-dir output/taues_fits --categories DM0,DM1,DM10_11,Inclusive --dry-run
```

`submit_shapes.py`/`submit_plotting.py`/`submit_training.py`/`submit_btag_efficiency.py`
(`--step preselect/calculate`) run inside the `taukitflow` conda env (the generated wrapper
activates it directly — deliberately does **not** also source `utils/setup_root.sh`, which
crashes the interpreter, see Environment setup above). `submit_taues_fit.py` is the one
exception: it needs the CMSSW/Combine environment, selected via
`SubmissionPlan.env_mode="cmssw"` in `condor/common.py`, which sources `utils/setup_cmssw.sh`
in its generated wrapper instead.

Not yet validated: an actual multi-hour real batch run of any of these against live xrootd
data completing on the KIT-ETP pool — dry-run classad validation plus small real test
submissions (environment probe, argument-passing probe) are the evidence recorded in
`STATUS.md`; a full production run should be launched interactively when convenient.

---

## Run2 (2018), tauES and embedding support

Run3 (all 6 eras, all 4 channels where data exists) is the primary, fully validated
production target. Run2/tauES/embedding support is real but narrower — documented honestly
here rather than implied to be equivalent:

- **2018/mt is validated end-to-end against a fresh `smhtt_ul` reference**: a real bin-by-bin
  control-shape comparison (`plotting/compare_control_shapes.py`) gives **36/36 histograms
  agreeing within 3σ** (12 processes × `m_vis`/`pt_1`/`pt_2`, max n_sigma 0.21, max rel_diff
  3.02% on one low-statistics process) — see `STATUS.md` Phase 6a for the full table and root
  causes. `et`/`tt`/`em` channels and 2016/2017 eras have **no validation data available** in
  the reference production and are not validated.
- **Embedding** (tau-embedded data samples) is real and validated for 2018/mt: the embedded
  weight chain (`emb_genweight`/`emb_idsel_wgt_*`/`emb_triggersel_wgt`/...) matches the
  legacy reference bit-for-bit once both frameworks' embedding code is actually exercised
  (smhtt_ul's live checkout has embedding commented out entirely — TauKITFlow's does not).
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

## Further reading

`STATUS.md` is the phase-by-phase development log for this rework — every file move, every
bug found and fixed, every validation run's actual numbers, and every deliberate
design/naming decision (with reasoning) live there. Read it if you want to know *why*
something is the way it is; this README is only meant to answer *how do I run it*.
