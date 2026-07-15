# TauHarvest

SM H→ττ analysis framework for Run3. The name is a play on [CombineHarvester](https://github.com/cms-analysis/CombineHarvester) and the τ (tau) analyses it targets.

TauHarvest handles the full shape-based analysis chain — from CROWNRun ntuples to Combine datacards — for the Run3 SM H→ττ measurement. It is deliberately **not** a fork of `smhtt_ul`: background sample lists and preselection cuts are sourced directly from [TauFakeFactors](https://github.com/KIT-CMS/TauFakeFactors) to avoid duplication, while signal samples and all Run3-specific selections are defined internally.

**Supported eras:** 2022preEE · 2022postEE · 2023preBPix · 2023postBPix · 2024 · 2025  
**Channels:** et (e + τ_h) · mt (μ + τ_h) · tt (τ_h + τ_h) · em (e + μ)  
**Shape production:** [ntuple_processor](https://github.com/KIT-CMS/ntuple_processor) submodule  
**Plotting:** [mplhep](https://github.com/scikit-hep/mplhep) with CMS style (no Dumbledraw)

---

## Repository Structure

```
TauHarvest/
├── config/
│   ├── shapes/
│   │   ├── tff_adapter.py         # Reads TauFakeFactors preselection YAMLs → file/sample lists
│   │   ├── signal_files.py        # Run3 signal sample names (ggH, qqH, VH, ttH)
│   │   ├── channel_selection.py   # Run3 trigger & tau ID selections
│   │   ├── process_selection.py   # MC weight selections (lumi, trigger, tau ID)
│   │   ├── variations.py          # Systematic variation definitions
│   │   ├── control_binning.py     # Control plot variable binning
│   │   └── category_selection.py  # SR/CR category definitions
│   ├── helper_collection.py
│   ├── logging_setup_configs.py
│   └── ntuple_processor_config_helper.py
├── shapes/
│   ├── produce_shapes.py          # Main shape production (uses ntuple_processor)
│   ├── do_estimations.py          # Post-processing estimations (FF, QCD, EMB)
│   ├── utils.py                   # Dataset / file helpers
│   └── estimations/               # Estimation classes: FF, QCD, ttbar, addl
├── plotting/
│   ├── plot_shapes_control.py     # mplhep CMS-style control plots
│   └── process_ordering.py        # Background stack ordering
├── datacards/
│   ├── produce_datacard.py        # SM H→ττ datacard production
│   ├── produce_workspace.py       # RooWorkspace for Combine
│   ├── produce_gof_datacard.py    # GoF datacard
│   ├── produce_gof_workspace.py   # GoF workspace
│   ├── run_gof.py                 # End-to-end GoF test (datacard→workspace→combine→collect)
│   └── run_impacts.py             # End-to-end Impacts (nuisance-ranking) workflow
├── friends/
│   └── build_friend_tree.py       # Cross-section friend tree builder
├── trainings/                     # NN training pipeline (multiclass DNN)
├── common/
│   ├── cmsenv.py                  # Run CMSSW/Combine binaries via utils/setup_cmssw.sh
│   ├── conda_env.py               # Run a subprocess inside the `taukiktflow` conda env
│   ├── lcg_env.py                 # Run something under the CVMFS LCG view (utils/setup_root.sh)
│   └── sample_paths.py            # CROWN ntuple/friend-tree path helpers (Run3)
├── utils/
│   ├── setup_root.sh              # ROOT environment setup (CVMFS LCG view -- bash, sources env)
│   └── setup_cmssw.sh             # CMSSW / Combine environment (cmsenv -- bash, sources env)
├── ntuple_processor/              # Submodule: KIT-CMS/ntuple_processor
├── TauFakeFactors/                # Submodule: KIT-CMS/TauFakeFactors
├── environment.yml                # Conda environment
└── run.py                         # Main entry point
```

---

## Key Components

### `config/shapes/tff_adapter.py`

The central innovation of TauHarvest. Instead of maintaining a separate list of background sample names and preselection cuts, this module reads them directly from the [TauFakeFactors](https://github.com/KIT-CMS/TauFakeFactors) preselection YAML configs. This guarantees that the background definitions used for shape production are always consistent with those used for fake factor derivation.

The adapter provides three public functions:
- `get_background_sample_names(era, channel)` — returns `{dataset_key: [sample_nicknames]}` for backgrounds
- `get_tff_event_selection(era, channel)` — returns the base event selection cuts from TFF
- `build_files_dict(channels, era)` — assembles the full `files[era][channel]` dict consumed by `shapes/utils.py`, merging background samples from TFF with signal samples from `signal_files.py`

### `config/shapes/channel_selection.py`

Run3-only channel selection. Raises `ValueError` for any non-Run3 era. Key trigger requirements:

| Channel | Trigger |
|---------|---------|
| mt | Single muon: `pt_1 > 26`, `trg_single_mu24` or cross-trigger `mu20tau27` |
| et | Single electron: `pt_1 > 32`, `trg_single_ele30` or cross-trigger `ele24tau30` |
| tt (2022/23) | Double-τ HPS: `pt_1,2 > 40`, `trg_double_tau35_mediumiso_hps` |
| tt (2024/25) | Double-τ PNet: `pt_1,2 > 35`, `trg_double_tau30_mediumiso_pnet` |
| em | Single muon: `pt_2 > 26`, `trg_single_mu24` |

The `modify_for_ff_DR` helper flips the OS sign requirement and inverts the tau ID for fake factor application regions.

### `config/shapes/variations.py`

Defines all systematic variation objects understood by `ntuple_processor`. Each variation is a named pair of Up/Down shifts. Variations that alter event selection (TES, JES, MET) cause ntuple_processor to re-run the full selection, while weight-only variations (b-tag, tau ID SFs, trigger SFs) are applied as weight replacements. Run3-specific notes:
- No L1 prefiring variation (Run3 only)
- `btagging_2024` variation for 2024/2025 (PNet tagger)
- `jet_es_hem` for 2022 HEM issue corrections

Fake factor weight variations are controlled via `FF_OPTIONS`, which supports several modes:
- `fake_factor` — simple FF weight from friend tree
- `fake_factor_with_bias_corr` — applies process-fraction-weighted bias correction
- `fake_factor_with_DR_SR_corr` — applies DR→SR extrapolation correction
- `fake_factor_with_DR_SR_and_bias_corr` — both corrections combined

### `shapes/produce_shapes.py`

The main entry point for shape production. It uses `ntuple_processor`'s `UnitManager` / `GraphManager` / `RunManager` to build a processing graph over the CROWNRun ntuples, then executes it (optionally in parallel). Key workflow:

1. Calls `build_files_dict()` from `tff_adapter` to get sample → file mappings
2. Books nominal shapes for all processes and channels
3. Books systematic variations per era (via `config/shapes/variations.py`)
4. Executes the graph with `RunManager` using `--num-processes` worker processes
5. Writes all histograms to a single output ROOT file

Modes selectable via arguments:
- `--control-plots` — produces shapes for a configurable set of kinematic variables
- `--gof-inputs` — single-category shapes for GoF tests
- `--analysis` — full SR shapes with all categories (default)
- `--skip-systematic-variations` — nominal only (used for `SHAPES-NOSYS` and `TRAIN-SHAPES`)
- `--collect-config-only` — dumps the ntuple_processor YAML config without processing (used for `CONFIGS`)

### `shapes/do_estimations.py`

Runs post-processing estimations on the ROOT file produced by `produce_shapes.py`:
- **Fake factor** (`--do-fake-factors`): scales jetFakes contribution from the anti-isolated DR region using fake factor weights
- **QCD estimation** (`--do-qcd`): ABCD method using same-sign / anti-isolated control regions
- **Embedding** (`--do-embedding`): replaces MC-based ZTT with tau-embedded data
- **ttbar EMB contamination** (`--do-emb-ttbar`): subtracts residual MC ttbar from embedding

### `plotting/plot_shapes_control.py`

Produces CMS-style control plots from the shapes ROOT file using mplhep. Each plot includes a stacked background histogram, an optional signal overlay (scaled ×50 by default), data points with error bars, and a Data/MC ratio panel. Outputs are saved as both `.png` and `.pdf`.

### `trainings/`

Multiclass deep neural network training pipeline. The network is trained to discriminate between ggH, qqH, ZTT, TT, W, and QCD classes simultaneously. Key files:
- `setup.yaml` — training variables, architecture hyperparameters, era flags
- `create_training_dataset.py` — reads shapes ROOT file, converts to pandas/numpy arrays
- `train_multiclass_nn.py` — Keras/TensorFlow DNN training with k-fold cross-validation
- `combine_to_cennt_folds.py` — combines fold models into a single inference model
- `adjust_config.py` — patches ntuple_processor config for training variable extraction

Training variables include kinematic quantities (`pt_1`, `pt_2`, `m_vis`, `m_fastmtt`, `mjj`, `pt_dijet`, `mt_1`, `pzetamissvis`, angular separations), jet multiplicity/b-tag counts, per-era flags (`is_2022postEE`, `is_2024`, etc.), and process label flags.

---

## Setup

### 1. Clone with submodules

```bash
git clone --recurse-submodules <this-repo-url>
cd TauHarvest
```

Or after cloning:
```bash
git submodule update --init --recursive
```

Two submodules are used:
- **`ntuple_processor/`** (`KIT-CMS/ntuple_processor`, branch `master`) — required for all shape production; provides the `UnitManager`/`GraphManager`/`RunManager` API used by `produce_shapes.py`
- **`TauFakeFactors/`** (`KIT-CMS/TauFakeFactors`) — provides preselection YAML configs consumed by `tff_adapter.py`, the full fake factor derivation code, and the sample database (`TauFakeFactors/datasets/`) used by `build_friend_tree.py`; `nanoAOD_v12` covers 2022/2023, `nanoAOD_v15` covers 2024/2025

### 2. Create the conda environment

```bash
conda env create -f environment.yml
conda activate tauharvest
```

The environment includes: `numpy`, `scipy`, `pandas`, `matplotlib`, `mplhep`, `uproot`, `awkward`, `pyyaml`, `tqdm`, `scikit-learn`, `xgboost`, `tensorflow`, `keras`.

### 3. Set environment variables

```bash
export NTUPLETAG="my_ntuple_tag_v1"
export NTUPLE_DIRECTORY="/store/user/${USER}/CROWN/ntuples/${NTUPLETAG}/CROWNRun/"
export ERA="2022postEE"     # one of the Run3 eras
export CHANNELS="et,mt,tt"
```

For fake factor shapes, also set:
```bash
export FF_FRIENDS_DIR="/store/user/${USER}/CROWN/ntuples/${NTUPLETAG}/CROWNFriends/ff/"
```

### 4. Set up ROOT and CMSSW

Shape production requires ROOT (for ntuple_processor):
```bash
source utils/setup_root.sh
```

Datacard and workspace production additionally require a CMSSW environment with CombineHarvester:
```bash
source utils/setup_cmssw.sh
export FITDIR=/path/to/combine/workdir
```

---

## Typical Analysis Workflow

A complete analysis run follows these steps:

```
CROWNRun ntuples
      │
      ▼
  XSEC friend trees       (run.py XSEC)
      │
      ▼
  Shape production         (run.py SHAPES or SHAPES-NOSYS)
      │  └── produce_shapes.py  ──► shapes.root
      │  └── do_estimations.py  ──► shapes.root (FF/QCD/EMB estimated)
      │
      ├─► Control plots         (run.py PLOT)
      │       └── plot_shapes_control.py ──► png/pdf
      │
      └─► Datacards             (datacards/produce_datacard.py)
              └── Workspace     (datacards/produce_workspace.py)
                      └─► Combine fits
```

For NN-score categories, insert a training step before the final shape production:

```
  Training shapes            (run.py TRAIN-SHAPES)
      │
      ▼
  Create training dataset    (trainings/create_training_dataset.py)
      │
      ▼
  Train DNN                  (trainings/train_multiclass_nn.py)
      │
      ▼
  Full shape production with NN score variable
```

---

## Modes of Operation

All modes are invoked via `run.py`:

```bash
python3 run.py <MODE> [additional-args]
```

### XSEC — Build cross-section friend trees

```bash
python3 run.py XSEC
```

Builds ROOT friend trees with cross-section weights using `friends/build_friend_tree.py`.

### SHAPES — Shape production with systematics

```bash
python3 run.py SHAPES
```

Runs `shapes/produce_shapes.py` over the CROWNRun ntuples using `ntuple_processor`, booking all systematic variations (TES, JES, MET, btag, etc.).  
Then runs `shapes/do_estimations.py` for fake factor / QCD estimations.

### SHAPES-NOSYS — Nominal shapes only (fast)

```bash
python3 run.py SHAPES-NOSYS
```

Same as `SHAPES` but with `--skip-systematic-variations`. Useful for fast iteration and control plots.

### PLOT — Control plots

```bash
python3 run.py PLOT
```

Produces CMS-style control plots using mplhep from the shapes ROOT file.  
Output: `output/plots/${ERA}/png/` and `output/plots/${ERA}/pdf/`.

Optional variables can be set:
```bash
VARIABLES="m_vis,pt_1,pt_2" python3 run.py PLOT
```

### TRAIN-SHAPES — Shapes for NN training

```bash
python3 run.py TRAIN-SHAPES
```

Produces nominal-only shapes with training-specific binning, used as input for `trainings/create_training_dataset.py`.

### CONFIGS — Collect ntuple_processor YAML configs

```bash
python3 run.py CONFIGS
```

Collects ntuple_processor configuration files without running any histogram production. Useful for debugging the sample/selection setup.

---

## TauFakeFactors Integration

TauHarvest reads background sample lists and preselection cuts directly from the [TauFakeFactors](https://github.com/KIT-CMS/TauFakeFactors) submodule (`TauFakeFactors/`) via `config/shapes/tff_adapter.py`. This avoids duplicating sample lists and ensures that shape production always uses exactly the same preselection as was used when deriving the fake factors. Having TauFakeFactors as a submodule also means fake factors can be recalculated from within this framework without maintaining a separate checkout.

The path to the preselection configs is resolved automatically relative to the repo root:
```
TauHarvest/TauFakeFactors/configs/smhtt_ul/{era}/preselection_{channel}.yaml
```
No hardcoded paths are used. If the submodule is not yet initialised, `tff_adapter.py` raises a `FileNotFoundError` with instructions.

Each YAML file contains a `processes` dict with entries like:
```yaml
processes:
  DYjets:
    samples:
      - DYJetsToLL_M-50_TuneCP5_13p6TeV-madgraphMLM-pythia8_Run2022EE_v2
      - ...
  ttbar:
    samples:
      - TTTo2L2Nu_TuneCP5_13p6TeV-powheg-pythia8_Run2022EE_v2
      - ...
```

The adapter maps TFF process names to `ntuple_processor` dataset keys:

| TFF name | Dataset key | Note |
|----------|-------------|------|
| `DYjets` | `DY` | |
| `ttbar` | `TT` | |
| `diboson` | `VV` | merged with ST |
| `ST` | `VV` | single-top merged into VV |
| `Wjets` | `W` | |
| `data` | `data` | |

Signal samples (ggH, qqH, VH, ttH) are **not** present in TFF configs and are defined separately in `config/shapes/signal_files.py`, keyed by era and production mode.

---

## Run3 Luminosities

| Era | Lumi (fb⁻¹) |
|-----|------------|
| 2022preEE | 7.98 |
| 2022postEE | 26.67 |
| 2023preBPix | 18.06 |
| 2023postBPix | 9.69 |
| 2024 | 219.7 |
| 2025 | 220.94 |

---

## Systematics

Systematic variations are defined in `config/shapes/variations.py`. Run3-specific notes:

- **No L1 prefiring** (Run3 uses ECAL DPS corrections instead)
- **PNet b-tagging** (`btagging_2024`) for 2024/2025 eras
- **HEM issue corrections** (`jet_es_hem`) for 2022 eras
- Tau energy scale, electron energy scale, jet energy scale/resolution all alter event selection → require ntuple_processor reprocessing

The following systematic groups are booked during shape production:

| Group | Type | Description |
|-------|------|-------------|
| `tauES_*` | Shape | Tau energy scale shifts per decay mode (genuine τ, e→τ, μ→τ fakes) |
| `eleES_*` | Shape | Electron energy scale / resolution |
| `muES_*` | Shape | Muon momentum scale |
| `jetES_*` | Shape | Jet energy scale / resolution (AK4 jets) |
| `unclMET_*` | Shape | Unclustered MET |
| `btagging_*` | Weight | b-tagging efficiency SFs (deep-jet for 2022/23, PNet for 2024/25) |
| `tauID_*` | Weight | Tau vs-jet, vs-ele, vs-muon ID SFs per WP and pT bin |
| `triggerSF_*` | Weight | Trigger efficiency SFs |
| `pileup_*` | Weight | Pileup reweighting |
| `topPt` | Weight | Top quark pT reweighting (ttbar only) |
| `zPt` | Weight | Z pT reweighting (DY only) |
| `ff_*` | Weight | Fake factor uncertainties (normalisation, extrapolation, DR→SR) |
| `EMB_*` | Weight | Tau embedding uncertainties |
| `theory_*` | Weight | QCD scale, PDF, αS uncertainties (signal only) |

---

## Datacards & Combine

After producing shapes, create datacards and workspaces:

```bash
# Set FITDIR to your CombineHarvester working directory
export FITDIR=/path/to/combine/workdir

./datacards/produce_datacard.py 2022postEE mt smhtt
./datacards/produce_workspace.py 2022postEE smhtt 4
```

For goodness-of-fit tests:
```bash
./datacards/produce_gof_datacard.py 2022postEE mt m_vis
./datacards/produce_gof_workspace.py 2022postEE mt m_vis
```

---

## NN Training

```bash
# Produce training shapes first
python3 run.py TRAIN-SHAPES

# Create training dataset
python trainings/create_training_dataset.py --config trainings/setup.yaml --era $ERA --channel mt

# Train
# see trainings/ for the current (Phase 6c-owned) training entry point
```

The DNN is a multiclass classifier. Classes: `ggH`, `qqH`, `ZTT`, `TT`, `W`, `QCD`. Training uses k-fold cross-validation; each fold produces a separate model which is then used for inference on the complementary data fold. The fold models are combined into a single deployable model by `combine_to_cennt_folds.py`.

Input features (defined in `trainings/setup.yaml`) include:
- **Kinematic**: `pt_1`, `pt_2`, `eta_1`, `eta_2`, `m_vis`, `m_fastmtt`, `pt_vis`, `mt_1`, `mt_2`, `mt_tot`, `pzetamissvis`, `met`
- **Di-tau system**: `deltaR_ditaupair`, `deltaEta_ditaupair`
- **Jet variables**: `jpt_1`, `jpt_2`, `jeta_1`, `jeta_2`, `mjj`, `pt_dijet`, `njets`, `nbtag`, `deltaR_jj`, `deltaEta_jj`
- **Cross-object angular separations**: `deltaR_1j1`, `deltaR_2j2`, `deltaR_12j1`, `deltaR_12j2`, etc.
- **Era flags**: `is_2022preEE`, `is_2022postEE`, `is_2023preBPix`, `is_2023postBPix`, `is_2024`, `is_2025`
- **Process labels**: `is_ggh_htautau`, `is_vbf_htautau`, `is_dyjets`, `is_ttbar`, `is_wjets`, `is_embedding`

---

## Troubleshooting

**`FileNotFoundError: TFF preselection config not found`**  
The TauFakeFactors submodule is not yet initialised. Run:
```bash
git submodule update --init TauFakeFactors
```

**`ValueError: Era 'X' is not a supported Run3 era`**  
TauHarvest is Run3-only. Supported eras: `2022preEE`, `2022postEE`, `2023preBPix`, `2023postBPix`, `2024`, `2025`. Run2 eras are not supported.

**Shape production is slow**  
Use `SHAPES-NOSYS` for initial checks. Set `NPROCS` and `NTHREADS` to match available CPU cores, e.g. `NPROCS=4 NTHREADS=8 python3 run.py SHAPES`. For a single channel, add `CHANNELS=mt`.

**ntuple_processor submodule not found**  
Run `git submodule update --init --recursive` from the TauHarvest root.

**`ModuleNotFoundError` for `ntuple_processor` or `config`**  
The `run.py` script exports `PYTHONPATH`. If running Python scripts directly, set it manually: `export PYTHONPATH="${PYTHONPATH}:${PWD}"`.
