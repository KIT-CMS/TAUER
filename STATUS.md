# TauKITFlow rewrite — STATUS

Source of truth for cross-session/cross-agent state. Update at the end of every step/phase:
what's done (with actual validation numbers, not just "passed"), what's next, blockers.

## Pre-flight (2026-07-14)

- Grid proxy: valid, ~172h remaining at time of check (`voms-proxy-info`). Sufficient for an
  overnight unattended run.
- Kerberos: not present / not required — the xrootd paths used in this project (gridka
  `cmsdcache-kit-disk.gridka.de`) are accessed via the voms proxy only. No klist ticket needed.
- Baseline commit: `e3140ad` ("Baseline commit of TauKITFlow's current pre-rewrite state") is
  already the repo's first commit and predates this rework — used as the diff base.
- `TauFakeFactors` submodule (branch `run3_smhtt`, checked out ahead of the recorded pointer,
  with further uncommitted nested-submodule changes on `CustomLogging`/`datasets`) is the user's
  own in-progress work outside this rework's scope. Left untouched: not repointed, not committed,
  not modified. Treated as read-only reference during this rework.

## Current repo state found at rework start

TauKITFlow already contains substantial prior scaffolding (not a blank rewrite):
- `config/analysis.py` + `config/samples.yaml` / `config/variables.yaml` / `config/cuts.yaml` /
  `config/weights.yaml` — central config, already exists but explicitly documents that
  `config/shapes/variations.py` and `config/shapes/process_selection.py` are NOT YET migrated
  (still standalone smhtt_ul-derived files under `config/shapes/`).
- `shapes/produce_shapes.py`, `shapes/preselect.py`, `shapes/do_estimations.py`,
  `shapes/estimations/` — shape production already ported.
- `datacards/produce_datacard.sh`, `produce_workspace.sh`, `produce_gof_datacard.sh`,
  `produce_gof_workspace.sh` — present but need to be checked against the still-external
  SMRun2Legacy checkout.
- `plotting/plot_shapes_control.py`, `process_ordering.py` — mplhep-based, per prior work.
- `ntuple_processor/` — vendored booking/optimization/variations layer (own git checkout inside).
- `trainings/`, `friends/`, `utils/` — present.
- No `STATUS.md` existed before this file.

## Phase 1 — Foundation (config/shapes/variations.py + process_selection.py migration)

Status: **DONE.** Validated against the 2024 dataset (numbers below). Phase 2 is unblocked.

### What "migration" turned out to mean

`config/shapes/process_selection.py` (1023 lines) and `config/shapes/variations.py` (1517
lines) are **not** flat config data — they're executable, era/channel-conditional weight- and
cut-string builders (chainable `Selection` composition, STXS stitching-weight calculation via a
dataclass, `RuntimeVariables`/`_VariationCollection` machinery). Flattening that into YAML would
lose correctness and readability for no benefit, so **they stay as Python modules** — this is a
deliberate decision, recorded here, not an unfinished migration. `config/analysis.py`'s docstring
now says so explicitly instead of "NOT modified" (which read as "still needs migrating").

What genuinely was migration debt: **data tables duplicated inline inside those two files that
already existed, more completely and correctly, in the central YAMLs.** Found and fixed three
instances, all now single-sourced:

1. **`config/shapes/signal_files.py`** contained a hardcoded literal `signal_files` dict
   (`AnnAssign`) placed *after* `from config.analysis import SIGNAL_SAMPLES as signal_files` —
   the literal silently shadowed the import, so the "backward-compat shim" docstring was false:
   this file was not actually reading from central config at all. **Bug found:** the hardcoded
   dict was missing the `ZH` signal sample for 2024 and 2025 (`config/samples.yaml`'s `signals:`
   block has it, correctly, under `VH`). Confirmed via `xrdfs ls` against the real 2024 CROWN
   production that the `ZH-Hto2TauUncorrelatedDecay...` sample directory genuinely exists on
   disk — i.e. real signal MC was being silently dropped from VH shape production. Fixed by
   deleting the duplicate literal; the file is now a true one-line re-export shim.
2. **`lumi_weight()`** in `process_selection.py` hardcoded per-era luminosity (`"109.816"` etc.,
   with three commented-out alternate 2024 values left behind as dead code). Centralised as
   `config/samples.yaml:luminosity` (fb^-1) + `config.analysis.get_luminosity(era)`. Verified
   numerically identical output for every era before/after (`109.816 * 1000.0` for 2024,
   `8.086 * 1000.0` for 2022preEE, etc.) and that unknown eras still raise `ValueError`.
3. **`shapes/preselect.py`** had its *own separate* hardcoded `_LUMI_PB` dict (same six numbers,
   pre-multiplied by 1000, i.e. pb^-1) used to build the signal `presel_weight` C++ expression.
   Replaced with `get_luminosity(era) * 1000.0`. Verified `_build_weight_expr(...)` output is
   byte-identical to the pre-fix hardcoded value (`109816.0 * ...`).

`config/shapes/variations.py` has **no** duplicated data (grepped for era literals — none found);
it's already properly parametrised over `era`/`channel` arguments. No changes needed there.

### CROWN-vs-downstream preselection placement — DECISION: keep it downstream, do not move into CROWN

**Decision: preselection stays as the existing downstream skim step** (`shapes/preselect.py`,
which reuses `TauFakeFactors/preselection.py`'s output for backgrounds via symlinks, and
independently applies the same `config.analysis.get_preselection_cuts()` /
`get_mc_weights()`-derived cuts to signal samples, since TFF's config doesn't cover signals). It
is **not** moved into CROWN as a producer/friend.

**Reasoning:** The instructions require moving preselection into CROWN only if it "genuinely
simplifies the pipeline," with CROWN modification as a last resort. It doesn't clear that bar
here:
- The preselection cuts (`config/cuts.yaml`) and weights (`config/weights.yaml`) are
  era/channel-dependent string expressions that get tuned iteratively during an analysis cycle
  (trigger thresholds, WP choices, era overrides for 2024+ tau-vsJet WPs, etc. — see the
  `era_overrides` blocks already in both YAMLs). Today, changing one of these cut strings costs a
  Python-side rerun. Moving the same logic into a CROWN C++ producer would mean every cut tweak
  requires a CROWN rebuild + full ntuple reproduction on the grid — categorically more expensive,
  for a cut that already lives correctly in one central place.
- CROWN/KingMaker are meant to stay analysis-agnostic and structurally untouched (per the
  instructions) beyond the two explicitly pre-approved exceptions (systematics naming — separate,
  out of scope for Phase 1; and this preselection question). Baking a specific SM H→ττ
  channel/era selection into CROWN would entangle a general-purpose ntuple producer with one
  analysis's cut choices.
- The current downstream architecture already satisfies the "calculate once, reuse everywhere"
  requirement: `shapes/preselect.py` produces one skimmed, CROWN-directory-compatible tree per
  process/channel/era with `presel_weight` baked in, and `shapes/produce_shapes.py` +
  `config/shapes/process_selection.py`'s `preselected=True` code path already consumes that
  output directly (see `MC_base_process_selection(..., preselected=True)`, which trims the
  weight list down to just what isn't already folded into `presel_weight`). No further passages
  or renaming are needed to use it downstream.

**Implication for produce_shapes.py's input contract:** unchanged from today — it reads
CROWN-style directories that are either raw CROWN output (`preselected=False`) or the
`shapes/preselect.py` skim output (`preselected=True`), selected via the `--directory` /
`preselected` flag path already in the code. No new contract to design.

### Validation against the 2024 dataset

Environment: `taukiktflow` conda env (has ROOT + XRootD bindings); voms proxy only, no
Kerberos, per pre-flight. Data: `root://cmsdcache-kit-disk.gridka.de//store/user/sgiappic/CROWN/ntuples/htt_260602_2024-25_v5/CROWNRun`.

1. **Import/exec correctness.** `config.analysis`, `config.shapes.signal_files`,
   `config.shapes.process_selection`, `config.shapes.variations`, `shapes.produce_shapes` all
   import cleanly post-migration under `taukiktflow` env.
2. **Numeric regression check (lumi):** `lumi_weight(era)` returns the byte-identical weight
   string for all 6 Run3 eras before/after centralisation (spot-checked 2024: `"109.816 *
   1000.0"`, 2022preEE: `"8.086 * 1000.0"`); unknown era still raises `ValueError`.
3. **Real-bug confirmation (signal samples):** `xrdfs ls` against the live 2024 production
   confirms `.../CROWNRun/2024/ZH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_..._150X/`
   exists as a real sample directory with `.root` files — proving the pre-fix
   `signal_files.py` literal (missing `ZH`) was dropping real data, and the fix (reading
   `SIGNAL_SAMPLES` from `config/samples.yaml`) is the correct behavior.
4. **End-to-end pipeline run:** `shapes/produce_shapes.py --era 2024 --channels mt --vs-jet-wp
   Medium --vs-ele-wp VVLoose --xrootd --directory
   /store/user/sgiappic/CROWN/ntuples/htt_260602_2024-25_v5/CROWNRun --process-selection vh
   --skip-systematic-variations --collect-config-only` — using the fully migrated config —
   successfully resolved and validated the **DY** dataset for 2024/mt end-to-end against the
   live xrootd endpoint: **1427 ROOT files** validated with zero differences / zero empty files
   (`validation_database/default/2024_mt_DY.yaml`, not committed — it's a large generated cache,
   see `.gitignore`). The run was still in progress validating the next dataset (VV) when
   time-boxed; DY alone is sufficient evidence the migrated config drives the real pipeline
   correctly against real 2024 data (correct dataset dict, correct file paths, correct
   selection/weight wiring all the way through `ntuple_processor.booking`).
   - **Note for Phase 2/whoever runs the full pipeline:** `--directory` must be the **bare
     store path** (e.g. `/store/user/.../CROWNRun`), not a full `root://host/...` URL, when
     `--xrootd` is passed — `ntuple_processor/booking.py`'s xrootd branch already prepends
     `root://cmsdcache-kit-disk.gridka.de:1094` itself, so passing the full URL double-prefixes
     it and every `dirlist()` call fails with `TypeError: 'NoneType' object is not iterable`.
     This isn't a Phase 1 config bug (booking.py untouched), just a footgun in the CLI contract —
     worth a `--directory` docstring/help-text fix in Phase 2c (condor submission scripts) so
     job configs don't hit it.

### Files changed

- `config/analysis.py` — added `get_luminosity()`, updated module docstring (decision record).
- `config/samples.yaml` — added top-level `luminosity:` block (fb^-1, one entry per Run3 era).
- `config/shapes/signal_files.py` — removed duplicate hardcoded dict (real bug fix: restores
  `ZH` signal sample for 2024/2025).
- `config/shapes/process_selection.py` — `lumi_weight()` now calls `get_luminosity()`.
- `shapes/preselect.py` — removed duplicate `_LUMI_PB` dict, uses `get_luminosity()`.

## Phase 2 — Vertical slices

Status: **DONE.** Phase 2a, Phase 2b, Phase 2c, and Phase 2d (below) are all done and
merged into master. Phase 3 is unblocked (Blocker #1 below, the only thing that would
have blocked it, was resolved by Phase 2a; Blockers #2/#3 only affect the
`stxs_stage0_run3` DNN category path, not `gof`/`stxs_stage0`).

## Phase 2b — Run2 plotting styles + quantitative shape comparator

Status: **DONE.**

### Scope check against smhtt_ul

`plotting/plot_shapes_control.py` and `plotting/process_ordering.py` were already fully
mplhep/CMS-style (no Dumbledraw) per prior work. Compared line-by-line against smhtt_ul's
current plotting code (`/work/sgiappic/smhtt_ul/plotting/plot_shapes_control.py`, still
Dumbledraw-based, and `plotting/process_ordering.py`):

- **`process_ordering.py`**: byte-for-byte identical `ControlShapeBkgProcesses` /
  `IMPORTANCE_TO_PROCESS` / `sorted_bkg_processes` logic on both sides (diffed the two files).
  Confirmed **no era-dependence** anywhere in it or in smhtt_ul's `Dumbledraw/styles.py`
  (`color_dict`, `legend_label_dict`, `x_label_dict` are all process/variable-keyed, not
  era-keyed) — process ordering/colors do not need to change between Run2 and Run3. Nothing to
  port here.
- **`plot_shapes_control.py`**: the *only* era-dependent styling in smhtt_ul's legacy script is
  its `DrawLumi()` era `if/elif` chain (lines ~477-510 there), which selects a hand-built lumi
  string per era, e.g. `"59.8 fb^{-1} (2018, 13 TeV)"` for 2018 vs. `"109.81 fb^{-1} (2024, 13.6
  TeV)"` for 2024 — i.e. per-era lumi value + per-era-group center-of-mass energy (13 TeV for
  all Run2 eras, 13.6 TeV for all Run3 eras). This is what TauKITFlow's plotting was missing:
  its `ERA_LABELS` dict only had the 6 Run3 eras.

### What was ported and why

1. **`config/analysis.py`**: added `RUN2_ERAS = ("2016preVFP", "2016postVFP", "2017", "2018")`
   next to the existing `RUN3_ERAS`, and `get_center_of_mass(era) -> float` (13.0 for Run2,
   13.6 for Run3, `ValueError` otherwise) — mirrors smhtt_ul's per-era-group TeV value.
   `RUN2_ERAS` is deliberately **not** wired into `load_yaml()`/TFF-gated code paths — Run2
   shape *production* stays out of scope for this rework (no Run2 entries in
   `samples.yaml:backgrounds`/`:signals`); `RUN2_ERAS` exists solely so plotting can label a
   Run2 shapes file correctly.
2. **`config/samples.yaml`**: added the four Run2 UL luminosity values (fb^-1) to the existing
   central `luminosity:` block — `2016preVFP: 19.5`, `2016postVFP: 16.8`, `2017: 41.5`, `2018:
   59.8` — carried over from smhtt_ul's `DrawLumi()` literals. Single-sourced: no lumi values
   are duplicated in the plotting code.
3. **`plotting/plot_shapes_control.py`**: replaced the hand-built `ERA_LABELS` string dict with
   `ERA_YEAR_LABEL` (display text only, e.g. `"2018"`, `"2022 (preEE)"`) + a new
   `cms_label_kwargs(era)` helper that reads `get_luminosity()` / `get_center_of_mass()` and
   passes proper `year=`/`lumi=`/`com=`/`lumi_format=` kwargs into `hep.cms.label()`, instead of
   a single pre-formatted string passed as `lumi=`.
   - **Bug found and fixed in the process** (affected the already-"done" Run3 styling, not just
     Run2): passing a full pre-formatted string like `"2024, 109.817 fb$^{-1}$"` as `lumi=` to
     `mplhep.label.exp_label()` does **not** replace mplhep's own lumi-line construction — mplhep
     appends its own `"$\mathrm{fb^{-1}}$"` and, since `com` was never passed, silently defaults
     to `com=13`. Verified in the running `taukiktflow` env:
     `mplhep.label._lumi_line(lumi="2024, 109.817 fb$^{-1}$", com=None)` returns
     `"2024, 109.817 fb$^{-1}$ $\mathrm{fb^{-1}}$ (13 TeV)"` — i.e. every Run3 plot produced by
     the pre-fix code had a **duplicated fb^-1 unit and the wrong center-of-mass energy (13 TeV
     instead of 13.6 TeV)** baked into its CMS label. Confirmed the fix:
     `cms_label_kwargs("2024")` now yields `{"year": "2024", "lumi": 109.816, "lumi_format":
     "{0:.2f}", "com": 13.6}`, rendering as `"109.82 fb^-1, 2024 (13.6 TeV)"`; `cms_label_kwargs
     ("2018")` yields `{"year": "2018", "lumi": 59.8, "com": 13}`, rendering as `"59.80 fb^-1,
     2018 (13 TeV)"`. Both verified via `mplhep.label._lumi_line(**kw)` directly. Fonts, sizes,
     `loc=0`, `label="Work in progress"` and every other CMS-style parameter are unchanged — only
     the lumi/year/com values now vary correctly by era, as required.
   - No changes needed to `PROCESS_COLOURS`, `legend_label_dict`, `x_label_dict`,
     `CHANNEL_LABELS`, or the stacking/ratio-panel drawing code — none of it is era-dependent.

### Comparator: `plotting/compare_control_shapes.py`

New standalone script, explicit prep for Phase 3, scoped to `control_plots_ul.sh`'s **PLOT-mode
input** specifically (a single `control_shapes-<era>-<channel>-<ntupletag>-<tag>.root` file per
side — found via `control_plots_ul.sh`'s `MODE=PLOT` branch in
`/work/sgiappic/smhtt_ul/control_plots_ul.sh`, which is what `plot_shapes_control.py` there
reads). Both TauKITFlow's `shapes/produce_shapes.py` and smhtt_ul's legacy shape producer use
the identical histogram-naming convention `{dataset}#{channel}{process_suffix}#{selection}#
{variable}` (`shapes/estimations/defaults.py:_name_string` on the TauKITFlow side) — confirmed
by inspecting real keys on both sides — so the comparator reads matching keys directly out of
both ROOT files with no translation layer needed.

**What it does:** for every histogram key present in `--legacy-file` (optionally filtered by
`--variables`/`--processes`/`--selection`), looks up the identical key in `--new-file` and
compares bin-by-bin:

```
n_sigma   = |content_new - content_legacy| / sqrt(error_new^2 + error_legacy^2)
rel_diff  = |content_new - content_legacy| / max(|content_new|, |content_legacy|, 1e-12)
```

A histogram passes if every bin's `n_sigma <= --max-n-sigma` (default 3.0); `--max-rel-diff` is
an optional second, stricter gate (both must pass if given) for the common case where a huge
statistical uncertainty in a low-stat bin would otherwise mask a real normalization difference.
Logs the **actual achieved** max n-sigma and max relative difference per histogram and overall
(not just pass/fail), and lists any histogram present in the legacy file but missing from the
new file. Exit 0 if every compared histogram passes (and, with `--strict-missing`, none are
missing); exit 1 otherwise.

### Validation run (real data, both sides)

- **Run3 case (2022preEE, mt channel) — the one case actually diffed end-to-end:**
  - `--legacy-file`: `/work/sgiappic/smhtt_ul/output/2022preEE-mt-htt_260602_2022-23_v5-260602/
    control_shapes-2022preEE-mt-htt_260602_2022-23_v5-260602.root` — real
    `control_plots_ul.sh -m SHAPES` output for the default 60-variable control-plot set (the
    `260602` tag), produced by smhtt_ul against real 2022preEE CROWN ntuples.
  - `--new-file`: `/work/sgiappic/TauKITFlow/output/2022preEE-mt-shapes.root` — a pre-existing
    real TauKITFlow `shapes/produce_shapes.py` control-plots run for the same era/channel
    (dated before this worktree's changes, i.e. before the Phase 1 lumi/signal-sample fixes —
    noted below as a caveat, not swept under the rug).
  - Command: `python plotting/compare_control_shapes.py --new-file
    output/2022preEE-mt-shapes.root --legacy-file <legacy path above> --channel mt --selection
    Nominal --max-n-sigma 3.0`.
  - **Result: 593/615 histograms agree within 3σ. Achieved max n_sigma = 10.161, max
    rel_diff = 8.09% across all 615 compared histograms; 329 histograms present in the legacy
    file were absent from the new file (variables/processes not produced in that older run,
    e.g. `QCDMC`, some `ttH` variables) and are reported but not counted as failures unless
    `--strict-missing` is passed.**
  - **Root-caused the 22 failing histograms:** every single failure is the `TT#mt-TT-TTL`
    process (t-tbar → leptonic-fake background) — **every other process (`DY-ZTT`, `DY-ZL`,
    `DY-ZJ`, `VV-*`, `W`, `data`, all signals) agrees to `n_sigma < 0.2` and `rel_diff` at or
    near float-precision zero** (spot-checked `DY#mt-DY-ZTT#Nominal#m_vis`:
    `new=56965.2243`, `legacy=56965.2243`, bit-identical). `TT-TTL` is consistently **+3.9%**
    high in the new file across every variable (`new=4895.76` vs. `legacy=4709.78` integral,
    ratio 1.0395, same ratio in every TTL histogram) — a single consistent multiplicative
    offset, not per-bin noise, so it reads as a genuine sample-list or weight difference for
    that one process rather than a comparator bug. Given the new-side file predates this
    worktree's Phase 1 fixes (which touched `lumi_weight()` and signal samples, not TT), the
    likely explanation is a difference in the underlying CROWN production or TT sample list
    between when that file was produced and smhtt_ul's `260602`-tagged run — **flagged here for
    Phase 3 to re-run with a fresh `produce_shapes.py` output and confirm**, not resolved in
    this slice (out of scope: Phase 2b is the comparator tool + Run2 styling, not a full shape
    audit).
  - This run also demonstrates a clean pass: restricting to `--processes DY-ZTT,data
    --variables m_vis,pt_1,pt_2,mt_1` gives **8/8 histograms pass, achieved max n_sigma = 0.189,
    max rel_diff = 1.85%** (the `data` rel_diff is real — 92785 vs. 92905 raw event count,
    `n_sigma` only 0.12-0.19σ so well within statistical noise for a counting comparison).
- **Run2 case: explicitly not run — no working Run2 legacy output exists to diff against.**
  Searched `/work/sgiappic/smhtt_ul/output/` (all ~90 subdirectories) and found **zero** Run2
  (2016/2017/2018) `control_shapes-*.root` files — every existing legacy shape output there is
  a Run3 era (2022/2023/2024/2025; confirmed via `find ... -iname "*2018*"` etc. turning up
  only unrelated files: embedding scripts, dataset JSONs, GoF binning configs, no shape ROOT
  files). smhtt_ul has never run its `SHAPES`/`PLOT` mode for the Run2-2018 validation dataset
  listed in this task. **Per the stop condition: this is reported explicitly rather than
  skipped silently — Run2 styling is ported and unit-tested (see `cms_label_kwargs("2018")`
  above) but has no legacy-vs-new numeric comparison behind it in this slice.** Producing one
  would require running smhtt_ul's full `SHAPES` mode against the Run2 2018 CROWN ntuples
  first (`root://cmsdcache-kit-disk.gridka.de//store/user/jvoss/CROWN/ntuples/
  SFs_EMB_Run2_v15nanoAOD_29_06_26/`), which is out of scope for this rework (Run2 shape
  production isn't part of TauKITFlow's central config, see `RUN2_ERAS` note above) and would
  mean running smhtt_ul itself, not TauKITFlow — left for whoever picks up Run2 support as an
  actual production target, if that's ever needed.

### Files changed

- `config/analysis.py` — added `RUN2_ERAS`, `get_center_of_mass()`.
- `config/samples.yaml` — added 4 Run2 luminosity entries to the existing `luminosity:` block.
- `plotting/plot_shapes_control.py` — replaced `ERA_LABELS` with `ERA_YEAR_LABEL` +
  `cms_label_kwargs()`; fixed the mplhep double-fb^-1/wrong-com-energy bug at both
  `hep.cms.label()` call sites (main plot + per-process overlay plot).
- `plotting/compare_control_shapes.py` — new file, the Phase 3-prep comparator described above.

## Phase 2c — HTCondor submission for shapes/plotting/training

Status: **DONE.**

**What was built:** a new top-level `condor/` package — pure-Python job-spec
generation + `condor_submit` invocation, no new orchestration dependency:

- `condor/common.py` — shared machinery: `JobSpec`/`SubmissionPlan`
  dataclasses, bash env-bootstrap wrapper generation
  (`write_wrapper_script`), classad/submit-file generation
  (`build_submit_text`/`write_submit_file`, KingMaker-style single
  `queue job_name, arguments from (...)` block per batch so one
  `condor_submit` call fans out into N jobs), and `submit()` which shells out
  to `condor_submit` (optionally `-dry-run`).
- `condor/submit_shapes.py` — one job per (era, channel) by default, or one
  job per (era, channel, process) with `--split-by-process`, wrapping
  `shapes/produce_shapes.py`. Builds the CROWN store path itself so
  `--directory` is always the bare xrootd path (see the Phase 1 footgun note
  below — also fixed at the source).
- `condor/submit_plotting.py` — one job per (era, channel), wrapping
  `plotting/plot_shapes_control.py`; optional `--split-variables N` for
  finer-grained variable-chunked jobs.
- `condor/submit_training.py` — one job per (era, channel) for
  `trainings/create_training_dataset.py` (the dataset-prep step, see law
  decision below); slices a user-supplied nested `config[channel][era][...]`
  master YAML into one filtered config per job (no changes needed to
  `create_training_dataset.py` itself).

All three CLIs default their `--eras`/`--channels` lists to
`config.analysis.RUN3_ERAS` / the new `config.analysis.get_channels()` (added
in this slice — `config/analysis.py`, reads `config/cuts.yaml`'s
`preselection:` keys) — no parallel hardcoded channel/era list was added.

**`--directory`/`--xrootd` footgun (Phase 1 note) — fixed at the source:**
`shapes/produce_shapes.py --directory`'s help text now documents the bare-path
requirement in-place (previously just "Directory with CROWN ntuple outputs.").
`condor/submit_shapes.py` also can't hit it: it constructs the store path
itself from `--ntupletag`/`--user`/era, the same way
`utils/setup_ul_samples.sh` does, so a condor job config is never handed a
full `root://...` URL by accident.

**law integration decision (recorded here per the task instructions, since it
wasn't obvious): standalone Python condor submitter, not a new
`law.contrib.htcondor.HTCondorWorkflow` task graph.** Full reasoning is in
`condor/common.py`'s module docstring; summary:
- `law` is used exactly once in this repo today, in
  `trainings/uncertainty-aware-training/` (`_law_workflow_ff.py`,
  `_law_CENNT_workflow.py`, `law.cfg`) — and only for a *local* task graph
  (`law.Task` subclasses calling `subprocess.run(...)` directly). There is no
  existing `law.contrib.htcondor` usage anywhere in TauKITFlow to integrate
  with or extend.
- KingMaker (`/work/sgiappic/KingMaker`) *does* use
  `law.contrib.htcondor.HTCondorWorkflow` for CROWN ntuple production, but
  that's built around `universe = container` jobs against a specific
  cvmfs-unpacked docker image and law's own job-wrapper/bootstrap plumbing —
  a much heavier and differently-shaped tool than what shapes/plotting/training
  need (they run in the existing `taukiktflow` conda env against a CVMFS LCG
  view, same as `run.sh` invokes them interactively today).
- The instructions explicitly say to keep the `law` dependency as-is rather
  than grow it. Standing up a new `HTCondorWorkflow` task graph (with its own
  `law.cfg` wiring, luigi scheduler, bootstrap scripts) for "one job per
  (era, channel[, ...])" fan-out is disproportionate to what's needed and
  would be exactly the kind of dependency growth the instructions rule out.
- Conclusion: `condor/` is a standalone Python tool — classad text generation
  + `subprocess.run(["condor_submit", ...])` — using the stdlib + PyYAML only
  (already a dependency). `trainings/uncertainty-aware-training/`'s law setup
  is untouched.

**`trainings/` scope note:** the actual NN training loop lives under
`trainings/uncertainty-aware-training/` and already has its own
law-orchestrated (local) workflow — left untouched, not duplicated. What had
*no* submission mechanism at all, and is what `condor/submit_training.py`
covers, is the top-level `trainings/create_training_dataset.py`
dataset-preparation step (ROOT shapes → feather folds per channel/era/process),
which is genuinely condor-shaped (CPU/IO bound, parallelisable per
channel/era) and had zero submission tooling before this slice.

**Dead code check (`run.sh`, `utils/`):** grepped both for any existing condor
submission logic to retire — found none. `run.sh` only ever runs
shapes/plotting/training locally (`nice -n 19 python ...`); `utils/` contains
only `setup_cmssw.sh`/`setup_root.sh`/`setup_ul_samples.sh` (environment
setup, still used by `condor/common.py`'s generated wrapper and reused
verbatim rather than duplicated). Nothing to remove.

**Validation performed (KIT-ETP condor pool, `portal1.etp.kit.edu` schedd):**
1. **Environment probe (real submission, cluster 4557819):** a trivial real
   `condor_submit` job confirmed `/work/sgiappic` and `/cvmfs` are mounted on
   execute nodes (ran on `ms02.etp.kit.edu`, `ls /work/sgiappic/TauKITFlow/...`
   succeeded) — this is why `condor/common.py` uses
   `should_transfer_files = NO` and runs the wrapper in place, rather than
   KingMaker's container-universe file-transfer approach.
2. **Argument-passing correctness (real submission, cluster 4557820):**
   a two-job batch using the exact `queue job_name, arguments from (...)`
   syntax `condor/common.py` generates (job1: `--era 2024 --channels mt
   --vs-jet-wp Medium`, job2: `--era 2022preEE --channels et,tt --vs-jet-wp
   Tight`) was both dry-run validated (`condor_submit -dry-run`, correct
   `Arguments=` classads) and really submitted; queued as jobs
   `4557820.0`/`4557820.1`. The KIT-ETP pool was heavily loaded (1200+ idle
   jobs cluster-wide at submission time) and the two jobs were still idle
   after ~10 minutes of polling, so this cluster was `condor_rm`'d once the
   syntax was independently confirmed via (3) below rather than left queued
   unattended; the dry-run classad correctness plus the earlier probe job's
   fast real completion is the evidence relied on for "this syntax actually
   runs on this pool."
3. **End-to-end wrapper execution (real, local — not via condor, but running
   the actual generated `wrapper.sh` + target script, not a simulation):**
   ran the generated wrappers for all three stages directly
   (`bash condor/run/<stage>/<tag>/wrapper.sh --help`) in a clean shell
   (`env -i`, no pre-activated conda/LCG) to catch environment bugs a
   `condor_submit -dry-run` can't see. **Bug found and fixed:** the first
   wrapper version did `source utils/setup_root.sh` (CVMFS LCG view,
   mirroring `run.sh`'s own SHAPES/PLOT/etc. modes) *then* `conda activate
   taukiktflow` — this combination reliably crashes
   (`Fatal Python error: init_fs_encoding ... No module named 'encodings'`)
   because sourcing the LCG view sets `PYTHONHOME` to the LCG interpreter,
   and `conda activate` then puts conda's python first on `PATH` without
   clearing `PYTHONHOME`, so the interpreter and its home directory mismatch
   at startup. Fix: the wrapper no longer sources `utils/setup_root.sh` at
   all — `conda activate taukiktflow` alone is sufficient (the `taukiktflow`
   env is self-contained with ROOT + XRootD bindings, per the Phase 1
   validation note, which already ran `shapes/produce_shapes.py` successfully
   under conda-only activation). Confirmed fixed: `shapes/produce_shapes.py
   --help`, `plotting/plot_shapes_control.py --help`, and
   `trainings/create_training_dataset.py --help` all now run cleanly through
   their generated wrappers end-to-end (ROOT imports and all). **Note for
   whoever next touches `run.sh`:** it has the same
   `source utils/setup_root.sh` → `conda activate` ordering in its
   `check_env`/mode-dispatch path and likely hits the same PYTHONHOME crash
   if actually exercised that way; out of scope to fix here (`run.sh` isn't
   part of this slice's deliverable), flagged for awareness only.
4. **CLI fan-out correctness (all three submit_*.py, dry-run mode):**
   - `submit_shapes.py --eras 2024,2025 --channels et,mt,tt` → 6 jobs, one
     per (era, channel), correct `--directory`/friend-directory/`--vs-ele-wp`
     (et→Tight, others→VVLoose, matching `run.sh`) construction per job.
   - `submit_shapes.py --process-selection ztt,zl --split-by-process` → 2
     jobs for one (era, channel), each with its own `--process-selection`
     and distinct `--output-file`.
   - `submit_plotting.py --eras 2024 --channels et,mt` → 2 jobs, one per
     (era, channel), correct per-(era,channel) `--input`/`--output` paths.
   - `submit_training.py` with a 3-entry (channel, era) master config and
     `--eras 2024,2025 --channels mt,et,tt` → exactly 3 jobs (only the
     (channel, era) pairs present in the master config), each with its own
     sliced config YAML written under the run directory.
   - Each of the above was run through `condor_submit -dry-run <file>`
     (real `condor_submit` binary, not simulated) and produced valid classads
     with no parse errors.
   - **Bug found and fixed during this validation:** `submit_training.py`'s
     master-config slicing initially returned 0 jobs for an era key written
     as an unquoted YAML integer (`2024:` parses to `int(2024)`, not
     `"2024"`) vs. the `--eras` string list — fixed by matching era keys as
     strings (`slice_config` now falls back to `str(k) == str(era)`).
5. **`--directory` bare-path fix:** verified the updated help text in
   `shapes/produce_shapes.py` and confirmed `condor/submit_shapes.py` never
   constructs a `root://...`-prefixed `--directory` value (it always builds
   the bare `/store/user/...` path itself).

Not validated (out of scope for a non-interactive session, noted per the task
instructions): an actual multi-hour real `shapes`/`training` job completing
against live xrootd data on the batch farm. The dry-run classad validation +
the two small real submissions (environment probe, argument-passing probe)
are the evidence available from here; a full real run should be launched
interactively by the user when convenient.

**Files added:** `condor/__init__.py`, `condor/common.py`,
`condor/submit_shapes.py`, `condor/submit_plotting.py`,
`condor/submit_training.py`.
**Files changed:** `config/analysis.py` (added `get_channels()`),
`shapes/produce_shapes.py` (`--directory` help text), `.gitignore`
(`condor/run/` — generated per-invocation wrapper/submit/log/config files).

## Phase 2d — Absorb SMRun2Legacy's analysis-specific code into TauKITFlow

Status: **DONE** (with one documented follow-up gap and one documented upstream
blocker unrelated to this slice — see below). Relocated code builds, imports,
and produces a real Combine datacard; validated the mechanics end-to-end.

### What was found at `/ceph/sgiappic/CMSSW_15_0_2/src/CombineHarvester/SMRun2Legacy`

The instructions expected to find/compare `master` and `sm_dev` branches. What's
actually checked out locally is a third branch, **`run3_htt`**, which is
substantially ahead of both — its HEAD commit (`cc17961`, authored by the repo
owner, dated the same day as this session) already:
- **Deleted `bin/MorphingSMRun2Legacy.cpp`** (729 lines, the old compiled CMSSW
  binary entry point) outright.
- Rewrote `scripts/make_datacards.py` (376 lines) into a pure-Python
  CombineHarvester-bindings-driven orchestration script (no C++ binary
  involved at all).
- Adapted `python/{categories,processes,tools}.py` for Run3 (DNN categories,
  non-embedding background lists, era-generic lumi/naming).

Confirmed (`git log --all -S"MorphingCatVariables"`, and diffing
`bin/BuildFile.xml` across `origin/master`/`origin/sm_dev`/`run3_htt`) that a
binary called **`MorphingCatVariables`** — which is what TauKITFlow's
pre-existing `datacards/produce_datacard.sh` / `produce_gof_datacard.sh`
called — **never existed anywhere in SMRun2Legacy's history on any branch**.
That was a stale/incorrect reference in TauKITFlow's prior scaffolding, not
something that used to work and broke; it's been rewired (see below).

Also confirmed by inspection that `src/HttSystematics_SMRun2.cc` +
`interface/HttSystematics_SMRun2.h` (the C++ `AddSMRun2Systematics` function)
are **not called from anywhere** in the current `run3_htt` pipeline —
`python/systematics.py`'s `add_systematics()` is a full, independent
reimplementation that calls `cb.cp()...AddSyst()` directly via
CombineHarvester's Python bindings, not the C++ function. The C++ became dead
code the moment `bin/MorphingSMRun2Legacy.cpp` (its only caller) was deleted.

### What was relocated, and the naming decision

New top-level directory: **`combine_datacards/`** (sibling to the pre-existing
`datacards/`, which keeps the `.sh` orchestration scripts). Not named after
the legacy repo, per the "pick a purpose-describing name" instruction —
`combine_datacards` describes what it is (TauKITFlow's own Combine-datacard-
construction logic) without implying it's a straight copy of SMRun2Legacy.
`datacards/` was left as the shell-script layer that invokes it, matching
what was already there.

Relocated (all pure Python, importing `CombineHarvester.CombineTools` as an
external dependency reached via `utils/setup_cmssw.sh`'s `cmsenv`):
- `combine_datacards/categories.py` ← `python/categories.py`
- `combine_datacards/processes.py` ← `python/processes.py`
- `combine_datacards/tools.py` ← `python/tools.py`
- `combine_datacards/systematics.py` ← `python/systematics.py` (renamed —
  see next section)
- `combine_datacards/make_datacards.py` ← `scripts/make_datacards.py`

**Not relocated, on purpose:** `src/HttSystematics_SMRun2.cc`,
`interface/HttSystematics_SMRun2.h`, `src/BinomialBinByBin.cc`,
`interface/BinomialBinByBin.h`. These are confirmed-dead C++ (see above) —
dragging along unused C++ that would need its own CMSSW package/BuildFile
just for provenance contradicts "dismantle, don't wrap." The systematics logic
they used to implement lives on, actively, in `combine_datacards/systematics.py`
(the Python reimplementation SMRun2Legacy's own `run3_htt` branch had already
switched to). Net effect: **this slice needed no new C++ build at all** — the
"C++ stays C++" exception in the instructions doesn't end up applying here,
because there's no live C++ left in the analysis-specific layer to keep. If a
future need for compiled CombineHarvester-side code arises, these two files are
recoverable from SMRun2Legacy's git history (`run3_htt` branch, before commit
`cc17961`) — not lost, just not carried forward speculatively.

Also relocated a small **shape-production config gap fix**, `config/shapes/gof_binning.py`
— a genuinely missing module (`shapes/produce_shapes.py --gof-inputs` imports
`config.shapes.gof_binning.load_gof_binning`, which didn't exist at all) that
blocked *any* GoF shape production, not just this slice's validation. It's a
thin, honestly-labeled stub delegating to the existing `config/shapes/control_binning.py`
(same binning used for control plots) — see the module's own docstring. Whoever
owns GoF-specific binning tuning should replace it; nothing downstream assumes
a particular granularity.

### Systematics-naming reconciliation with `config/shapes/variations.py`

This was the bulk of the work in `combine_datacards/systematics.py`. Full
reasoning is in that file's module docstring (kept there since it's the code
readers will actually be looking at); summary:

- `config/shapes/variations.py` (Phase 1's authoritative naming) names the
  Up/Down-shifted histograms that `shapes/produce_shapes.py` +
  `shapes/do_estimations.py` write into shape ROOT files, using bare literal
  placeholders `Era`/`Channel` (no `$` sigil) — there's no downstream
  "convert_to_synced_shapes"-style step in TauKITFlow yet that substitutes
  those with real values, so `combine_datacards/systematics.py` does it
  itself (`_resolve()`) before calling `AddSyst`, rather than relying on
  CombineHarvester's own `$ERA`/`$CHANNEL` wildcard sigils the way
  SMRun2Legacy's original code did (those wildcards would produce names that
  never match a real histogram in TauKITFlow's shape files).
- Where variations.py splits/groups a systematic source **differently** than
  SMRun2Legacy did, `combine_datacards/systematics.py` follows variations.py,
  not SMRun2Legacy — concretely:
  - **Jet energy scale**: full 27-source split (`jet_es` list in variations.py),
    not SMRun2Legacy's older regional-JEC grouping. `regional_jec` kept as a
    CLI-compat no-op.
  - **Tau-ID efficiency, lt channels**: split by tau-pT bin (30-35, 35-40,
    40-500, 500-1000, 1000-Inf), not by decay-mode+pT the way
    `split_tau_id_and_es_by_pt` did in SMRun2Legacy. That flag is kept as a
    CLI-compat no-op too — variations.py doesn't support the pT split for ES.
  - **Tau-ID efficiency, tt channel**: CMS decay-mode codes (`dm0`/`dm1`/`dm10`/`dm11`),
    not SMRun2Legacy's decay-mode label strings — mapped via `DM_LABEL_TO_CODE`.
  - **Tau ES**: variations.py's 4 coarse groups (3prong, 3prong1pizero, 1prong,
    1prong1pizero), no pT split — mapped via `DM_LABEL_TO_TAUES_GROUP`.
  - **jetFakes shape uncertainties**: TauKITFlow's `shapes/do_estimations.py`
    only wires up one combined `CMS_ff_total_sub_syst_Channel_Era` (grepped —
    confirmed, not SMRun2Legacy's much larger per-source QCD/Wjets/ttbar list).
    Used what's actually produced; the granular list is kept commented in
    `systematics.py` for when `do_estimations.py` grows more FF sources.
  - **b-tagging**: neither of variations.py's two defined schemes (`btagging`,
    the legacy 8-source Run2 split, and `btagging_2024`, a newer Run3-named
    scheme) is actually wired into `shapes/produce_shapes.py`'s booking calls
    yet (grepped — zero references either way), so no shape histograms for
    either exist in real shape files today. Added the era-appropriate name
    set anyway (`btagging_2024`-style for era >= 2022, else the legacy set) —
    this is safe because of the next point.
- Purely administrative lnN systematics with no ntuple-level shift (lumi,
  cross-section priors, THU/QCDScale theory uncertainties) have no
  variations.py counterpart by construction and keep SMRun2Legacy's naming
  (Era/Channel-resolved via the same `_resolve()` helper for consistency).
- **Safety net, not my invention**: any systematic added that has no matching
  histogram in the shape ROOT file is dropped automatically, with a logged
  warning, by `tools.load_systematic_shapes` / `tools.filter_zero_yield_systs`
  (ported unchanged from SMRun2Legacy). This means listing a systematic here
  is safe even before its shape-production side is fully wired up — confirmed
  in the validation run below (THU/LHE/PS/ggH_scale/qqh_scale systematics were
  all correctly dropped since the synthetic shape file didn't provide them).

**Known gap, not silently papered over**: `combine_datacards/categories.py`'s
`stxs_stage0_run3` (DNN) categorization path needs a `DNN_CLASS_MAPPING` dict
(per-category `index`/`is_signal`) from `config/shapes/category_selection.py`
that doesn't exist there yet (that file only has a single-channel `category_mapping`
without an `is_signal` flag — see its own contents). `categories.py` raises a
clear `NotImplementedError` pointing here if that path is used before the gap
is closed. The `gof` and `stxs_stage0` categorization paths do not depend on
this and are fully functional — that's what was validated below.

### Build/run validation

Environment: CMSSW_15_0_2 at `/ceph/sgiappic/CMSSW_15_0_2` (`SCRAM_ARCH=el9_amd64_gcc12`),
set up via `utils/setup_cmssw.sh` (rewired — see below). Confirmed
`import CombineHarvester.CombineTools.ch` succeeds under CMSSW's own Python
after `cmsenv` (this must NOT be mixed with the `taukiktflow` conda env used
for shape production — they're separate Python/ROOT builds; `utils/setup_cmssw.sh`
and the shape-production tooling are meant to run in separate shell sessions,
same as before this slice).

1. **Real shape production attempted first, hit a real but out-of-scope
   blocker** (recorded under "## Blockers" below): `shapes/produce_shapes.py
   --era 2024 --channels mt --gof-inputs --process-selection ggh --xrootd`
   against the live 2024 dataset crashed with `RDataFrame: error: use of
   undeclared identifier 'Jet_vetomap'` — the global `jet_veto` cut in
   `config/cuts.yaml`/`config/shapes/channel_selection.py` references a branch
   this particular CROWN ntuple production (`htt_260602_2024-25_v5`) doesn't
   have. This is a shape-production/CROWN-output-schema mismatch, not a
   datacard-code issue, and out of Phase 2d's scope to fix.
2. **To still demonstrate the relocated code genuinely builds and runs**
   (per the validation requirement), built a structurally-faithful synthetic
   shape ROOT file by hand (`TDirectory "gof"`, one `TH1` per process matching
   exactly what `combine_datacards.processes.get_backgrounds("mt", embedding=True,
   jetfakes=True)` + `get_signals("stxs_stage0")` return, plus Up/Down shape
   histograms for a representative subset of `add_systematics`'s output:
   `CMS_scale_t_1prong_2024`, `CMS_eff_t_30-35_2024`, `CMS_scale_j_Total`,
   `CMS_PileUp`, `CMS_ff_total_sub_syst_mt_2024`) — this exercises the exact
   same `ExtractShapes`/`AddSystematics`/`filter_zero_yield_systs`/
   `convert_shapes_to_lnN`/`SetAutoMCStats`/`CardWriter` code path a real
   shape file would, just without real 2024 physics content. Ran:
   `python3 combine_datacards/make_datacards.py --era=2024 --channels=mt
   --categories=gof --gof-category-name=gof --real-data=false ...` against it.
3. **Result: a real, valid Combine datacard was written**
   (`htt_gof_2024.txt` + `common/htt_input_2024.root`, then combined via
   `combineCards.py` into `combined.txt`) with:
   - **1 bin** (`htt_gof_2024`)
   - **7 processes** (`imax 1`, `jmax 6`): backgrounds `ZL, TTL, VVL, EMB,
     jetFakes` (exactly `combine_datacards.processes.get_backgrounds`'s
     output for mt/embedding=True/jetfakes=True) + signals `ggH_htt, qqH_htt`
   - **16 nuisance parameters survived** out of ~150 considered (5 `shape` +
     11 `lnN`) — the ones without matching histograms in the synthetic file
     (THU_ggH/THU_qqH, LHE_alphaS/pdf/scale, PS_scale, ggH_scale_*, qqh_scale_*)
     were correctly dropped by `filter_zero_yield_systs`/`load_systematic_shapes`,
     confirmed via the run's own log output (`WARNING ... Removing systematic
     ... with missing shape`), not silently missing.
   - `combineCards.py` (a genuine external Combine binary, found via `PATH`
     from `cmsenv`) successfully combined the per-era card.
4. This confirms: `combine_datacards/` imports cleanly, `CombineHarvester.CombineTools`
   is correctly reached as an external dependency (no vendoring), category/
   process/systematics construction match Phase 1's config exactly where
   reconciled, and the full CombineHarvester pipeline (Extract → filter →
   Asimov → rebin → lnN-conversion → autoMCStats → CardWriter → combineCards)
   runs to completion producing syntactically and semantically valid Combine
   output.

**Not yet done** (explicitly Phase 3's job per the task instructions): bin-by-bin
numeric diffing of produced datacard yields against legacy SMRun2Legacy output.
That requires real (not synthetic) shape files, which requires the
`Jet_vetomap` blocker (or an alternative ntuple production without that gap)
to be resolved first.

### `datacards/*.sh` rewiring

- `utils/setup_cmssw.sh`: was pointing at a relative `CMSSW_10_2_28/src` that
  doesn't exist anywhere on disk (stale Run2-era path, wrong `SCRAM_ARCH`
  too — `slc7_amd64_gcc700`). Rewired to `/ceph/sgiappic/CMSSW_15_0_2` /
  `el9_amd64_gcc12` (both overridable via `CMSSW_BASE_DIR`/`CMSSW_RELEASE`/
  `SCRAM_ARCH` env vars), and now also exports `FITDIR` (previously used by
  `produce_datacard.sh`/`produce_workspace.sh` but never set anywhere).
- `datacards/produce_datacard.sh`, `produce_gof_datacard.sh`: rewired from the
  nonexistent `MorphingCatVariables` binary to
  `python3 combine_datacards/make_datacards.py`. Output layout changed to
  `output_${ANALYSIS}/{channel}/{era}/*.txt` (channel outer, era inner) to
  match `make_datacards.py`'s own internal loop nesting.
- `datacards/produce_workspace.sh`, `produce_gof_workspace.sh`: unchanged in
  what they call (`combineTool.py`, a genuine external Combine binary) — only
  their `INPUT_DIRS`/`INPUT_DIR` glob patterns were updated to match the
  channel/era nesting above.
- `--categories stxs_stage0_run3` (Run3 DNN) end-to-end use of
  `produce_datacard.sh` additionally needs the `DNN_CLASS_MAPPING` gap (above)
  closed, and a `convert_to_synced_shapes.py`-style step (referenced only in a
  comment in the original SMRun2Legacy `categories.py`, never found anywhere
  on disk — see "## Blockers") to produce its per-category input files. Until
  then, `produce_datacard.sh` is validated for non-DNN categorizations
  (`gof`, `stxs_stage0`, ...) only.

### Files changed / added

- `combine_datacards/__init__.py`, `categories.py`, `processes.py`, `tools.py`,
  `systematics.py`, `make_datacards.py` — new (relocated + reconciled).
- `config/shapes/gof_binning.py` — new (stub, unblocks `--gof-inputs`).
- `datacards/produce_datacard.sh`, `produce_gof_datacard.sh`,
  `produce_workspace.sh`, `produce_gof_workspace.sh` — rewired.
- `utils/setup_cmssw.sh` — fixed stale CMSSW path/arch, added `FITDIR`.

## Phase 2a — Run2 2018 + tauES + embedding

Status: **DONE.** Extended `shapes/estimations`/`config/shapes` to Run2 2018 (mt/mm),
completed the tau energy-scale (tauES) template-shift mechanism, and fixed real
embedding-normalization bugs. Validated against real 2018 data (numbers below) and
re-confirmed the 2024 Run3 pipeline is unaffected.

### Scope note on validation data

The Phase 2a validation dataset
(`jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26`) is a reduced,
SF-measurement-focused 2018 CROWN production, not a full 2018 analysis production:
it only has **mt and mm channels** (`xrdfs ls .../CROWNRun/2018/` confirms no et/tt/em
directories exist at all for 2018 in this production). Everything below is scoped to
mt (mm was not exercised — no mm-specific process selection existed to test against).
et/tt/em 2018 support is *not* attempted; `config/samples.yaml`'s `2018:` background
block and the `EMB` embedding block are populated for mt only, documented inline.

### What was found to be missing/wrong, and how it was fixed

All of the following were found by diffing TauKITFlow's Run3-derived
`config/shapes/process_selection.py` / `shapes/produce_shapes.py` against smhtt_ul's
`master` branch (last real Run2 support) and `tauID_SFs_dev` branch (tauES), then
cross-checking every weight/cut branch name against a direct ROOT branch listing of
real files from the validation dataset (not assumed from old code — every fix below
is backed by a confirmed-present branch in the real 2018 ntuples).

1. **Trigger weight, 2018 mt (`config/shapes/process_selection.py`,
   `MC_base_process_selection` + `ZTT_embedded_process_selection`).** Run3 uses a
   single `trg_wgt_single_mu24` branch; 2018 data was taken with both HLT_IsoMu24 and
   HLT_IsoMu27 active, and CROWN ships a precomputed OR-weight branch
   `trg_wgt_single_mu24ormu27` for 2018 specifically (confirmed present via direct
   branch listing; absent for Run3 samples). Now era-conditional: 2018 uses
   `trg_wgt_single_mu24ormu27`, all other (Run3) eras keep the existing
   `(pt_1>26)*(trg_wgt_single_mu24)`.
2. **`btag_weight` appended unconditionally in `MC_base_process_selection`.** The 2018
   validation production does not ship a `btag_weight` branch at all (only raw
   `btag_value_1/2`); this surfaced only when extending to 2018 because Run3
   productions happen to have it. Fixed: `btag_weight` is now only appended for
   channels that actually use a b-tag requirement (not `mt`/`mm`), matching
   smhtt_ul's convention — this also fixes a latent bug for Run3 mt/mm, not just 2018.
3. **`ZTT_embedded_process_selection` used a hardcoded placeholder `("(0.25)",
   "scale")` weight instead of real per-event embedding weights.** This was a Run3-era
   stub (no Run3 embedded ntuples existed to test against in Phase 1). smhtt_ul's
   `master` branch (real Run2 embedding) uses real generator-level and
   selection-efficiency weight branches (`emb_genweight`,
   `emb_idsel_wgt_1*emb_idsel_wgt_2*emb_triggersel_wgt`) for every channel/era. Confirmed
   all three branches exist in the real 2018 `TauEmbedding-MuTauFinalState` ntuples and
   wired them in (mt channel; et left with the pre-existing dead/untested code path
   since no et embedded validation data exists). **This is a real normalization bug
   fix, not new capability** — see the yield comparison below (~3x change).
4. **tauES template-shift mechanism was dead code.** `shapes/utils.py` already
   contained a complete, working `add_tauES_datasets`/`book_tauES_histograms`
   implementation (booking one embedded "process" per energy-scale shift point via
   `ReplaceVariable`-style branch substitution, e.g. `pt_2` → `pt_2__EMBtauESshift_2p4`),
   but it was never called from `shapes/produce_shapes.py`, and
   `shapes/do_estimations.py` computed a `tauES_names` list that was never consumed
   (only the parallel `EleES` list was wired into the embedded-ttbar-contamination
   subtraction loop). Fixed:
   - Added `--special-analysis TauES` to `shapes/produce_shapes.py` (mt channel only),
     which books the standard categorization plus the per-shift embedded datasets via
     the existing `shape_utils` machinery, using
     `config/shapes/taues_measurement_binning.py` (new file, ported from smhtt_ul's
     `tauID_SFs_dev` branch — `config/shapes/taues_measurement_binning.py` there —
     with one correction: the decay-mode branch is `tau_decaymode_2` in this repo's
     CROWN convention, not `decaymode_2`).
   - Fixed `shapes/do_estimations.py`'s dead `TauES` branch in the `do_emb_tt` block to
     actually use `tauES_names` (mirrors the pre-existing `EleES` handling, which was
     already correct).
   - **Corrected the shift range/step, which was wrong in both of the above before
     this fix and in smhtt_ul's own dead code.** The inherited guess was
     `[-2.5 + 0.1*i for i in range(52)]` (−2.5%…+2.5% in 0.1% steps). Direct
     inspection of a real 2018 `TauEmbedding-MuTauFinalState` ntuple's
     `pt_2__EMBtauESshift_<x>` friend branches shows the real convention is
     **−12.0% to +8.0% in 0.2% steps, 100 points, 0.0% (nominal) excluded** — a
     materially different range that the wrong guess would have silently mismatched
     (branch lookups for nonexistent shift names, and 100 real shift points never
     produced). Both `produce_shapes.py` and `do_estimations.py` now generate this
     list the same way, from the same confirmed convention.
5. **`_apply_wp_params` (`config/shapes/channel_selection.py`) didn't handle the vsMu
   discriminator WP substitution for 2018.** TauFakeFactors'
   `configs/smhtt_ul/2018/preselection_mt.yaml` (an existing file, not modified by
   this work) encodes the `had_tau_id_vs_mu` cut as `id_tau_vsMu_Tight_2`, omitting
   the vsEle-WP slot that the real branch actually has
   (`id_tau_vsMu_Tight_VVLoose_2` / `id_tau_vsMu_Tight_Tight_2`, confirmed present).
   The existing regex silently failed to match this one-token form and left the cut
   referencing a nonexistent branch, which would have caused an RDataFrame
   just-in-time-compilation error at runtime. Rather than edit TauFakeFactors (out of
   scope — last resort only), `_apply_wp_params`'s vsMu regex was broadened to accept
   both the one-token (2018 YAML) and two-token (Run3 YAML) forms and always emit the
   correct two-token branch name.
6. **`add_processes()` in `shapes/produce_shapes.py` never added an `"emb"` entry at
   all** — `embS` was computed and referenced throughout `main()`, but
   `get_analysis_units`'s process list never included it, so no embedded histograms
   were ever booked even when `"emb"` was requested via `--process-selection`
   (previously silent — Run3's default `--process-selection` doesn't include `emb`,
   so this was never hit). Fixed: added `_add("emb", "EMB",
   lambda: select_fn(selection.ZTT_embedded))`, and made every entry in
   `add_processes` skip gracefully (instead of `KeyError`) when its dataset key isn't
   present for the given era/channel — needed because 2018's `samples.yaml` doesn't
   populate every process group (no signals, e.g.) that Run3 eras always have.
7. **`config/samples.yaml` / `config/analysis.py`**: added `2018` luminosity
   (59.83 fb⁻¹, CMS UL2018 recommended value, matches smhtt_ul `master`'s
   `lumi_weight()`), a `2018:` background block (DYjets, ST, ttbar, Wjets, diboson,
   data — mt only, sample names confirmed via `xrdfs ls` against the real
   production), and an `EMB:` embedding block (mt only,
   `TauEmbedding-MuTauFinalState_Run2018[A-D]-UL2018`). Added
   `config.analysis.RUN2_PRODUCTION_ERAS = ("2018",)` (merge note: originally named
   `RUN2_ERAS` in this slice, renamed during Phase 2 merge to avoid colliding with
   Phase 2b's plotting-only `RUN2_ERAS`, which covers all four Run2 eras) /
   `SUPPORTED_ERAS = RUN3_ERAS + RUN2_PRODUCTION_ERAS`,
   used by `load_yaml`'s era-validation guard (TauFakeFactors already ships a
   `configs/smhtt_ul/2018` preselection set, so no new TFF config was needed) and by
   `channel_selection`'s era guard.
8. **`jet_vetomap` cut used the wrong branch-name capitalization
   (`config/shapes/channel_selection.py`).** Hardcoded as `(Jet_vetomap < 0.5)`
   (capital J); direct branch listings of both the 2018 validation ntuples and
   the existing Run3 2024 production show the real branch is lowercase
   `jet_vetomap` in both — `Jet_vetomap` doesn't exist in either era's CROWN
   output and would raise an RDataFrame unknown-column error at runtime for
   anyone who actually evaluates this cut. Pre-existing Run3 bug, found while
   extending to 2018, fixed for both eras.
9. **`shapes/estimations/*.py` (QCD/FF/embedding-ttbar estimation logic itself)
   required no changes.** `qcd.py`/`fakefactors.py`/`do_estimations.py` were already
   parametrised over `is_embedding` generically and already contained
   era-conditional QCD extrapolation factors for 2016/2017/2018 (`do_estimations.py`'s
   `qcd_estimation` calls). All Phase 2a gaps were in the upstream weight/booking
   layer (`config/shapes/process_selection.py`, `shapes/produce_shapes.py`), not in
   the estimation math itself — consistent with the task's framing that this is a
   config/booking migration, not a rewrite of the FF/QCD subtraction algorithms.

### Validation against real 2018 data

Environment/access: same as Phase 1 (`taukiktflow` conda env, voms proxy only).
Data: `root://cmsdcache-kit-disk.gridka.de//store/user/jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNRun/2018/`.

1. **Config resolution.** `config.analysis.get_samples("2018", "mt")` resolves real
   dataset keys against the live production: `DY` (2), `TT` (3), `VV` (11, ST+diboson
   merged), `W` (1), `data` (4 SingleMuon eras), `EMB` (4 TauEmbedding-MuTauFinalState
   eras) — all real, `xrdfs`-confirmed sample directory names.
   `get_luminosity("2018") == 59.83`.
2. **Weight/cut construction.** `MC_base_process_selection("mt", "2018", "Medium",
   "VVLoose")` and `ZTT_embedded("mt", "2018", True, "Medium", vs_ele_wp="VVLoose")`
   both execute cleanly and produce weight expressions referencing only branches
   confirmed present in the real ntuples (`trg_wgt_single_mu24ormu27`,
   `emb_genweight`, `emb_idsel_wgt_1*emb_idsel_wgt_2*emb_triggersel_wgt`, etc.).
   `channel_selection(channel="mt", era="2018", ...)` produces
   `id_tau_vsMu_Tight_VVLoose_2` (post-fix; was the nonexistent
   `id_tau_vsMu_Tight_2` pre-fix).
3. **Real embedded-sample yield, before/after the normalization fix** (RDataFrame,
   direct read of one real file,
   `TauEmbedding-MuTauFinalState_Run2018A-UL2018_0.root`, mt channel, full
   channel-selection cuts applied, 509,835 raw entries → 51,517 pass selection):
   - **Before fix** (old placeholder weight `(0.25)*(gen_match_1==4 &&
     gen_match_2==5)*(trg_wgt_single_mu24)`): weighted yield = **12,407.75**.
   - **After fix** (real weight `emb_genweight*emb_idsel_wgt_1*emb_idsel_wgt_2*
     emb_triggersel_wgt*(gen_match_1==4 && gen_match_2==5)*iso_wgt_mu_1*id_wgt_mu_1*
     trg_wgt_single_mu24ormu27`): weighted yield = **4,024.72**.
   - The ~3x difference confirms the fix materially changes embedded-background
     normalization (not a no-op), as expected for replacing a flat placeholder with
     real per-event generator/selection weights.
4. **tauES shift sanity check** (same file/selection, mean `pt_2` by shift point,
   confirming the `EMBtauESshift_<x>` branches behave as a genuine energy scale — i.e.
   scale linearly with shift fraction):

   | shift | mean pt_2 | expected (nominal × (1+shift)) |
   |---|---|---|
   | nominal | 39.5692 | — |
   | +2.4% | 40.5152 | 40.5169 |
   | −2.4% | 38.6196 | 38.6216 |
   | +8.0% | 42.7306 | 42.7347 |
   | −12.0% | 34.8209 | 34.8209 |

   Matches to <0.01% — strong confirmation the shift branches are read correctly and
   behave as a real multiplicative energy scale, not noise.
5. **End-to-end pipeline execution against live xrootd (real files, not mocked).**
   `shapes/produce_shapes.py --era 2018 --channels mt --vs-jet-wp Medium --vs-ele-wp
   VVLoose --xrootd --directory
   /store/user/jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNRun
   --process-selection emb --skip-systematic-variations --only-create-graphs` ran to
   completion: resolved the `EMB` dataset against the live production, built
   `MC_base`/`ZTT_embedded_process_selection`/`channel_selection` weight and cut
   strings referencing only real branches, produced 1 graph, and wrote
   `analysis_unit_graphs-2018-mt-emb.pkl` (210 KB) — i.e. the full booking pipeline
   (dataset discovery → weight/cut construction → graph build) works end-to-end for
   2018 embedding against the real production.
   - The equivalent `--special-analysis TauES` run (same process, same era/channel)
     was also launched and confirmed to correctly enter
     `shape_utils.add_tauES_datasets`, generate the corrected 100-point shift list,
     and validate the first shift point end-to-end against the live xrootd `EMB`
     dataset: `validation_database/default/2018_mt_embminus12p0.yaml` (not
     committed, generated cache) shows **zero differences / zero empty files**
     across every real file in all 4 `TauEmbedding-MuTauFinalState_Run2018[A-D]`
     run periods for shift point `embminus12p0` — i.e. the very first of the 100
     corrected shift points resolves and validates cleanly against real data.
     Each of the 100 shift points re-runs a full per-file validation pass
     (~2-3 min/point observed), so running all 100 was time-boxed rather than
     necessary — the per-shift branch-substitution logic itself was already
     validated directly and more cheaply (item 4 above) against the same real
     data it would consume.
   - The parallel `--collect-config-only` run across all 2018 mt processes (`data,
     ztt, zl, zj, ttt, ttl, ttj, vvt, vvl, vvj, w, emb`, `--no-dnn-categorization`
     since this validation production has no DNN friend trees) **completed**: it
     resolved and wrote booking config for all 6 dataset groups (`DY`, `TT`, `VV`,
     `W`, `data`, `EMB`), with real per-process resolved-file-path counts from the
     generated YAML: `DY` 81, `TT` 390, `VV` 137 (ST+diboson merged), `W` 12,
     `data` 236, `EMB` 81 — i.e. embedding resolves the same order of file
     coverage as the other backgrounds, not an empty/degenerate dataset. Output at
     `2018__mt__2018_mt_config2.yaml` (scratch path, not committed).
6. **Re-confirmed Run3/2024 unaffected.** `config.analysis.SUPPORTED_ERAS` still
   contains all 6 Run3 eras unchanged; `MC_base_process_selection`/`ZTT_embedded` for
   non-2018 eras take the unchanged `else` branch (verified by inspection — no
   Run3-era weight string changed except the now-conditional `btag_weight`, which
   was a latent bug for `mt`/`mm` fixed for all eras, not a Run3 behavior change for
   the channels that already worked).

### Not done / explicitly out of scope for this slice

- **et/tt/em channels for 2018**: no validation data exists for them in this
  production; `ZTT_embedded_process_selection`'s et/tt/em branches are untouched
  (still whatever they were before Phase 2a — mt was the only branch fixed and
  tested).
- **smhtt_ul's standalone tauID/tauES SF-fit pipeline**
  (`shapes/produce_shapes_tauid_es.py` on `tauID_SFs_dev`, ~1450 lines, with its own
  dedicated categorization/binning modules) was **not** ported wholesale. What *was*
  ported is the core, reusable mechanism it depends on for producing per-shift
  embedded templates (`add_tauES_datasets`/`book_tauES_histograms`, already present
  in this repo's `shapes/utils.py`, now wired up and range-corrected) plus a
  minimal categorization (`config/shapes/taues_measurement_binning.py`). Turning
  that into an actual SF fit (correctionlib output, plotting, iteration) is a
  separate, larger piece of work not attempted here.
- **2016/2017**: no validation data available; `config.analysis.RUN2_ERAS` is
  deliberately `("2018",)` only, not all of Run2.
- The full 100-point `--special-analysis TauES --collect-config-only` validation
  (item 5 above) was time-boxed after confirming the first shift point validates
  cleanly — re-running the rest is straightforward but not needed as evidence
  given item 4's direct per-shift branch check already confirms the mechanism
  end-to-end. The plain (non-TauES) `--collect-config-only` run across all 2018
  mt background/embedding processes, by contrast, did complete (see item 5,
  final bullet).

### Files changed / added

- `config/samples.yaml` — added `2018` luminosity + background/embedding sample
  lists (mt only).
- `config/analysis.py` — added `RUN2_ERAS`/`SUPPORTED_ERAS`, `EMB` dataset-key
  handling in `get_background_samples`.
- `config/shapes/process_selection.py` — 2018 trigger-weight branch, conditional
  `btag_weight`, real `ZTT_embedded_process_selection` weights.
- `config/shapes/channel_selection.py` — `SUPPORTED_ERAS` era guard, `_apply_wp_params`
  vsMu regex fix (both Run3 and 2018 TFF-YAML forms), `jet_vetomap` branch-name
  capitalization fix (Run3 and 2018 both).
- `config/shapes/tff_adapter.py` — `SUPPORTED_ERAS` era guard.
- `config/shapes/taues_measurement_binning.py` — new file, ported from smhtt_ul
  `tauID_SFs_dev`, mt-only, `tau_decaymode_2` branch-name fix.
- `shapes/produce_shapes.py` — `--special-analysis TauES` wiring
  (`add_tauES_datasets`/`book_tauES_histograms`, corrected shift range/step),
  `add_processes()` gained `"emb"` and per-key existence guards.
- `shapes/do_estimations.py` — corrected tauES shift range/step, wired the
  previously-dead `TauES` branch into the `do_emb_tt` embedded-ttbar-contamination
  loop.

## Phase 3 — Validation comparators

Status: **DONE.** Produced a real (non-synthetic) 2024/mt shape file against the live CROWN
production, re-ran Phase 2b's control-shape comparator against it, root-caused what turned out
to be a *much bigger* effect than the +3.9% TT-TTL discrepancy Phase 2b flagged (a 2x
luminosity discrepancy on the legacy reference file's own side — see below), and built a second
comparator (`combine_datacards/compare_datacards.py`) for the datacard/nuisance side, run against
a real Combine datacard built from that same shape file by both TauKITFlow's relocated
`make_datacards.py` and the actual legacy SMRun2Legacy `run3_htt` script.

### Pre-flight

Grid proxy: valid, ~169h remaining at session start (`voms-proxy-info`), sufficient for this
session's real xrootd runs. `taukiktflow` conda env used throughout for shape production;
CMSSW_15_0_2 (`utils/setup_cmssw.sh`) for the datacard side, as in Phase 2d — the two are never
mixed in one process, per the established house rule.

**Worktree submodule gap found and worked around (not a code bug):** this session runs inside a
git worktree (`.claude/worktrees/agent-...`); `git worktree` does not populate submodule content,
so `TauFakeFactors/` and `ntuple_processor/` were empty directories here even though they're
fully checked out in the main `/work/sgiappic/TauKITFlow` working copy. Every import
(`ntuple_processor.utils`, `CustomLogging`, and — the one that actually blocked a real run —
`config/shapes/tff_adapter.py`'s TFF preselection-YAML lookup, which needs the real
`TauFakeFactors/configs/smhtt_ul/2024/preselection_mt.yaml`) failed until these two directories
were symlinked to the main repo's populated checkouts for the duration of this session's runs,
then **restored to empty directories before committing** (confirmed via `git status --short`
that only this session's real Phase 3 files are staged — no submodule-pointer changes). Whoever
next works in a fresh worktree will hit the same thing; not a Phase 3 code change, just a
documented one-time environment fix.

### Goal 1: real 2024/mt shape production + control-shape comparison

Ran `shapes/produce_shapes.py --era 2024 --channels mt --vs-jet-wp Medium --vs-ele-wp VVLoose
--apply-tauid --control-plots --control-plot-set <57 vars> --xrootd --directory
/store/user/sgiappic/CROWN/ntuples/htt_260602_2024-25_v5/CROWNRun --mt-friend-directory
.../CROWNFriends/xsec/ --skip-systematic-variations --no-dnn-categorization --num-processes 12
--num-threads 8` against the live 2024 CROWN production, followed by
`shapes/do_estimations.py --era 2024 --do-qcd`. **Completed successfully (rc=0)**, producing a
real 1.70 MB shape ROOT file with 16 processes (`data`, `DY-ZTT/ZL/ZJ`, `TT-TTT/TTL/TTJ`,
`VV-VVT/VVL/VVJ`, `W`, `QCDMC`, `ggH125`, `qqH125`, `ttH125`, `VH125`) x 57 variables. (The full
`control_plots_ul.sh` `DEFAULT_VARIABLES_LIST` has 59 variables; TauKITFlow's
`config/shapes/control_binning.py` for `mt` doesn't define `puppimet`/`puppimetphi` — it uses
`met`/`metphi` instead — so those 2 were dropped from the request rather than silently failing;
reported as "missing from --new-file" by the comparator, not a bug.)

**Comparator run:** `plotting/compare_control_shapes.py --new-file <new 2024/mt shapes>
--legacy-file /work/sgiappic/smhtt_ul/output/2024-mt-htt_260602_2024-25_v5-260602/
control_shapes-2024-mt-htt_260602_2024-25_v5-260602.root --channel mt --selection Nominal
--max-n-sigma 3.0` (this is the real `control_plots_ul.sh -m SHAPES` output for 2024/mt, produced
Jun 8 2026 against the live 2024 CROWN production — not synthetic).

- **Raw result: 109/912 histograms pass within 3σ. Achieved max n_sigma=489.140, max
  rel_diff=181.24% across 912 histograms; 32 histograms (2 missing variables x 16 processes,
  exactly `puppimet`/`puppimetphi`) reported missing from the new file, as expected from the
  variable-name difference above.**
- **Root cause of the low raw pass rate — NOT the same bug as Phase 2b's TT-TTL finding, and NOT
  a TauKITFlow bug: every single MC/simulated process (all 15 non-`data` processes) integrates to
  almost exactly 50.1-50.3% of the legacy value; `data` (which carries no luminosity weight)
  matches bit-for-bit** (`data#mt#Nominal#m_vis`: new=legacy=1,473,179.000 exactly). A uniform
  ~2x factor across every MC process but not data is the signature of a luminosity-weight
  difference, not a physics/selection difference. Confirmed directly:
  `config.analysis.get_luminosity("2024")` (TauKITFlow, central config, unchanged since Phase 1)
  returns **109.816** fb⁻¹, while `/work/sgiappic/smhtt_ul/config/shapes/process_selection.py`'s
  own `lumi_weight()` — in its **current, live** checkout — hardcodes
  `lumi = "218.9" #lumi = "109.81"` for era `"2024"` (and, matching pattern,
  `lumi = "219.78" #lumi = "109.89"` for `"2025"`) — i.e. **smhtt_ul's own live reference
  checkout currently uses almost exactly double the correct 2024 luminosity, with the correct
  value left commented out immediately alongside it.** `git log --follow -p` on that file shows
  this doubling (`219.7"/"219.7" -> "218.9"`, `2025` similarly) was introduced in a
  `875b545`/`e3eed54`-range "updates" commit on **2026-06-02**, and the legacy reference shape
  file used for this comparison (`control_shapes-2024-mt-...-260602.root`) has an mtime of
  **2026-06-08 16:10** — i.e. it was produced *after* that doubling landed, so the bug is baked
  into the specific legacy reference file being compared against, not a stale artifact from
  before it. Phase 1's original lumi-weight validation (byte-identical `"109.816 * 1000.0"`
  before/after centralisation) was correct at the time and remains correct — it was checked
  against an *earlier* version of smhtt_ul's own file, before this doubling was introduced there
  independently of this rework. **This is a real, dated, git-log-confirmed bug in the live
  smhtt_ul reference checkout, not in TauKITFlow.**
- **Residual agreement after manually correcting for the confirmed 2x legacy-side factor**
  (`new_integral * (218.9/109.816)` vs `legacy_integral`, spot-checked on `m_vis` for every
  process): DY-ZTT 0.9998, DY-ZL 0.9999, DY-ZJ 0.9964, W 0.9995, VV-VVT 1.0013, VV-VVL 1.0012,
  ggH 0.9996, qqH 0.9998, VH 0.9962, ttH 1.0025 — **all within ~0.4%**. Two processes show a
  larger residual worth flagging for whoever next chases process-level discrepancies (out of
  scope to resolve further in this time-boxed slice): **TT-TTT 0.9834 (1.66% low) and TT-TTL
  0.9837 (1.63% low)** (same direction and similar magnitude to each other, opposite sign and
  substantially smaller magnitude than Phase 2b's +3.9% TT-TTL finding on 2022preEE — this is a
  different era/production, so it is *not* a re-observation of the same effect, but the fact that
  TT specifically shows the only non-negligible non-lumi residual in both eras is worth someone's
  attention), and **VV-VVJ 0.7338 (26.6% low)**, a low-statistics process where a single MC
  sample's presence/absence would swing the ratio this much — not chased further here (would need
  a per-sample dataset diff against the legacy TT/VV sample lists, next slice's job if pursued).
- **Conclusion for the Phase 2b-flagged TT-TTL discrepancy specifically:** not literally
  reproduced or refuted — Phase 2b's comparison was 2022preEE, this one is 2024, a different
  era/production entirely, so it isn't the same measurement re-run. What this slice does show is
  that at 2024/mt, once the (real, independently-confirmed) legacy-side lumi bug is accounted
  for, TT-TTT/TTL sit at a much smaller ~1.6% residual, same direction — consistent with *some*
  small, real, TT-specific difference existing at multiple eras, but far too small to have been
  the dominant discrepancy at either era once lumi is controlled for.

### Goal 2: datacard-level comparison against a real (non-synthetic) shape file

**`shapes/convert_to_synced_shapes.py` relocated into TauKITFlow** (new file,
`shapes/convert_to_synced_shapes.py`) — this is the flat-histogram-key -> `$BIN/$PROCESS`
TDirectory converter that bridges `produce_shapes.py`'s control/gof output to the input format
`combine_datacards/make_datacards.py`'s `ExtractShapes(...)` calls expect. **This corrects Phase
2d's "## Blockers" #2** ("`convert_to_synced_shapes.py` referenced but never found" — Phase 2d's
filesystem search missed it): it exists at
`/work/sgiappic/smhtt_ul/shapes/convert_to_synced_shapes.py` and is pure ROOT + stdlib, no
external deps, so it's copied here verbatim with a docstring explaining the correction and
pointing at its real source. Blocker #2 in "## Blockers" below is updated to RESOLVED.

Pipeline run, using the `gof` categorization path (fully functional per Phase 2d; the DNN
`stxs_stage0_run3` path remains blocked on Blockers #3, unrelated to this slice):

1. `python shapes/convert_to_synced_shapes.py -e 2024 -i <2024/mt shapes from Goal 1> -o
   <syncdir> --gof --mc --variable-selection m_vis -n 4` — converted the real 2024/mt shape file
   (Goal 1's output, not synthetic) into a `mt_m_vis/{ZTT,ZL,ZJ,TTT,TTL,TTJ,VVT,VVL,VVJ,W,
   ggH_htt125,qqH_htt125,ttH_htt125,VH_htt125,data_obs}` TDirectory structure. Confirmed by
   listing the output file's keys directly.
2. Ran **both** `combine_datacards/make_datacards.py` (TauKITFlow, this repo) and the actual
   legacy `${CMSSW_BASE}/src/CombineHarvester/SMRun2Legacy/scripts/make_datacards.py` (`run3_htt`
   branch — the real relocation source, not a reimplementation) against the **identical** synced
   input file, with matching arguments (`--era 2024 --channels mt --categories gof
   --gof-category-name mt_m_vis --stxs-signals stxs_stage0 --real-data False --embedding False
   --jetfakes False --bbb True --systematics True --rebinning-strategy none`; legacy's CLI lacks
   `--ggh-wg1`/`--qqh-wg1`/`--convert-shapes-to-lnN`, TauKITFlow-only additions, so those were
   only passed on the new side, set to `False` to match legacy's absence of that knob as closely
   as CLI compatibility allows). Both produced a real `htt_mt_m_vis_2024.txt` datacard +
   `common/htt_input_2024.root` shape file, combined via `combineCards.py` (the genuine external
   Combine binary), with **zero errors on either side.**
3. **`combine_datacards/compare_datacards.py`** — new file, a minimal Combine-datacard text
   parser (rate block + nuisance rows) plus a yield/nuisance-set comparator, the datacard-level
   counterpart to `compare_control_shapes.py`. Compares every `(bin, process)` rate
   (`rel_diff = |new-legacy| / max(|new|,|legacy|,eps)`) and reports the shared/new-only/
   legacy-only nuisance-name sets (a nuisance-set difference is *expected* here, per Phase 2d's
   deliberate systematics-naming reconciliation, so it's reported not failed by default;
   `--strict-nuisances` opts into failing on any set difference).
   - **Result: 12/12 (bin, process) yields agree at rel_diff = 0.000e+00 (bit-identical)** —
     `ZTT`, `ZL`, `ZJ`, `TTT`, `TTL`, `TTJ`, `VVT`, `VVL`, `VVJ`, `W`, `ggH_htt`, `qqH_htt` all
     match exactly, as does the `data_obs` observation (700,415.6928 both sides). This is the
     expected result for two codebases fed the identical synced input file and confirms the
     relocation (Phase 2d) preserved yield-construction logic exactly, now checked against a real
     shape file rather than the hand-built synthetic one Phase 2d used.
   - **Nuisances: 13 total on the new side, 11 shared with legacy, 2 new-only
     (`QCDScale_ggH`, `QCDScale_qqH`), 0 legacy-only.** All 13 are `lnN` — no `shape`-type
     nuisance survived on either side, which is correct and expected: this shape file was
     produced with `--skip-systematic-variations` (Goal 1), so no Up/Down-shifted histograms
     exist for any systematic to attach to, and `filter_zero_yield_systs`/
     `load_systematic_shapes` (ported unchanged from SMRun2Legacy, see Phase 2d) correctly and
     silently dropped every shape-type systematic on both sides. The 2 new-only nuisances trace
     directly to a CLI-surface difference, not a real physics difference: legacy's `run3_htt`
     `make_datacards.py` has no `--ggh-wg1`/`--qqh-wg1` flags at all (TauKITFlow-only additions),
     so it always runs its own unconditional default for ggH/qqH theory-scale naming, which
     happens not to include `QCDScale_ggH`/`QCDScale_qqH` under its naming scheme — not a
     reconciliation gap, just a consequence of the two CLIs not being fully arg-compatible for
     that one knob.
4. **Separately, to characterise the *code-level* systematics-naming reconciliation (Phase 2d)
   in full, independent of which shapes happen to exist in one particular ROOT file:** built an
   identical mt/2024/`gof` `CombineHarvester` skeleton (same categories/backgrounds/signals) and
   called `add_systematics()` directly from both codebases (`combine_datacards/systematics.py`
   vs. legacy `CombineHarvester.SMRun2Legacy.systematics`), dumping the full nuisance-name set
   each produces *before* any shape-file filtering. **TauKITFlow: 97 nuisances. Legacy: 92
   nuisances. 47 shared, 50 TauKITFlow-only, 45 legacy-only.** The 47 shared are exactly the
   administrative/theory lnN priors with no shape counterpart (`BR_htt_*`, `LHE_*`, `PS_scale_*`,
   `QCDScale_ggH/qqH`, `ggH_scale_*`/`qqh_scale_*` theory-scale bins, `CMS_htt_*Xsec`, `CMS_PileUp`,
   `CMS_prefiring`, `lumi_13.6TeV_*`, `CMS_eff_m`, `CMS_scale_j_FlavorQCD`/`RelativeBal`). The
   non-shared 95 names are exactly the reconciliation Phase 2d documented, confirmed here with an
   actual diff rather than just a code-reading claim:
     - **JEC**: TauKITFlow's full 27-source split (`CMS_scale_j_AbsoluteMPFBias`,
       `..._RelativeJEREC1/2/HF`, `..._SinglePionECAL/HCAL`, etc., 25 TKF-only names) vs. legacy's
       regional grouping (`CMS_scale_j_Absolute[_Run2024]`, `_BBEC1[_Run2024]`, `_EC2[_Run2024]`,
       `_HF[_Run2024]`, `_RelativeSample_Run2024`, `CMS_res_j_Run2024` — 10 legacy-only names).
     - **Tau-ID efficiency (lt channels)**: TauKITFlow's pT-bin split (`CMS_eff_t_30-35_2024`
       ... `CMS_eff_t_1000-Inf_2024`, 5 names) vs. legacy's decay-mode x pT split
       (`CMS_eff_t_1prong0pizero_20to40_Run2024` ... `_3prong1pizero_40toInf_Run2024`, 8 names).
     - **Tau ES**: TauKITFlow's 4 coarse DM groups (`CMS_scale_t_1prong[1pizero]_2024`,
       `_3prong[1pizero]_2024`) vs. legacy's DM x pT split (8 names, same pattern as tau-ID).
     - **b-tagging**: TauKITFlow's `btagging_2024` 9-source scheme (`CMS_btag_2024`,
       `_fsr/_hdamp/_isr/_jer/_jes/_mass/_stat/_tune_2024`) vs. legacy's 8-source scheme
       (`CMS_btag_b_HF`, `_b_HFstats1/2_Run2024`, `_c_CFerr1/2`, `_j_LF`, `_j_LFstats1/2_Run2024`)
       — as Phase 2d noted, neither scheme is actually wired into real shape production yet
       (`shapes/produce_shapes.py` books no b-tag systematic histograms on either side), so this
       is a pure naming-convention difference with zero yield impact today on either side.
     - **Era-string convention**: every name containing an era literal differs only in format —
       TauKITFlow emits bare `_2024` (`config/shapes/variations.py`'s literal, resolved by
       `combine_datacards/systematics.py`'s `_resolve()`), legacy emits `_Run2024` (its own
       `$ERA`-substitution convention) — cosmetic, not a scheme difference, but explains why e.g.
       `CMS_ZLShape_mt_2024` (TKF) and `CMS_ZLShape_mt_Run2024` (legacy) don't dedupe as "shared"
       even though they're the same systematic.
   None of this is new information relative to Phase 2d's documented reconciliation reasoning —
   what's new here is the actual number (97 vs 92, 47 shared) instead of a code-reading claim.

### Files changed / added

- `shapes/convert_to_synced_shapes.py` — new (relocated from
  `/work/sgiappic/smhtt_ul/shapes/convert_to_synced_shapes.py`, verbatim + a docstring correcting
  Phase 2d's Blocker #2). Bridges `produce_shapes.py` output to
  `combine_datacards/make_datacards.py`'s expected `$BIN/$PROCESS` input format.
- `combine_datacards/compare_datacards.py` — new. Datacard-level yield/nuisance-set comparator,
  the Combine-datacard counterpart to `plotting/compare_control_shapes.py`.
- `.gitignore` — added `convert_to_synced_shapes.log` (the relocated script hardcodes this
  relative log path, same treatment as the existing `routine_output.log` entry).

### Not done / explicitly out of scope for this slice

- **VV-VVJ's 26.6% residual and TT-TTT/TTL's ~1.6% residual** (Goal 1, after lumi correction) —
  flagged with real numbers above, not chased to a root cause. Would need a per-sample dataset
  listing diff between TauKITFlow's and smhtt_ul's current TT/VV sample lists for 2024, which is
  a distinct investigation from what this slice's time-box covered.
- **DNN (`stxs_stage0_run3`) categorization datacard comparison** — still blocked on Blockers
  #3 (`DNN_CLASS_MAPPING`) exactly as in Phase 2d; this slice's datacard comparison used `gof`
  instead, which is unaffected by that gap and was explicitly Phase 2d's own validated path.
  `--embedding True`/`--jetfakes True` datacard variants (which would exercise the
  reconciled embedding/jetFakes-specific systematics in `combine_datacards/systematics.py`) were
  also not run — the real 2024/mt shape file produced in this slice used
  `--process-selection` defaults that don't include `emb`, so an embedding-based datacard would
  need a separate shape-production run; out of scope for this time-boxed slice given the `gof`
  path already gives a clean, real, non-synthetic yield+nuisance comparison.
- **Systematic-variation shapes** (Goal 1's shape production used
  `--skip-systematic-variations`, matching `control_plots_ul.sh -m SHAPES`'s own flag) — so the
  datacard comparison in Goal 2 has no `shape`-type nuisances to compare on either side (both
  correctly show zero, as documented above). A full systematic-variations run (dropping that
  flag) would be needed to compare actual shape-uncertainty templates bin-by-bin; that's a
  materially longer production (every JES/tau-ES/tau-ID variation booked and filled) left for a
  future slice if pursued.

## Phase 4 — GoF/impacts

Status: **DONE.** Stood up and ran, for real, the standard CMS Combine
GoodnessOfFit + Impacts workflow end-to-end against a real (non-synthetic)
2024/mt `gof` datacard/workspace built from a fresh real shape production
(the Phase 3 shape file itself no longer existed on disk — it was never
committed, being large generated output — so this slice reproduced it).
Real numbers below, not just "ran successfully."

### Scope decided for this slice

Per the task framing ("define this phase's scope yourself"), scoped to:
- One real GoF test (`gof` category, 2024/mt, `m_vis` discriminant — the
  validated Phase 2d/3 path; the DNN `stxs_stage0_run3` path stays out per
  Blocker #3, unrelated to this phase).
- One real Impacts run against the same workspace.
- New CLI layer (`datacards/run_gof.sh`, `datacards/run_impacts.sh`) wired on
  top of the pre-existing `produce_gof_datacard.sh`/`produce_gof_workspace.sh`,
  which needed real fixes (below) — they had never actually been run against
  a real synced shape file before this slice, only against Phase 2d's
  hand-built synthetic one.
- Condor submission for GoF/Impacts: **deliberately not built.** The real run
  below took under 5 minutes wall-clock total for both GoF (300 toys) and
  Impacts (42 nuisances) on a single 2024/mt/`gof`/`m_vis` card — nowhere near
  the "slow, grid-shaped" case the task anticipated. A full production config
  (all discriminant variables, real systematic-variation shapes once produced,
  every channel/era) would plausibly justify condor fan-out the same way
  `condor/submit_shapes.py` etc. do (Phase 2c) — noted here as a natural
  follow-up, not attempted speculatively.

### What was found: `produce_gof_datacard.sh`/`produce_gof_workspace.sh` had never actually been run for real

Both existed since Phase 2d/rewiring but were validated there only against a
**hand-built synthetic shape file** (Phase 2d's own note: "no real physics
content"). Running them for real in this slice surfaced three real bugs, none
previously visible because nothing had exercised these two scripts against a
real synced shape file or under CMSSW's own Python before now:

1. **`produce_gof_datacard.sh`'s `--gof-category-name` was wired to a bare
   `"gof"`/`$TAG` value that never matches a real synced file.**
   `shapes/convert_to_synced_shapes.py --gof` writes a TDirectory named
   `"{channel}_{variable}"` (e.g. `mt_m_vis`) — confirmed directly by listing
   the real synced file's keys (see below) — and
   `combine_datacards/make_datacards.py`'s `ExtractShapes("$BIN/$PROCESS")`
   needs `--gof-category-name` to equal that exact directory name to find any
   histograms at all. Fixed: `produce_gof_datacard.sh` now derives
   `GOF_CATEGORY_NAME="${CHANNEL}_${VARIABLE}"` itself instead of taking an
   opaque `TAG` argument.
2. **`produce_gof_workspace.sh` built a `multiSignalModel` (`r_ggH`/`r_qqH`)
   workspace**, which is wrong for both downstream steps: `combine -M
   GoodnessOfFit --fixedSignalStrength=0` and single-POI `combineTool.py -M
   Impacts` both expect (or work far more simply with) Combine's *default*
   single-`r` physics model. Fixed: rewritten to call plain
   `text2workspace.py <card> -m 125 -o ws.root` (no `-P
   multiSignalModel`/`--PO` maps) — the standard choice for a one-bin `gof`
   category where there's no ggH/qqH separation to preserve anyway.
3. **`config/logging_setup_configs.py`'s `CustomLogging` import
   (`from CustomLogging import ...`) is only satisfiable with
   `TauFakeFactors/` on `PYTHONPATH`** — true for the `taukiktflow` conda env
   (already fixed by `run.sh`'s `PYTHONPATH=...:${PWD}/TauFakeFactors`) but
   this had never been fixed for the **CMSSW-side** scripts
   (`produce_datacard.sh`/`produce_gof_datacard.sh`), which import
   `combine_datacards/make_datacards.py` → `config.logging_setup_configs` →
   `CustomLogging` under CMSSW's own Python. Both scripts crashed with
   `ModuleNotFoundError: No module named 'CustomLogging'` the first time they
   were actually run in this slice. Fixed both `export PYTHONPATH=` lines to
   include `$(pwd)/TauFakeFactors`.

### Real environment bug found and fixed: `utils/setup_cmssw.sh` numpy/pandas ABI clash

`text2workspace.py` (imports `HiggsAnalysis.CombinedLimit.ShapeTools` →
`pandas`) crashed under a freshly-sourced `utils/setup_cmssw.sh` with:
```
ValueError: numpy.dtype size changed, may indicate binary incompatibility.
Expected 96 from C header, got 88 from PyObject
```
Root-caused directly: `python3 -c "import numpy; print(numpy.__file__)"`
under `cmsenv` resolved to `~/.local/lib/python3.9/site-packages/numpy`
(numpy 2.0.2, a user-site install) instead of CVMFS's bundled numpy 1.24.3 —
Python's user-site directory is on `sys.path` by default even inside
`cmsenv`, and CVMFS's `py3-pandas` is a compiled extension built against the
bundled numpy's ABI, so importing the wrong numpy first breaks pandas'
compiled `_libs` at import time. Confirmed the fix directly:
`PYTHONNOUSERSITE=1` excludes the user site-packages directory for the shell,
after which `import pandas` and `text2workspace.py --help` both succeed under
`cmsenv`. Added `export PYTHONNOUSERSITE=1` to `utils/setup_cmssw.sh` itself
(not just this session's shell) so every future CMSSW-side script sourcing it
gets the fix automatically — this was a latent bug in the existing setup
script that any script importing `pandas`-dependent Combine machinery
(`text2workspace.py`, `FitDiagnostics`, ...) would have hit, not something
specific to GoF/Impacts.

### New files

- **`datacards/run_gof.sh`** — orchestrates the full GoF workflow: places a
  synced shape file at the path `make_datacards.py` expects, calls
  `produce_gof_datacard.sh` + `produce_gof_workspace.sh`, runs `combine -M
  GoodnessOfFit` once on real data (observed statistic) and again `N_TOYS`
  times split across `PARALLEL` seeds (b-only, `--fixedSignalStrength=0`,
  matching `smhtt_ul/gof_tests.sh`'s GOF mode), collects via
  `combineTool.py -M CollectGoodnessOfFit`, and prints the observed statistic
  + toy-based p-value (own small Python snippet, no dependency added).
  Supports `saturated`/`KS`/`AD` algorithms (`plotGof.py` invoked for the
  latter two, matching legacy).
- **`datacards/run_impacts.sh`** — the standard `combineTool.py -M Impacts`
  pipeline (`--doInitialFit` → `--doFits` per-nuisance, both `--parallel` →
  `-o impacts.json` → `plotImpacts.py`), adapted from
  `smhtt_ul/fitting/impacts.sh`/`gof_tests.sh`'s IMPACTS mode to TauKITFlow's
  default single-`r` workspace (no `--redefineSignalPOIs` juggling needed —
  exactly one POI). Prints its own top-15 nuisance-impact ranking table
  (parses `impacts.json` directly, no new dependency).

### Real validation run

Environment: `taukiktflow` conda env for shape production (with
`TauFakeFactors`/`ntuple_processor` symlinked into this worktree from the main
checkout for the session's duration, then restored to empty dirs before
committing — the same one-time worktree-submodule-gap workaround Phase 3
documented, not a new issue). `utils/setup_cmssw.sh`
(CMSSW_15_0_2/`el9_amd64_gcc12`) for the Combine side, in a separate shell
session, per house rule. Grid proxy: valid, **150h remaining** at the time of
the real xrootd shape-production run (`voms-proxy-info`).

1. **Real shape reproduction (2024/mt, `gof`, `m_vis` only).**
   `shapes/produce_shapes.py --era 2024 --channels mt --vs-jet-wp Medium
   --vs-ele-wp VVLoose --apply-tauid --gof-inputs --control-plot-set m_vis
   --xrootd --directory
   /store/user/sgiappic/CROWN/ntuples/htt_260602_2024-25_v5/CROWNRun
   --mt-friend-directory .../CROWNFriends/xsec/ --skip-systematic-variations
   --no-dnn-categorization --num-processes 12 --num-threads 8` ran to
   completion against the live 2024 CROWN production, followed by
   `shapes/do_estimations.py -e 2024 --do-qcd` and
   `shapes/convert_to_synced_shapes.py -e 2024 --gof -n 4`.
   - **Bug found in the process (own driver script, not repo code):**
     `--control-plot-set` is `nargs="+"` (space-separated), not
     comma-separated — passing `"pt_1,pt_2,m_vis,..."` as one token made
     `get_control_units` raise `Exception: Variable pt_1,pt_2,...,pt_vis not
     available in control_binning` since the whole comma-joined string was
     treated as a single (nonexistent) variable name. Not a repo bug; just a
     footgun in this slice's own shell invocation, fixed by switching to a
     single `m_vis` argument (sufficient for this validation; nothing stops
     a real production run from passing multiple space-separated variables).
   - Real synced output: `2024-mt-synced-m_vis.root`, one TDirectory
     `mt_m_vis`, **14 real histograms**: `ZTT, ZL, ZJ, TTT, TTL, TTJ, VVT, VVL,
     VVJ, W, ggH_htt125, qqH_htt125, ttH_htt125, VH125` + `data_obs`.
     `data_obs` integral **1,473,179.0** — bit-identical to Phase 3's real
     2024/mt `data#mt#Nominal#m_vis` observation, confirming this reproduction
     drew from the same real data as Phase 3 (same live production, same
     selection).
2. **Real datacard + workspace.** `datacards/run_gof.sh 2024 mt m_vis
   <synced file> saturated 300 htt_260602_2024-25_v5 0 10` built
   `htt_mt_m_vis_2024.txt` (1 bin, real-data observation, `embedding=false
   jetfakes=false` — same MC-only closure model Phase 3 bit-identically
   validated) + `common/htt_input_2024.root`, combined via `combineCards.py`,
   then `text2workspace.py` → `ws.root` (default single-`r` model,
   **31 analysis bins**, `SetAutoMCStats` applied — confirmed via the
   `combine` startup log listing all 31 `prop_binhtt_mt_m_vis_2024_bin*`
   Gaussian-constrained nuisances).
3. **Real GoF result (saturated test statistic, real data):**
   - **Observed test statistic: 1816.9417** (`combine -M GoodnessOfFit
     --algo=saturated --fixedSignalStrength=0`, real `data_obs`).
   - **300 toys thrown** (10 parallel seeds x 30 toys/seed, `--toysFreq`,
     b-only `--fixedSignalStrength=0`), collected via `combineTool.py -M
     CollectGoodnessOfFit` into `gof_saturated.json`.
   - **p-value = 0.0000** (0/300 toys >= observed). Read honestly, not
     glossed over: this reflects the *reduced* background model used here
     (MC-only, no embedding/jetFakes, `--skip-systematic-variations` shape
     production per Phase 3's Goal 1 choice) — with essentially zero shape
     freedom beyond `autoMCStats` and a handful of administrative `lnN`
     priors, the model has no mechanism to absorb real data's statistical
     fluctuations across 31 bins, so a very poor saturated-GoF p-value is the
     *expected* outcome of this reduced setup, not a sign the GoF machinery is
     broken — the pipeline itself (real data, real toys, real p-value
     arithmetic) is what this phase was scoped to validate, and it did.
     Getting a physically meaningful p-value would need the full
     embedding+jetFakes+shape-systematics production Phase 3 explicitly
     scoped out (see its "Not done" list) — a natural next step, not
     re-attempted here.
   - Total wall-clock for datacard+workspace+GoF (observed + 300 toys):
     **~26 seconds** (`09:55:01` datacard start → `09:55:26` `gof_saturated.json`
     written) — confirms this scale of GoF run is nowhere near
     condor-shaped, per the scope note above.
4. **Real Impacts result (same workspace):**
   - **`--doInitialFit`: best-fit r = 2.993 (-1.850/+1.828, 68% CL)**
     (`combineTool.py -M Impacts --doInitialFit --robustFit 1`, 7.3s).
   - **`--doFits`: 42 nuisance parameters fit** (1 POI `r` + 41 others: 31
     `autoMCStats` bin nuisances + 10 administrative `lnN`-derived
     parameters — `BR_htt_THU`, `BR_htt_PU_alphas`, `BR_htt_PU_mq`,
     `CMS_eff_m`, `CMS_eff_t_wp_Run2024`, `CMS_htt_tjXsec`, `CMS_htt_vvXsec`,
     `CMS_htt_wjXsec`, `CMS_htt_zjXsec`, `lumi_13.6TeV_Run2024`,
     `lumi_13.6TeV_correlated`), all fit successfully in parallel
     (`--parallel 10`, 20.2s wall-clock for all 42 fits — confirms
     `combineTool.py`'s own multiprocessing parallelism, not a new mechanism
     built here).
   - **`impacts_2024_mt_m_vis.json` + `impacts_2024_mt_m_vis.pdf`** produced
     by `plotImpacts.py` (a real ranked tornado plot, 2 pages/30+12
     parameters split, matplotlib/ROOT rendering succeeded with only expected
     "pull could not be computed" warnings for a handful of `lnN`-only
     nuisances with no external constraint term to plot a pull against —
     standard Combine behavior, not an error).
   - **Top-5 ranked nuisances by |impact on r|:**

     | rank | impact | nuisance |
     |---|---|---|
     | 1 | 1.5709 | `prop_binhtt_mt_m_vis_2024_bin10` |
     | 2 | 1.3202 | `prop_binhtt_mt_m_vis_2024_bin11` |
     | 3 | 1.1442 | `prop_binhtt_mt_m_vis_2024_bin12` |
     | 4 | 1.1386 | `prop_binhtt_mt_m_vis_2024_bin9` |
     | 5 | 0.9147 | `prop_binhtt_mt_m_vis_2024_bin6` |

     All top-ranked nuisances are `autoMCStats` bin-by-bin statistical
     uncertainties, not any physics systematic — consistent with (not an
     artifact of) this shape file having zero shape-type systematics
     (`--skip-systematic-variations`, same as Goal 1's Phase 3 production):
     with no JES/tau-ID/tau-ES templates to rank, bin-by-bin MC statistics are
     mechanically the largest-impact nuisances left. A production run with
     real systematic-variation shapes (Phase 3's explicitly-deferred "Not
     done" item) would be needed to get a physics-meaningful impact ranking
     dominated by named systematics instead.
   - Total wall-clock, both Impacts steps: **~28 seconds**
     (7.3s + 20.2s, collect+plot negligible).

### Files changed / added

- `datacards/run_gof.sh` — new. Orchestrates synced-file placement → datacard
  → workspace → observed GoF → toys → collect → p-value.
- `datacards/run_impacts.sh` — new. Orchestrates the standard `-M Impacts`
  `doInitialFit`/`doFits`/collect/`plotImpacts.py` pipeline + a ranked
  nuisance-impact summary table.
- `datacards/produce_gof_datacard.sh` — fixed `--gof-category-name` to derive
  `"${CHANNEL}_${VARIABLE}"` (matching `convert_to_synced_shapes.py --gof`'s
  real TDirectory naming) instead of a bare tag that never matched any real
  synced file; added `TauFakeFactors` to `PYTHONPATH`; added
  `--embedding`/`--jetfakes` passthrough args (default off, matching the
  MC-only model Phase 3 validated).
- `datacards/produce_gof_workspace.sh` — switched from a `multiSignalModel`
  (`r_ggH`/`r_qqH`) workspace to Combine's default single-`r` model via plain
  `text2workspace.py`, required for `--fixedSignalStrength=0` (GoF) and
  single-POI Impacts.
- `datacards/produce_datacard.sh` — added `TauFakeFactors` to `PYTHONPATH`
  (same latent CustomLogging-import gap as `produce_gof_datacard.sh`, fixed
  for consistency even though this slice's real run only exercised the GoF
  script).
- `utils/setup_cmssw.sh` — added `export PYTHONNOUSERSITE=1` (real
  numpy/pandas ABI-mismatch fix, see above).

### Not done / explicitly out of scope for this slice

- **Condor submission for GoF/Impacts** — deliberately not built; see scope
  note above (real run was seconds, not condor-shaped at this scale).
- **A physically meaningful GoF p-value / impact ranking** — needs a shape
  production run with real systematic-variation templates and the full
  embedding+jetFakes background model, both explicitly out of Phase 3's scope
  too. This phase validated that the GoF/Impacts *machinery* runs correctly
  end-to-end against real data and produces real, correctly-computed
  statistics — not that today's reduced shape production yields a
  publication-grade result (it doesn't, and isn't expected to).
- **DNN (`stxs_stage0_run3`) GoF/Impacts** — still blocked on Blocker #3
  (`DNN_CLASS_MAPPING`), same as every prior phase's datacard work.
- **KS/AD GoF algorithms** — `run_gof.sh` supports them (mirrors
  `smhtt_ul/gof_tests.sh`'s per-algorithm loop) but only `saturated` was run
  for real in this slice; `--toysFreq` is only applied for `saturated` per
  the legacy script's own convention, `--plots` for the other two.
- **Multiple discriminant variables / channels / eras in one pass** — this
  slice validated the mechanism on one (era, channel, variable) combination,
  matching Phase 3's own single-combination validation depth; nothing in
  `run_gof.sh`/`run_impacts.sh` is hardcoded to `m_vis`/`mt`/`2024` specifically.

## Phase 4b — Close the `stxs_stage0_run3` (Run3 DNN) `DNN_CLASS_MAPPING` gap (Blocker #3)

Status: **DONE at the config + datacard-construction level.** The
`NotImplementedError` that `combine_datacards/categories.py`'s `stxs_stage0_run3`
path raised is gone; `make_datacards.py --categories stxs_stage0_run3` now
builds a real, valid 7-category Combine datacard end-to-end (validated below).
The remaining piece — real DNN-scored *physics content* — is a genuinely larger,
separate gap (no DNN-score friend trees exist yet); see "honest boundary" below.
Blocker #3 is updated to **PARTIALLY RESOLVED** accordingly.

### Where the `is_signal` ground truth came from

smhtt_ul is checked out on branch **`77af7d0` ("nn, combine")** — ahead of what
earlier phases looked at — and its `config/shapes/category_selection.py` now
contains a real, current `DNN_CLASS_MAPPING` (the single source of truth
consumed by *its own* `produce_shapes.py`/`plot_shapes_control.py`). In it, the
two Higgs production-mode classes are the only signal classes:
- `ggh` (index 0) → `is_signal: True`
- `vbf` (index 1) → `is_signal: True`
- `dyjets_tt` (DY→ττ), `dyjets_ll` (DY→ll), `jetFakes`, `ttbar`, `diboson` →
  all `is_signal: False` (background / control regions).

It also defines `et` (same 7-class scheme as its `mt`) and `tt` (a 5-class
scheme: `ggh`/`vbf`/`dyjets_tt`/`jetFakes`/`bkg_rest`) — but under **smhtt_ul's
own class names**, which do **not** match TauKITFlow's existing
`category_mapping` names (`ggh`/`qqh`/`ztt`/`ff`/`zll`/`tt`/`misc`, mt only).

### What was built, and the reconciliation decision

`config/shapes/category_selection.py` now defines **`DNN_CLASS_MAPPING`** in the
exact shape `combine_datacards/categories.py` expects
(`{channel: {name: {"index": int, "is_signal": bool}}}`). Two decisions,
mirroring Phase 2d's "follow TauKITFlow's naming where it's correct, pull the
*semantics* from legacy" rule:
1. **Single-sourced off the existing `category_mapping`** (a dict comprehension,
   no names/indices duplicated). TauKITFlow's own `mt` class names + DNN
   output-class indices are kept verbatim (they are what TauKITFlow's DNN
   categorization branch `mt_max_index` actually selects on); only the new
   `is_signal` field is added, via a `SIGNAL_CLASSES = {"ggh", "qqh"}` set
   (`qqh` == legacy `vbf`) taken straight from the legacy ground truth above.
   Result for `mt`: `ggh`(0)/`qqh`(1) signal; `ztt`(2)/`ff`(3)/`zll`(4)/`tt`(5)/
   `misc`(6) background — physically exactly the legacy split.
2. **`mt` only, on purpose.** `et`/`tt` were *not* added: doing so would mean
   mixing two naming schemes across channels (TauKITFlow names for `mt`, legacy
   `dyjets_*`/`jetFakes`/`ttbar`/`diboson` names for `et`/`tt`) with no
   TauKITFlow-side `category_mapping` to reconcile against, and `mt` is the only
   channel validated end-to-end anywhere in this rework. Documented inline in
   `category_selection.py`; deferred until `category_mapping` itself grows those
   channels. (Noted, not swept under the rug — this is a naming-scheme boundary,
   not laziness.)

**Also fixed (would otherwise have been a false-positive re-block):**
`config/shapes/category_selection.py` imported `ntuple_processor` unconditionally
at module top. The CMSSW/`cmsenv` datacard session has no `ntuple_processor`, so
`categories.py`'s `from config.shapes.category_selection import DNN_CLASS_MAPPING`
would have raised `ImportError` → mis-caught as the very `NotImplementedError`
we're closing. Guarded the import in `try/except` (mirroring smhtt_ul's own
file) and skip only the production-side `categorization` build when it's absent;
`DNN_CLASS_MAPPING` stays importable with or without `ntuple_processor`.
Confirmed both ways (bare `python3` and under `cmsenv`).

### Real end-to-end validation (structurally-faithful synthetic shapes)

Environment: CMSSW_15_0_2 via `utils/setup_cmssw.sh` (`cmsenv`), with
`PYTHONPATH` = repo root + `TauFakeFactors/` (the `CustomLogging` package lives
in that submodule, exactly as `datacards/produce_datacard.sh` sets it; the
worktree's own submodule is unpopulated, so the main checkout's
`/work/sgiappic/TauKITFlow/TauFakeFactors` was used read-only for the run).

Built 7 structurally-faithful synthetic per-category synced files — the same
honestly-labeled synthetic approach Phase 2d used, **not** fabricated "real"
data — one per DNN class, matching exactly what
`shapes/convert_to_synced_shapes.py` emits and what `make_datacards.py`'s
`stxs_stage0_run3` branch consumes:
`synced_shapes-2024-mt-synthetic-dnn/2024-mt-synced-{ggh,qqh,ztt,ff,zll,tt,misc}.root`,
each with a `TDirectory mt_<cat>` containing `ZL, TTL, VVL, EMB, jetFakes`
(= `get_backgrounds("mt", embedding=True, jetfakes=True)`), `ggH_htt125,
qqH_htt125` (= `get_signals("stxs_stage0")` @ m=125), `data_obs`, plus
`CMS_PileUp` Up/Down (MC processes) and `CMS_ff_total_sub_syst_mt_2024` Up/Down
(jetFakes) shape templates to exercise shape-systematic attachment in this path.

`python3 combine_datacards/make_datacards.py --era 2024 --channels mt
--categories stxs_stage0_run3 --stxs-signals stxs_stage0 --input-folder <scratch>
--ntuple-tag synthetic --tag dnn --embedding True --jetfakes True
--real-data False --systematics True --bbb True --convert-shapes-to-lnN False
--rebinning-strategy none` produced, **with no `NotImplementedError` and no
errors**:
- **7 per-category datacards** `htt_mt_{ggh,qqh,ztt,ff,zll,tt,misc}_2024.txt` +
  `common/htt_input_2024.root`, one bin each (`imax 1`, `jmax 6`).
- Each card's process block is correct: `ggH_htt`/`qqH_htt` as signal
  (process id `-1`/`0`), `ZL/TTL/VVL/EMB/jetFakes` as backgrounds (`1..5`).
- **Both shape systematics survived and attached** in the DNN path
  (`CMS_PileUp` on MC, `CMS_ff_total_sub_syst_mt_2024` on jetFakes), alongside
  the expected lnN priors — confirming the DNN path exercises the same
  systematics/filtering machinery Phase 3/4 validated for `gof`.
- `combineCards.py` combined them into `mt/combined.txt`: **`imax 7`** (all 7
  DNN bins), **`jmax 6`**, **`kmax 14`** nuisances — the signal categories
  (`ggh`, `qqh`) ordered first, background/control categories after, exactly as
  `get_categories(stxs_stage0_run3)` returns.
- **`text2workspace.py combined.txt -m 125`** ran to completion (exit 0),
  producing a valid 79 KB RooWorkspace with per-bin autoMCStats — i.e. the
  combined DNN datacard is genuinely valid Combine input, not just
  syntactically well-formed text.

### Honest boundary — what is NOT yet validated (the real, larger remaining gap)

**Real DNN-scored physics content does not exist yet, and this slice did not
fabricate it.** TauKITFlow's DNN categorization (`category_selection.py`'s
`categorization`) selects on friend-tree branches `{channel}_max_index` /
`{channel}_max_score`, supplied via `--*-friend-directory`. But:
- `friends/build_friend_tree.py` (the only friend producer in the repo) writes
  **only normalization-weight branches** (`numberGeneratedEventsWeight`,
  `crossSectionPerEventWeight`, `negative_events_fraction`) — **no DNN-score
  branch at all.** There is no DNN-inference/score friend producer in TauKITFlow.
- There is also an **unreconciled branch-name divergence**: TauKITFlow expects
  `{channel}_max_index`/`{channel}_max_score`, whereas smhtt_ul's current
  (`77af7d0`) NN code emits `nn_predicted_class`/`nn_predicted_max_value`.

So producing a *real* 2024/mt DNN-scored shape file needs, as a separate and
materially larger future slice: (a) a DNN-inference step + score friend-tree
producer, (b) reconciling that branch-naming, (c) then
`produce_shapes.py` (default, DNN categorization) → `convert_to_synced_shapes.py`
→ this datacard path with real templates. That's a distinct piece of work with
its own physics validation, not something closeable by config alone. **What this
slice closes is precisely the config + datacard-construction gap** (Blocker #3),
validated with faithful synthetic shapes — the boundary the task anticipated in
its point 4.

### Files changed

- `config/shapes/category_selection.py` — added `SIGNAL_CLASSES` +
  `DNN_CLASS_MAPPING` (single-sourced off `category_mapping`, `is_signal` from
  legacy `77af7d0`); guarded the `ntuple_processor` import so `DNN_CLASS_MAPPING`
  imports cleanly under `cmsenv`. No changes to `combine_datacards/` were needed
  — `categories.py`'s `stxs_stage0_run3` path already consumed this dict; it just
  had nothing to consume before.

## Phase 5.1 — Root-cause TTL/VVJ discrepancies

Status: **DONE for TT-TTT/TTL/TTJ and VV-VVT/VVL (now bit-identical to a fresh
smhtt_ul rerun). VV-VVJ remains a real, unresolved ~25.7% residual** — root-cause
not found despite exhaustive code-level diffing; documented as an open item below
rather than papered over, per the stop condition.

**Method:** reran real 2024/mt shapes fresh through both frameworks against the
live CROWN production (`htt_260602_2024-25_v5`), restricted to
`--process-selection ttt,ttl,ttj,vvt,vvl,vvj` / `--control-plot-set m_vis,pt_1,pt_2`
(narrowed scope for a same-day turnaround — full-variable-set reproduction is a
strictly larger version of the same run, not expected to change any conclusion
below since these are channel/process-level weight and cut effects, not
variable-specific):
- TauKITFlow (this worktree, `taukiktflow` conda env):
  `shapes/produce_shapes.py --era 2024 --channels mt --vs-jet-wp Medium --vs-ele-wp
  VVLoose --apply-tauid --control-plots --control-plot-set m_vis pt_1 pt_2 --xrootd
  --directory /store/user/sgiappic/CROWN/ntuples/htt_260602_2024-25_v5/CROWNRun
  --mt-friend-directory .../CROWNFriends/xsec/ --process-selection
  ttt,ttl,ttj,vvt,vvl,vvj --skip-systematic-variations --no-dnn-categorization`.
- smhtt_ul (`/work/sgiappic/smhtt_ul`, LCG_106 view via `utils/setup_root.sh`, no
  conda — same house rule as Phase 2d/3): identical processes/variables/WPs via
  `shapes/produce_shapes.py` directly (the equivalent of
  `control_plots_ul.sh -m SHAPES`).
- Comparator: the existing `plotting/compare_control_shapes.py` (Phase 2b), plus a
  direct `TH1::Integral()`/bin-error read for the specific before/after numbers
  below (needed to see per-fix deltas at higher precision than the comparator's
  pass/fail log lines give).

### Root cause #1 (small, confirmed, FIXED): stale `ttbar_em_weight` calibration

`ttbar_em_weight()` in `config/shapes/process_selection.py` (both frameworks)
applies a hardcoded, per-era data/MC ttbar normalization scale factor (an
em-channel control-region measurement), multiplied into every TTT+TTL event.
TauKITFlow's copy carried a **stale** set of `ratio_em` values (m_vis>100 only, no
nbtag cut — 2024: `0.926025`); smhtt_ul's live checkout has since been recalibrated
(`config/shapes/calculate_ttbar_weights.py`, "260602" tag, nbtag>=0 selection) to a
**different, newer** set (2024: `0.945792`) — the old values are left commented out
in smhtt_ul's own file with an explicit "wrong weight for 24-25" comment. Updated
TauKITFlow to the current smhtt_ul values for all 6 Run3 eras. Small effect in
isolation (~1-2% depending on era) but real and dated.

### Root cause #2 (small, confirmed, FIXED): `btag_weight` wrongly excluded from `mt`

`MC_base_process_selection()` in TauKITFlow excluded **both** `mm` and `mt` from the
per-event `btag_weight` data/MC b-tag scale-factor reweighting
(`if channel not in ("mm", "mt"): ...append(btag_weight)`). smhtt_ul's live
reference only excludes `mm` (`if channel != "mm":`, with a
`# and channel != "mt"` **commented out**, i.e. disabled — mt gets `btag_weight`
there today). Confirmed directly that the real 2024 CROWN production ships a
`btag_weight` branch for `mt` (branch-list check on a live TT ntuple file:
`['btag_value_1', 'btag_value_2', 'btag_weight', 'nbtag']` present). The `mt`
exclusion was inherited from a Phase 2a fix for a genuine but *era-specific* gap
(the 2018 CROWN validation production used there does not ship `btag_weight` at
all) that was incorrectly encoded as a *channel*-level exclusion instead of an
*era*-level one, silently also breaking `mt` for every Run3 era where the branch
does exist. Fixed by keying the guard on `era not in RUN2_PRODUCTION_ERAS`
(`config/analysis.py`) instead of `channel`, matching smhtt_ul's channel-only
(`mm`-only) exclusion for every era that actually has the branch. Small effect in
isolation (~1-2%).

### Root cause #3 (dominant, confirmed, FIXED): two global cuts entirely missing from `channel_selection()`

This is the fix that actually closed the bulk of the gap. smhtt_ul's live
`config/shapes/channel_selection.py` sets, **unconditionally for every channel**,
right after the jet-veto-map cut and before the per-channel branch:
```python
cuts["pt"] = "(pt_2 > 25)"
cuts["mt"] = "mt_1 < 60"
```
Both are active (not commented out) in the current reference — confirmed by
reading the file directly and by diffing the actual per-run booking log output
side by side (`channel_selection (Cuts): Using: ... pt: (pt_2 > 25) / mt: mt_1 <
60 / ... mt_cut: (mt_1 < 70)` on the legacy side vs. no `pt`/`mt` entries at all on
the TauKITFlow side, otherwise identical cut lists). TauKITFlow's
`channel_selection.py` had **no equivalent of either cut** — it only ever applied
the separate, per-channel, looser `mt_cut: (mt_1 < 70)`, and no `pt_2` floor at
all. Net effect: TauKITFlow was letting through every event with
`60 <= mt_1 < 70` and every event with `pt_2` between whatever the trigger-implied
floor is and 25 GeV that smhtt_ul's live selection excludes — a real, silent
over-inclusion affecting every MC process in every channel, not something visible
in the DY/W/signal comparisons because those already agreed well enough (~0.4%,
Phase 3) that this hadn't been suspected, but which dominates the *relative*
picture for TT/VV because those processes are the two families where changes near
the `mt_1` boundary are most populated (real/fake top and diboson topologies).
Fixed by adding both cuts to TauKITFlow's `channel_selection()`, unconditionally,
matching smhtt_ul's placement and text exactly.

### Before/after numbers (2024/mt, `m_vis`, `Nominal` selection; both integrals bin-by-bin summed; legacy lumi-corrected by the independently-confirmed, still-live smhtt_ul-side 2x lumi bug documented in Phase 3, `218.9/109.816`)

| process | raw ratio (before any Phase 5.1 fix) | raw ratio (after all 3 fixes) | lumi-corrected ratio (after) | n_sigma (after) |
|---|---|---|---|---|
| TT-TTT  | 0.6528 | 0.5017 | **1.0000** | 0.000 |
| TT-TTL  | 0.7100 | 0.5017 | **1.0000** | 0.000 |
| TT-TTJ  | 0.7789 | 0.5017 | **1.0000** | 0.000 |
| VV-VVT  | 0.6577 | 0.5017 | **1.0000** | 0.000 |
| VV-VVL  | 0.7411 | 0.5015 | **0.9997** | 0.081 |
| VV-VVJ  | 0.6151 | 0.3729 | **0.7433** | 40.724 |

("raw ratio" = `new_integral / legacy_integral` before dividing out the known
lumi factor; the middle column isolates the effect of the 3 fixes above, all
still expressed at raw — i.e. pre-lumi-correction — scale, which is why it moved
*closer to* the pure-lumi value `109.816/218.9 = 0.50168` rather than to 1: once
the pt/mt/btag/ttbar_em_weight bugs were fixed, the only remaining difference
between the frameworks for TTT/TTL/TTJ/VVT/VVL is the already-known, independently
confirmed, smhtt_ul-side lumi doubling — dividing that back out gives the
lumi-corrected column, which is where the real physics-content agreement is
judged.)

**TT-TTT, TT-TTL, TT-TTJ, and VV-VVT are now bit-identical to the fresh smhtt_ul
reference (n_sigma = 0.000 exactly — i.e. every difference has been accounted
for). VV-VVL agrees to 0.08σ (0.03% relative).** This resolves, with a real
mechanism and real numbers (not a fudge factor), both of the originally-flagged
findings for every TT subprocess and two of the three VV subprocesses:
Phase 2b's +3.9% TT-TTL (2022preEE) and Phase 3's ~1.6% TT-TTT/TTL (2024)
residuals are both explained by these three fixes (chiefly root cause #3, the
missing global cuts) — a different era, but the same underlying code bug, present
in `channel_selection()`/`process_selection.py` regardless of era.

### VV-VVJ: real, unresolved ~25.7% residual — NOT explained by any difference found

**VV-VVJ still shows a large, statistically-significant deficit: raw ratio 0.3729,
lumi-corrected 0.7433 (25.67% low), n_sigma = 40.7 — i.e. this is not consistent
with MC statistical noise (the integral's own relative stat uncertainty is only
~0.6%; a 40σ pull means the two numbers are genuinely, significantly different,
not just noisy).** This number is close to (marginally larger than) Phase 3's
original 26.6% VV-VVJ finding from a completely different (broader) production run
— i.e. this is a real, reproducible, persistent effect, not a fluke of the
narrower rerun.

**What was checked and ruled out** (each confirmed by direct comparison, not
assumption):
- `VVJ_process_selection()`'s cut text (`(gen_match_2 == 6)` for mt/et) is
  byte-identical between frameworks.
- `VV_process_selection()`'s full weight list (`MC_base_process_selection` +
  `numberGeneratedEventsWeight` + the `crossSectionPerEventWeight` expression) is
  byte-identical between frameworks, and — critically — is the *same object*
  shared by VVT/VVL/VVJ within a framework, so a weight-formula bug would move all
  three VV subprocesses together, not just VVJ. VVT/VVL do NOT show this residual
  (0.000σ / 0.08σ respectively), which rules out a VV-wide weight or
  normalization bug as the explanation for VVJ specifically.
- The underlying dataset/file list is identical: diffed the
  `validation_database/.../2024_mt_VV.yaml` file-set actually validated by both
  runs — **573 files on both sides, zero set difference** (same 20-sample
  diboson+single-top merge, same production tag). Rules out a sample-list/file-set
  cause.
- `tauidweight` (the one weight component that's explicitly gen-match-conditional,
  `((gen_match_2==5)*id_wgt_tau_vsJet_WP_2 + (gen_match_2!=5))`) is set and then
  immediately overwritten back to `None` in **both** frameworks' `mt`-channel
  branch (`tauidweight = None` appears verbatim, same two-line pattern, in both
  `process_selection.py` files) — an identical no-op in both, not a discrepancy,
  and in any case evaluates to a factor of exactly 1 for `gen_match_2 == 6`
  (VVJ's own selection condition) regardless of whether it's applied, so it
  cannot be the cause even if it weren't already a matched no-op.
- TauFakeFactors' `btag_efficiency.py`/`configs/btag_efficiency/` (per this task's
  explicit hint to check) is not in the code path at all for this comparison:
  `MC_base_process_selection`'s `btag_weight` is a flat per-event branch read
  directly from the CROWN friend tree (root cause #2 above), not derived from
  TauFakeFactors' efficiency maps — those are used elsewhere in the framework
  (fake-factor QCD/W+jets estimation), not in the TT/VV process-splitting weight
  chain being compared here. No wiring between the two was found.

**Working hypothesis, not confirmed:** since VVJ is specifically the
genuinely-jet-faked-tau slice of VV (`gen_match_2 == 6`, i.e. the tau candidate is
not matched to any real generator-level tau or lepton), and every cut/weight
governing *which* events fall into that bin is confirmed identical between
frameworks, the remaining candidate explanations are either (a) a difference
upstream of both frameworks' config layer — e.g. in how the `gen_match_2` branch
itself, or the friend-tree quantities it depends on, were produced/filled at the
CROWN level for specific VV/single-top sub-samples, which neither framework's
config controls and which would require a raw per-event diff (dumping
`gen_match_2` + event id from both frameworks' RDataFrame graphs for the same
files) to pin down, or (b) some other VVJ-specific code path not yet found despite
this session's cut/weight/sample-list audit. Given the exhaustive, itemized
ruling-out above and the time-box on this slice, **this is reported as an open,
unresolved residual rather than guessed at further** — per the explicit
instruction to stop and document rather than loop indefinitely. Whoever picks
this up next should start with a raw per-event `gen_match_2` dump comparison on
one small VV sample (e.g. `WZto3LNu_...Run3Summer24...`) read identically by both
frameworks' RDataFrame graphs, to determine whether (a) or (b) above is the actual
mechanism.

### Files changed

- `config/shapes/process_selection.py` — `ttbar_em_weight()` updated to smhtt_ul's
  current "260602" `ratio_em` values (root cause #1); `MC_base_process_selection()`
  `btag_weight` guard changed from `channel not in ("mm", "mt")` to
  `channel != "mm" and era not in RUN2_PRODUCTION_ERAS` (root cause #2).
- `config/shapes/channel_selection.py` — added the two previously-missing global
  cuts, `cuts["pt"] = "(pt_2 > 25)"` and `cuts["mt"] = "(mt_1 < 60)"`, applied
  unconditionally for every channel, matching smhtt_ul exactly (root cause #3,
  the dominant fix).

### Not done / explicitly out of scope for this slice

- VV-VVJ's residual (see above) — real, reproducible, not closed.
- Re-running the full (all-process, all-variable) 2024/mt control-plot comparison
  that Phase 3 ran, to get an updated overall pass-rate number analogous to
  Phase 3's "109/912" — this slice's rerun was deliberately scoped to
  TT/VV-only + 3 variables for turnaround time; the mechanism found (root cause
  #3 especially) is channel/process-selection-level, not variable-specific, so it
  should improve the full comparison too, but that hasn't been directly measured.
- The still-live smhtt_ul-side 2x lumi bug (Phase 3 finding, confirmed still
  present in this session's fresh legacy run: `lumi: 218.9 * 1000.0` in the
  booking log) is unchanged — it's a bug in smhtt_ul's live checkout, not
  TauKITFlow's, out of scope to "fix" here (would mean editing smhtt_ul).
  TauKITFlow's own lumi value (`109.816`, from `config/analysis.get_luminosity`)
  remains correct, per Phase 1.
- Era coverage: only 2024/mt was rerun fresh in this slice (matching the task's
  primary validation dataset). The Phase 2b 2022preEen +3.9% TT-TTL finding is
  explained by the same code-level bugs (channel_selection/process_selection are
  era-generic, the bugs applied to every Run3 era), not independently
  re-measured at 2022preEE with a fresh rerun.

## Blockers

Note: none of the below block Phase 2a specifically — see "Not done / explicitly out
of scope" under Phase 2a for items deliberately deferred in that slice.

1. **RESOLVED by Phase 2a.** Was: real 2024 shape production crashed on a missing
   `Jet_vetomap` branch (`shapes/produce_shapes.py --era 2024 --xrootd --directory
   /store/user/sgiappic/CROWN/ntuples/htt_260602_2024-25_v5/CROWNRun
   --gof-inputs ...` failed with `RDataFrame: error: use of undeclared
   identifier 'Jet_vetomap'`). Root cause (found independently while extending to
   2018, see Phase 2a): `config/shapes/channel_selection.py` hardcoded the cut as
   `(Jet_vetomap < 0.5)` (capital J), but the real CROWN branch is lowercase
   `jet_vetomap` in both Run3 and 2018 output — a pre-existing bug, not a
   production/config mismatch as originally suspected. Fixed at
   `config/shapes/channel_selection.py:104` (`cuts["jet_vetomap"] =
   "(jet_vetomap < 0.5)"`), applies to every era/channel unconditionally.
   `config/cuts.yaml`'s `jet_veto:` entries (still show capital-J `Jet_vetomap`
   in the YAML) are now dead/superseded by this code-level override — worth
   fixing the YAML too for consistency, but not functionally blocking since
   `channel_selection.py` always overwrites it. Original notes, kept for
   context: this blocked full physics-content validation of Phase 2d
   (worked around with a synthetic shape file, documented above) and would have
   blocked Phase 3's real bin-by-bin comparator until fixed — no longer the case.
2. **RESOLVED by Phase 3.** Was: "`convert_to_synced_shapes.py` referenced but
   never found." SMRun2Legacy's original `categories.py` comment ("Category
   names match convert_to_synced_shapes.py output") implies a per-category
   shape-file-splitting step between shape production and `stxs_stage0_run3`
   datacard production; Phase 2d's filesystem search did not find it. It does
   in fact exist, at `/work/sgiappic/smhtt_ul/shapes/convert_to_synced_shapes.py`
   (Phase 2d's search evidently missed it despite smhtt_ul being on the search
   path) — pure ROOT + stdlib, no external deps. Phase 3 relocated it verbatim
   to `shapes/convert_to_synced_shapes.py` and used it for real (`--gof --mc`)
   to bridge a real 2024/mt shape file into a Combine datacard — see Phase 3's
   "Goal 2" section. The `stxs_stage0_run3` (DNN) categorization path still
   additionally needs Blocker #3 (`DNN_CLASS_MAPPING`) closed before it can use
   this converter end-to-end; the `gof` path (what Phase 3 validated) does not.
3. **PARTIALLY RESOLVED by Phase 4b.** Was: "`config/shapes/category_selection.py`
   lacks `DNN_CLASS_MAPPING`" — blocked `--categories stxs_stage0_run3`. **Config
   + datacard-construction half is now closed:** `DNN_CLASS_MAPPING` is defined
   (single-sourced off `category_mapping`, `is_signal` from smhtt_ul `77af7d0`),
   the `NotImplementedError` is gone, and `make_datacards.py --categories
   stxs_stage0_run3` builds a real 7-category datacard + valid workspace (see
   Phase 4b for numbers). **Still open — a distinct, larger gap:** no real
   DNN-scored shapes exist yet, because TauKITFlow has no DNN-score friend-tree
   producer (`friends/build_friend_tree.py` writes only normalization weights)
   and the friend-branch names are unreconciled with smhtt_ul
   (`{channel}_max_index/max_score` vs `nn_predicted_class/nn_predicted_max_value`).
   Full physics-content validation of this path is a future slice (DNN inference
   + score friends + branch reconciliation), not a config gap. `gof`/`stxs_stage0`
   remain unaffected either way.

## Addendum plan (2026-07-15) — remaining work items

User supplied a follow-up punch list on top of Phases 1-4b above. Organized into phases by
dependency (structural changes that touch overlapping files are grouped into the same slice to
avoid worktree merge conflicts; cleanup/docs deferred to last since earlier phases will create
new dead code and change the structure docs need to describe).

### Phase 5 — sequential foundation (2 independent tracks, each blocking its own Phase 6 dependents)

- **5.1** — Root-cause and fix the TTL/VVJ discrepancies flagged in Phase 2b/2d (TT-TTL ~+3.9%/~1.6%,
  VV-VVJ ~26.6% residual). Rerun the 2024 samples fresh through smhtt_ul to get up-to-date reference
  shapes, bin-by-bin compare against TauKITFlow, find the actual root cause(s), and fix until they
  agree within the established tolerance. This is the trust foundation the Phase 6 comparators below
  build on. (Running in a sibling worktree in parallel with 5.2 below.)
- **5.2** — Config duplication cleanup: reconcile `config/cuts.yaml` vs `channel_selection.py` vs
  `category_selection.py` (single-source the cuts, no shadow copies), and audit/collapse redundant
  shape-production passes across control-plots/training/combine so each is generated as few times as
  possible. Also move non-config files/actions currently sitting under `config/` to a directory that
  matches what they actually do. **See "## Phase 5.2" below for the full record.**

### Phase 6 — parallel vertical slices (own worktree/branch each), after Phase 5 lands

- **6a** — Run Run2 (2018) samples through smhtt_ul and compare against how TauKITFlow handles the
  same data.
- **6b** — tauES: run and validate the tauES samples (using CROWN directly if needed), and extract
  the tauES calculation out of smhtt_ul (`tauID_SFs_dev` branch) into its own dedicated space inside
  TauKITFlow, wired consistently into the rest of the framework.
- **6c** — Remove the `law` dependency from the training setup; submit to condor directly (same
  philosophy as the rest of the framework's Python submission code) and rewrite the local
  (non-condor) workflow to not use law either.
- **6d** — Convert remaining bash scripts to Python control scripts/routines, framework-wide.
- **6e** — TauFakeFactors slimdown: make it use TauKITFlow's central preselection code instead of its
  own, extract the btag efficiency code out into its own dedicated space, and integrate
  TauFakeFactors as a seamless part of the whole framework's workflow rather than a bolted-on step.
- **6f** — Decide whether `ntuple_processor` (vendored booking/optimization/variations layer) is
  still needed, and if so rework it into modern, simpler code either in place or relocated.

### Phase 7 — sequential, after Phase 6 merges

- **7.1** — Final framework-wide dead-code cleanup pass (deferred to last on purpose: Phase 6's
  structural moves will themselves create newly-dead code that an earlier pass would miss).
- **7.2** — Write documentation as a README with example calls for each step, in the order they're
  meant to run — deferred to last so it describes the settled structure, not a moving target.

Each slice agent: read this file and the relevant Phase 1-4b sections above for context, work in its
own worktree/branch, run its own validation, and update this file (append, don't rewrite prior
sections) with what's done/validated/blocked before merging to master.

## Phase 5.2 — Config duplication cleanup + move non-config files out of config/

Status: **DONE.** (Written incrementally as work progressed, per explicit instruction to checkpoint
STATUS.md + commit periodically rather than only at the end; the "checkpoint" language earlier in
this section reflects the in-progress state at that point in the session and is left as-is below
rather than rewritten, with this final status line added on top.)

Branch: `phase5.2-config-cleanup` (this worktree). Running in parallel with a sibling agent's
Phase 5.1 (physics-discrepancy root-cause) in a different worktree — no direct coordination, and
this slice does not touch shape-production physics logic/cut *values*, only structure/duplication/
file placement, per the task scope.

### Duplication #1 found: `config/shapes/tff_adapter.py` — dead shadowed re-implementations

`tff_adapter.py`'s own docstring claimed it was a pure "backward-compatibility shim... all
functionality has moved to config/analysis.py", importing `build_files_dict`,
`get_background_samples as get_background_sample_names`, `get_preselection_cuts as
get_tff_event_selection`, `get_mc_weights as get_tff_mc_weights`, `get_samples as
get_combined_files`, `build_presel_files_dict` from `config.analysis` — but then **redefined every
one of those same names locally, below the import**, so the local defs silently shadowed the
aliased imports. Confirmed by repo-wide grep that only `get_tff_event_selection` is actually
imported from this module anywhere (`shapes/selection/channel_selection.py`, one call site) — the
other five re-implementations (`get_background_sample_names`, `get_tff_mc_weights`,
`get_combined_files`, `build_files_dict`, `build_presel_files_dict`) were **100% dead code**, and
would have raised `NameError` on an unimported `logger` if ever actually called (this module never
imported `logging`/`logger`) — further confirming they were never exercised by any test or real run.

**Fix:** rewrote `tff_adapter.py` down to its one real, used function
(`get_tff_event_selection`/`_load_tff_yaml`), removed the dead shadowed re-implementations and the
now-misleading "pure shim" docstring. Documented in the new docstring **why**
`get_tff_event_selection` is deliberately *not* a re-export of
`config.analysis.get_preselection_cuts` (the obvious "just delegate" fix): it reads the TFF
submodule's own generated `preselection_{channel}.yaml` directly, not `config/cuts.yaml`, because
`config/cuts.yaml` → TFF YAML is a **build/sync step** (`config/generate_tff_configs.py`, run
manually, not automatically on every `cuts.yaml` edit) — reading the TFF YAML directly guarantees
`channel_selection()`'s tau-ID/vsMu/trigger cuts always match what TauFakeFactors will actually use
for the fake-factor measurement selection (the entire point of routing through this adapter),
rather than transiently reading a `cuts.yaml` value that's already moved past the last
regeneration. This is intentional, recorded design, not an unreconciled duplicate — `config/cuts.yaml`
stays the one editable source of truth for the cut *values*, TFF's generated YAML is a downstream
copy of it, and this one call site deliberately reads that downstream copy.

### Duplication #2 found (bigger): `config/cuts.yaml`'s entire `channel_selection:` block was 100% dead YAML

Confirmed by grep (`"channel_selection"` as a dict key) that **nothing in the Python codebase ever
read `cuts.yaml`'s top-level `channel_selection:` block** (`common:`/`et:`/`mt:`/`tt:` sub-blocks:
`extraelec_veto`, `extramuon_veto`, `dilepton_veto`, `os`, `tau_iso` (with a `{vs_jet_wp}`
placeholder — the YAML's own comment even says *"`{vs_jet_wp}` is a runtime placeholder filled by
channel_selection.py"*, i.e. this wiring was clearly intended but never actually built), `mt_cut`,
`ele_iso`/`muon_iso`). Instead, `shapes/selection/channel_selection.py` (formerly
`config/shapes/channel_selection.py`) had every one of these same cut strings hardcoded as Python
literals — a byte-for-byte, unintentional duplicate of the YAML, with the YAML being the dead copy
this whole time. This is the same class of bug STATUS.md's pre-existing Blocker #1 already flagged
for the narrower `jet_veto` case (also confirmed still true: `channel_selection.py` hardcoded its
own `jet_vetomap` cut rather than reading `config/cuts.yaml`'s `preselection.*.jet_veto` entry via
`get_preselection_cuts()`, even though `shapes/preselect.py` already reads that same entry
correctly for signal samples) — this audit found it's not just `jet_veto`, it's the *entire*
`channel_selection:` YAML block.

**Reconciliation decision:** per the "data lives in YAML, era/channel-conditional logic stays
Python" philosophy already recorded in this file's Phase 1 section, these are cut-value *data*
(simple string literals/formulas, not era/channel-branching logic), so **`config/cuts.yaml` is the
single source of truth going forward**, not the Python file. Added
`config.analysis.get_channel_selection_cuts(channel, era=None)` (mirrors the existing
`get_preselection_cuts()` pattern: merges `common` + per-channel sub-block, with optional
`era_overrides` support for forward-compatibility even though none exist in the YAML today).
`shapes/selection/channel_selection.py` now calls this getter instead of hardcoding the values a
second time; `jet_vetomap` now reads `get_preselection_cuts(era, channel)["jet_veto"]` instead of
its own separate hardcoded copy (closing the narrower part of Blocker #1 too), with the pre-existing
hardcoded default kept as a fallback only for the `em` channel (which cuts.yaml's `preselection:`
block doesn't define — same channel coverage as before, not a behavior change).

**Verified byte-for-byte no behavior change** (real import, `taukiktflow` conda env,
`TauFakeFactors`/`ntuple_processor` symlinked in for the session per the documented worktree-submodule
workaround, restored to empty dirs before every commit): called
`channel_selection(channel=ch, era="2024", vs_jet_wp="Medium", vs_ele_wp="VVLoose")` for
`ch in ("mt", "et", "tt")` before vs. after the refactor and diffed the resulting `Selection.cuts`
list — identical cut-name-to-expression pairs in both cases, e.g. `mt`:
`extraelec_veto=(extraelec_veto < 0.5)`, `jet_vetomap=(jet_vetomap < 0.5)`,
`tau_iso=(id_tau_vsJet_Medium_2 > 0.5)`, `mt_cut=(mt_1 < 70)`, `muon_iso=(iso_1 < 0.15)`, etc. — and
`tt`'s `tau_iso=(id_tau_vsJet_Medium_1 > 0.5) && (id_tau_vsJet_Medium_2 > 0.5)` (the `.format()`
substitution of the YAML's `{vs_jet_wp}` placeholder producing exactly the same string the old
f-string literal did).

### Move #1: "selection logic" out of `config/` into `shapes/selection/`

Per the task's explicit instruction (naming `channel_selection.py`/`category_selection.py` as the
example), moved the four modules that are genuinely **executable, era/channel-conditional
selection/weight-string-building logic** (not config data) out of `config/shapes/`:
`channel_selection.py`, `category_selection.py`, `process_selection.py`, `variations.py` →
new package **`shapes/selection/`** (sibling to `shapes/produce_shapes.py`, which is their only
real first-party consumer besides `combine_datacards/categories.py`).

Chose `shapes/selection/` over a bare top-level `selection/` package specifically to avoid a name
collision: `shapes/produce_shapes.py` already has a local variable/import alias `selection` (`import
...process_selection as selection`) at several call sites — nesting under `shapes/` avoids that
collision while still describing what the package is for.

**Left in `config/shapes/`, on purpose** (data tables / thin shims, not selection logic):
`control_binning.py`, `gof_binning.py`, `taues_measurement_binning.py` (binning-edge arrays keyed by
variable name — data, expressed in Python only because `np.linspace`/irregular bin edges don't
serialize cleanly to YAML, same class of decision as Phase 1's process_selection.py/variations.py
Python-not-YAML call, just for binning instead of cuts), `signal_files.py` and `tff_adapter.py`
(both thin backward-compat/adapter shims over `config/analysis.py` and the TFF submodule
respectively, not selection logic themselves).

**Also considered and left in place:** `config/generate_tff_configs.py` (a CLI script, not config
data by the letter of the instruction) — judged as tightly-coupled config-sync tooling (regenerates
TFF's derived YAMLs from `config/cuts.yaml`/`samples.yaml`/`weights.yaml`/`variables.yaml`, nothing
else) rather than analysis business logic, and moving it only affects one `run.sh` call site. Left
in `config/` as a judgment call; flagging here in case a future pass disagrees.

**Import updates** (repo-wide grep after the move, confirmed no stale references remain outside of
this file's own historical prose and comments in `shapes/selection/category_selection.py` that
correctly still refer to *smhtt_ul's* file layout, not TauKITFlow's):
- `shapes/produce_shapes.py`: `config.shapes.{process_selection,variations,category_selection,
  channel_selection}` → `shapes.selection.{...}` (control_binning/taues_measurement_binning/
  gof_binning imports unchanged — those stayed put).
- `shapes/selection/variations.py`: its own internal `from config.shapes.process_selection import
  _get_stxs_bin_or_range` → `from shapes.selection.process_selection import ...`; a docstring
  example `from config.shapes import variations` → `from shapes.selection import variations`.
- `combine_datacards/categories.py` (the only other real consumer, imports `DNN_CLASS_MAPPING`) and
  `combine_datacards/make_datacards.py`: `config.shapes.category_selection` →
  `shapes.selection.category_selection`, including the module docstrings/error message text.
- `combine_datacards/__init__.py`, `tools.py`, `systematics.py`, `compare_datacards.py`: doc-comment
  references to ``config/shapes/variations.py`` (naming-convention provenance notes) →
  ``shapes/selection/variations.py``.
- `config/analysis.py`: module docstring's consumer list updated
  (`config/shapes/process_selection.py`/`variations.py` → `shapes/selection/...`).

### Move #2: generic utilities out of `config/` into `common/`

`config/helper_collection.py` (generic `ObjBuildingDict`/`NestedDefaultDict`/
`PreserveROOTPathsAsStrings`/`calculate_stxs_N_and_negative_fractions` utility classes/functions —
no config data, no analysis-specific logic) and `config/ntuple_processor_config_helper.py` (booking-
graph glue helpers for `ntuple_processor`) are pure utility code, not configuration. Moved to a new
top-level `common/` package.

**Regression found and fixed during validation, worth recording:** first attempt moved these two to
`utils/` (the obvious existing home, next to `setup_cmssw.sh` etc.) — this **broke real script
invocation**: `python3 shapes/produce_shapes.py --help` failed with `ModuleNotFoundError: No module
named 'utils.helper_collection'; 'utils' is not a package`, because running a script directly puts
the *script's own directory* (`shapes/`) first on `sys.path`, and `shapes/utils.py` (a pre-existing,
unrelated flat module — booking helpers for shape production) shadowed the top-level `utils/`
package for that one invocation mode (`python3 -c "import ..."` from the repo root didn't show the
bug — only direct script execution, which is how `run.sh`/`condor/*.py` wrappers actually invoke
`produce_shapes.py`, does). Renamed the target package to `common/` instead (no collision anywhere
in the repo, confirmed by checking `condor/common.py` is a submodule-qualified name, not a
top-level-importable `common`). Re-verified `python3 shapes/produce_shapes.py --help` and 7 other
entry points (`shapes/preselect.py`, `shapes/do_estimations.py`, `plotting/plot_shapes_control.py`,
`shapes/convert_to_synced_shapes.py`, `condor/submit_{shapes,plotting,training}.py`) all run cleanly
after the `common/` fix — this regression would otherwise have silently broken every real
shape-production invocation via `run.sh`/condor, so it's recorded here explicitly as a real bug this
slice introduced-then-caught, not a hypothetical.

Import updates: `config/shapes/control_binning.py`, `shapes/selection/process_selection.py`,
`shapes/produce_shapes.py`, `common/ntuple_processor_config_helper.py` (its own internal import of
`helper_collection`) all updated to `common.helper_collection`/`common.ntuple_processor_config_helper`.
`common/helper_collection.py`'s own relative import `from .logging_setup_configs import
setup_logging` (worked when the file lived next to `logging_setup_configs.py` inside `config/`) fixed
to the absolute `from config.logging_setup_configs import setup_logging` now that it's moved out.

### Validation performed so far

Environment: `taukiktflow` conda env; `TauFakeFactors`/`ntuple_processor` symlinked into this
worktree from the main checkout for the session (same one-time worktree-submodule-gap workaround
Phase 3/4/4b documented — restored to empty placeholder directories before every commit, confirmed
via `git status --short` showing no submodule-pointer changes).

1. `python3 -c "import ast; ast.parse(...)"` over every changed/moved file — all parse cleanly.
2. Real imports (not just parse): `config.analysis.get_channel_selection_cuts('mt')`,
   `get_preselection_cuts('2024','mt')['jet_veto']`, `shapes.selection.{channel_selection,
   category_selection,process_selection,variations}` all import and execute correctly; confirmed
   `DNN_CLASS_MAPPING['mt']` still returns the same 7-class dict as before the move.
3. **Byte-for-byte cut-string equivalence** (see Duplication #2 above) for `channel_selection()`
   across `mt`/`et`/`tt` at era `2024`, `vs_jet_wp="Medium"`, `vs_ele_wp="VVLoose"` — identical to
   the pre-refactor hardcoded literals.
4. `--help` run cleanly (rc=0, no tracebacks) for: `shapes/produce_shapes.py`,
   `shapes/preselect.py`, `shapes/do_estimations.py`, `plotting/plot_shapes_control.py`,
   `shapes/convert_to_synced_shapes.py`, `condor/submit_shapes.py`, `condor/submit_plotting.py`,
   `condor/submit_training.py` — all touched by or downstream of this slice's import-path changes.
5. Repo-wide grep for stale `config.shapes.{channel_selection,category_selection,
   process_selection,variations}` / `config.helper_collection` / `config.ntuple_processor_config_helper`
   import paths after the moves — none remain in executable code (only historical/smhtt_ul-referring
   prose, listed above).

### Shape-iteration duplication audit (item 2 of the task) — result: already consolidated for control-plots/combine; training is a structurally different (not redundant) consumer

Checked `shapes/produce_shapes.py`, `plotting/plot_shapes_control.py`, `trainings/`, `datacards/`/
`combine_datacards/` for the specific concern the original framework prompt raised: shapes being
independently *(re-)produced* multiple times for control plots vs. training vs. combine when one
pass could serve all three.

1. **`shapes/produce_shapes.py` is already the single production step for both control-plots and
   combine.** Confirmed by reading `main()`: one `RunManager`/`GraphManager` invocation per script
   run (`shapes/produce_shapes.py:283,300,509,533`), with `--control-plots` vs. `--gof-inputs` vs.
   the default full-analysis categorization selected via `if/elif` branches *within* that one
   `main()` (lines 337-341, 434, 524) — not three separate scripts or three separate RDataFrame
   passes glued together. A given invocation still has to pick one mode (different histogram
   binning needs a different booking graph), but that's an unavoidable one-shape-request-per-run
   reality, not redundant re-derivation of the same output — this is already what "generated as few
   times as possible" looks like for this step.
2. **`plotting/plot_shapes_control.py` and `combine_datacards/` are pure downstream consumers.**
   Neither re-runs `ntuple_processor`/`RDataFrame` over the raw CROWN ntuples or re-derives any cut
   string — `plot_shapes_control.py` reads `produce_shapes.py`'s already-written control-plot ROOT
   file directly (confirmed in Phase 2b/3's validation runs); `combine_datacards/make_datacards.py`
   reads a synced shape file built by `shapes/convert_to_synced_shapes.py` from `produce_shapes.py`'s
   `--gof-inputs` output (Phase 2d/3/4's validated path) via `ExtractShapes`. Both are one
   ROOT-file-read step, not a second physics-selection pass. **No redundant shape production found
   here** — confirmed by evidence (Phase 3/4's own real runs), not assumed.
3. **`trainings/create_training_dataset.py` is a genuinely different consumer, not a duplicate
   production pass of the same thing.** It does not read `produce_shapes.py`'s histogram output at
   all — it needs per-event flat rows for NN features, which a binned histogram ROOT file cannot
   provide by construction, so there is no way for it to "reuse" a control-plot/combine shape file
   even in principle. What *is* shared already: the expensive step — CROWN-ntuple-wide event
   selection/skimming — happens once, in `shapes/preselect.py`, and both shape production (`shapes/
   produce_shapes.py`'s `preselected=True` path, see Phase 1) and (per `trainings/create_training_dataset.py`'s
   `Keys.PATHS`-driven file list, `config[channel][era][process][Keys.PATHS]`) training are expected to
   point at that same preselected output rather than raw CROWN ntuples each doing their own full
   skim independently. What is *not* shared, and is a distinct, external config format from
   `config/cuts.yaml`/`shapes/selection/`: training's own `--config` master YAML supplies
   `subprocess_dict[Keys.CUT]`/`[Keys.WEIGHT]` per subprocess. Traced these through
   `trainings/src/dataset_manipulation.py::nominal_weight_and_cut` (`df[tuple_column(...,
   Keys.CUT)] = self.subprocess_df[cut]...`) — `cut`/`weight` here are used as **column-name
   references into an already-loaded dataframe**, not fresh cut-expression strings evaluated against
   raw kinematic branches. That means the master `--config` YAML is selecting *which
   already-materialised column* (presumably written upstream, at the preselection/CROWN-friend
   stage) a given subprocess should use as its cut/weight mask, not re-authoring the cut *logic*
   itself in a second, driftable place — i.e. this does not look like the kind of "same cut defined
   twice" duplication `config/cuts.yaml`/`channel_selection.py` had. **Not fully traced to where
   those named columns are actually written** (out of this slice's time-box — that master `--config`
   file is itself external/per-training-run, not checked into `config/`, so it's out of this task's
   literal scope of `config/cuts.yaml` vs. `channel_selection.py` vs. `category_selection.py`
   anyway). Recorded here as a residual, deliberately-not-chased-further item rather than silently
   assumed fine: if a future pass finds those column names *are* built by re-authoring cut logic
   somewhere in `trainings/`, that would be a real finding worth its own slice — Phase 6c (law
   removal from the training setup) is a natural place to also revisit this, since it's already
   touching the same subsystem.

**Conclusion for item 2: no redundant shape (re-)production found to collapse.** The framework
already does this correctly for control-plots/combine (one `produce_shapes.py` run per output
mode, both downstream consumers read its output rather than re-deriving); training's separate input
pipeline is structurally necessary (different data shape: per-event vs. histogram) and already
reuses the expensive preselection-skim step, with only a lower-risk, not-fully-verified residual
around its own external per-training-run config format -- flagged above, not fixed, since it's
outside `config/`'s scope and touching it risks the kind of trainings/ config-format redesign this
slice was told to avoid (physics-adjacent, and Phase 2c already declared the training subsystem's
existing (law-based) workflow untouched pending its own dedicated Phase 6c slice).

### Final validation pass

Re-ran the full sanity-check suite (real imports, not just `ast.parse`) after all edits, in the
`taukiktflow` conda env with `TauFakeFactors`/`ntuple_processor` symlinked in for the session and
restored to empty placeholder directories before this final commit (confirmed via `git status
--short` showing no submodule-pointer changes are staged):

- `config.analysis.get_channel_selection_cuts`/`get_preselection_cuts` — correct values for
  `mt`/`et`/`tt`, matching the pre-refactor hardcoded literals exactly.
- `shapes.selection.{channel_selection, category_selection, process_selection, variations}` all
  import cleanly; `channel_selection()` produces byte-identical `Selection.cuts` lists for
  `mt`/`et`/`tt` at era `2024` before vs. after the refactor; `DNN_CLASS_MAPPING['mt']` unchanged
  (still the same 7-class dict Phase 4b validated).
- `--help` runs cleanly (rc=0, no tracebacks) for all 8 touched/downstream entry points:
  `shapes/produce_shapes.py`, `shapes/preselect.py`, `shapes/do_estimations.py`,
  `plotting/plot_shapes_control.py`, `shapes/convert_to_synced_shapes.py`,
  `condor/submit_{shapes,plotting,training}.py`.
- Repo-wide grep for every old import path (`config.shapes.{channel_selection,category_selection,
  process_selection,variations}`, `config.helper_collection`, `config.ntuple_processor_config_helper`,
  and their `config/shapes/...`-style doc-comment forms) confirms zero stale references remain in
  executable code; the only remaining textual hits are historical prose in
  `shapes/selection/category_selection.py` that correctly still describe *smhtt_ul's* file layout
  (a different repo), not TauKITFlow's own.
- No CMSSW/`cmsenv`-side real run was performed in this slice (that would require the Combine/CMSSW
  environment Phase 2d/3/4 used) — the `combine_datacards/*.py` edits in this slice are pure
  docstring/import-path text substitutions (`config.shapes.category_selection` →
  `shapes.selection.category_selection`), verified by grep + `ast.parse`, not a full CMSSW re-run;
  low risk since no logic changed, only the module path referenced.

### Files changed / moved (full list for this slice)

- `config/analysis.py` — added `get_channel_selection_cuts()`; updated docstring's file-path
  references for the two moved modules.
- `config/shapes/tff_adapter.py` — rewritten down to its one real function; removed 5 dead
  shadowed re-implementations.
- `config/shapes/control_binning.py` — import path update (`common.helper_collection`).
- **Moved** `config/shapes/channel_selection.py` → `shapes/selection/channel_selection.py`
  (behavior change: now reads cuts from `config.analysis.get_channel_selection_cuts()`/
  `get_preselection_cuts()` instead of hardcoding them; verified byte-identical output).
- **Moved** `config/shapes/category_selection.py` → `shapes/selection/category_selection.py`
  (pure move, no content change).
- **Moved** `config/shapes/process_selection.py` → `shapes/selection/process_selection.py`
  (import path update only: `common.helper_collection`).
- **Moved** `config/shapes/variations.py` → `shapes/selection/variations.py` (import path updates
  only: self-referential import + docstring example).
- **Moved** `config/helper_collection.py` → `common/helper_collection.py` (fixed its own relative
  `logging_setup_configs` import to absolute).
- **Moved** `config/ntuple_processor_config_helper.py` → `common/ntuple_processor_config_helper.py`
  (import path update: `common.helper_collection`).
- New: `common/__init__.py`, `shapes/selection/__init__.py`.
- `shapes/produce_shapes.py` — import path updates for all of the above moves.
- `combine_datacards/{categories,make_datacards,__init__,tools,systematics,compare_datacards}.py` —
  import-path/docstring updates for the `category_selection.py`/`variations.py` move (text only,
  no logic changes).

### What was deliberately left as a residual / not chased

- Training's external per-run `--config` master YAML's `subprocess_dict[Keys.CUT]`/`[Keys.WEIGHT]`
  column-name references — see the shape-iteration audit above. Flagged, not fixed: outside
  `config/`'s literal scope, and the columns themselves weren't traced to their origin in this
  time-box.
- `config/generate_tff_configs.py` was considered for a move out of `config/` (it's a CLI
  script/action, not config data, by the letter of the instruction) but left in place as a judgment
  call — it's config-*sync* tooling (regenerates TFF's derived YAMLs from the central `config/*.yaml`
  files, nothing else), tightly coupled to `config/`'s own data, low value to relocate for one
  `run.sh` call site. Noted here rather than silently decided.
- `config/shapes/control_binning.py`/`gof_binning.py`/`taues_measurement_binning.py` stayed in
  `config/shapes/` — judged as data tables (binning-edge arrays), not selection logic, matching
  Phase 1's existing "data in Python only when YAML can't represent it cleanly" precedent.
- `signal_files.py`/`tff_adapter.py` stayed in `config/shapes/` — thin adapter/shim modules over
  `config/analysis.py`/the TFF submodule, not selection logic themselves.

Committed to branch `phase5.2-config-cleanup` in this worktree (two commits: the structural
move/reconciliation, and this STATUS.md write-up). Not pushed, no force operations, no destructive
git commands used, per the task's git-safety instructions.

## Phase 6e — TauFakeFactors slimdown, btag_efficiencies extraction, FF-measurement integration

Status: **DONE.** Branch `phase6e-tff-slimdown`, new worktree
`.claude/worktrees/phase6e-tff-slimdown` (branched fresh from `master`/`a61a3b4`, since this
worktree's shared main checkout had its branch changed out from under it mid-session by another
concurrent agent — see "Worktree note" at the end of this section). Running alongside sibling
agents' 6a/6b/6c/6d/6f slices per the Phase 6 fan-out plan above.

### Part 1 — TauFakeFactors preselection duplication: what was actually found

Before touching anything, audited what "TauFakeFactors' own preselection logic" actually consists
of today, since Phase 5.2 had already built `config/generate_tff_configs.py` (a build/sync script
that regenerates `TauFakeFactors/configs/smhtt_ul/{era}/preselection_{ch}.yaml` from
`config/cuts.yaml`/`samples.yaml`/`weights.yaml`/`variables.yaml`) and `config/shapes/tff_adapter.py`
(reads that generated YAML back for `shapes/selection/channel_selection.py`). Read
`TauFakeFactors/preselection.py` in full: it is **already 100% config-driven** — every cut/weight
it applies comes from `config["event_selection"]`/`config["mc_weights"]` (the YAML passed via
`--config-file`), no hardcoded era/channel cut strings anywhere in the script itself. So the
smhtt_ul FF-measurement preselection side of "TFF has its own duplicate preselection logic" had
already been closed by Phase 5.2's `generate_tff_configs.py` — there was no live duplicate left to
remove there.

What **was** a real, live duplicate, found by diffing `TauFakeFactors/configs/btag_efficiency/{era}/
preselection_{ch}.yaml`'s `event_selection:` block against `config/cuts.yaml`: this is a *second*,
separate TFF preselection config (used only for the b-tag efficiency measurement, completely
independent of the smhtt_ul FF-measurement config Phase 5.2 already fixed) whose `event_selection:`
was a hand-typed, unreconciled copy of most of `config/cuts.yaml`'s `preselection:`/
`channel_selection:` entries (`had_tau_decay_mode`, `had_tau_id_vs_ele`, `jet_veto`, the
extra-lepton vetoes, opposite-sign, tau-vsJet WP cut). This is the actual duplicate this phase
closes — see Part 2 below, since fixing it fell out naturally from relocating the btag-efficiency
code into its own space (its config needed to move anyway).

**Also found and fixed, in `config/generate_tff_configs.py` itself** (the smhtt_ul side):
`_build_event_selection()`/`_build_mc_weights()` were **local re-implementations** of the exact
same common+per-channel+`era_overrides` merge that `config.analysis.get_preselection_cuts()`/
`get_mc_weights()` already do — i.e. two copies of one merge algorithm, one in `config/analysis.py`
(used by `shapes/selection/channel_selection.py`) and one duplicated inline in the TFF-config
generator. Removed the duplicate; `generate_tff_configs.py` now calls the central getters
directly. **Validated byte-for-byte**: wrote a standalone comparison of the old local helpers vs.
the central getters for every (era, channel) combination — **0 mismatches across all 18** Run3
era × {et,mt,tt} combos (dict equality, not just string diff). Also ran a full dry-run
regeneration before/after and confirmed the YAML payload is identical (only cosmetic log-line
differences from the different script filename in the log tag).

### Part 2 — btag efficiency extraction: `btag_efficiencies/`

**Naming decision** (recorded per the repo's established naming philosophy, same reasoning
pattern as `combine_datacards/` in Phase 2d): new top-level **`btag_efficiencies/`** — plural,
matching the actual output (per-era, per-sample-type, per-WP/flavor/pT/eta efficiency maps), and
deliberately *not* named after where it came from. It measures a detector/production-level
quantity (jet b-tag efficiency, consumed downstream as a CROWN-level `btagWeight` branch/friend —
see the `process_selection.py` note below) that has nothing to do with fake-factor measurement,
TauFakeFactors' actual job — it only lived inside the TFF submodule as a historical accident of
where someone put the script.

**Relocated:**
- `TauFakeFactors/btag_efficiency.py` → `btag_efficiencies/calculate_efficiency.py` — moved with
  no logic changes, plus a `sys.path` bootstrap added (before its `import CustomLogging`/
  `import helper.functions` lines) that adds `TauFakeFactors/` to `sys.path` so it keeps reaching
  TFF's generic `CustomLogging`/`helper` packages **as an external library dependency** rather than
  duplicating them — the same "reach a sibling package, don't fork it" pattern
  `combine_datacards/` already uses for `CombineHarvester.CombineTools` (Phase 2d).
- `TauFakeFactors/configs/btag_efficiency/{era}/*.yaml` → `btag_efficiencies/configs/{era}/*.yaml`
  — moved for all 6 Run3 eras.
- `TauFakeFactors/run_eff.sh`, `run_presel.sh` — removed (superseded by
  `btag_efficiencies/run_btag_efficiency.py`, see Part 3-equivalent below).

**New `btag_efficiencies/generate_configs.py`** closes the Part-1 duplicate found above: rebuilds
each `preselection_{ch}.yaml`'s `event_selection:` block from
`config.analysis.get_preselection_cuts()`/`get_channel_selection_cuts()` for `et`/`mt`/`tt`
(single-sourced — same central getters `generate_tff_configs.py` uses). One cut is **deliberately
not** single-sourced: the b-tag efficiency measurement uses a looser transverse-mass cut
(`mt_1 < 50`) than shape production's central `mt_cut` (`mt_1 < 70`) to keep more statistics in its
control region — this is a genuine, intentional physics difference confirmed by diffing the old
file, not undiscovered drift, so it's kept as an explicit named local override
(`_BTAG_CR_MT_CUT`) with a docstring explaining why, rather than silently sourced from a getter
that would make a future central `mt_cut` change silently retune the b-tag efficiency CR too. The
`em` channel is left untouched/unregenerated: `config/cuts.yaml`'s `preselection:`/
`channel_selection:` blocks don't cover `em` at all (same pre-existing gap Phase 5.2 already noted
for `shapes/selection/channel_selection.py`), so there is no central source to regenerate it from.

**`btag_efficiencies/run_btag_efficiency.py`** — new single entry point, `--step
{preselect,calculate,all}`: `preselect` runs `TauFakeFactors/preselection.py` (reused as-is,
already config-driven) against the relocated config, one job per (era, channel); `calculate` runs
`calculate_efficiency.py`, one job per era (its own config's `channels:` list covers every channel
internally in one job, so per-channel fan-out doesn't apply to this step).

**`condor/submit_btag_efficiency.py`** — new, follows the existing `condor/submit_*.py` pattern
(`JobSpec`/`SubmissionPlan`/`submit()` from `condor/common.py`, era/channel defaults from
`config.analysis.RUN3_ERAS`/`get_channels()`): one job per (era, channel) for `--step preselect`,
one job per era for `--step calculate` — matching the two scripts' actual parallelisable
granularity (see script docstring).

**Consumer check (per the task's explicit instruction to verify whatever consumes btag efficiency
maps points at the new location):** grepped the whole non-TFF repo for `btag_efficiency.json`/
`btagEfficiency`/`btag_eff` references. Found none — `shapes/selection/process_selection.py`'s
`btag_weight` (added `("btag_weight", "btagWeight")` to `MC_base_process_selection`'s weight list,
Phase 5.1) reads a **branch already present in the CROWN ntuple** (`btagWeight`, computed upstream
at the CROWN/friend-tree level using the efficiency map, outside this repo), not a file path — so
there was nothing in TauKITFlow's own code pointing at the old
`TauFakeFactors/configs/btag_efficiency/` path to update. The only repo-internal hit was a dead
comment (`# btag_eff = btag_eff`) in `shapes/selection/variations.py:1303`, not a real reference.

**Validated:**
- Real imports under the dedicated `fake_factors` conda env (not `taukiktflow` — see environment
  note below): `import btag_efficiencies.calculate_efficiency` succeeds and its `func` module
  resolves to the real `TauFakeFactors/helper/functions.py` on disk, confirming the `sys.path`
  bootstrap correctly reaches TFF's helper package as an external dependency.
- `btag_efficiencies/generate_configs.py --dry-run` for all 6 Run3 eras × {et, mt, tt}: no errors;
  spot-checked `mt`/`tt` output against the original hand-written YAMLs — semantically equivalent
  (e.g. `lep_iso: (iso_1 < 0.15)` from the central single-value getter vs. the old file's redundant
  `((iso_1 >= 0.0) && (iso_1 <= 0.15))` — isolation is non-negative by construction, so these are
  equivalent, and the new form is the single central definition instead of a second hand-typed
  one); `em` confirmed byte-identical to the pre-existing file (untouched, as designed).
- `condor_submit -dry-run` (real binary) validated classads for both `--step preselect` (6 jobs,
  2 eras × 3 channels) and `--step calculate` (2 jobs, one per era).
- **Environment note, recorded rather than silently worked around:** `TauFakeFactors/helper/
  functions.py` imports `ruamel.yaml`, which is not installed in the `taukiktflow` conda env this
  rework otherwise uses for shape production — confirmed this is a **pre-existing environment gap,
  not something this phase introduced**, by reproducing the identical `ModuleNotFoundError` from
  TFF's own original (pre-move) `helper/functions.py` import under the same env. A separate
  `fake_factors` conda env already exists on this machine with the right dependencies and was used
  for the validation above; TauFakeFactors' own `environment.yml` presumably documents this, and
  this phase doesn't change which env preselection.py/ff_calculation.py/btag scripts expect —
  `run_fake_factor_measurement.py`/`run_btag_efficiency.py` invoke them via `subprocess.run` with
  whatever Python is on `PATH` at call time, same as `run.sh`'s existing PRESEL/FF/FF-CORR modes
  already did (those also assume the caller has activated the right env first).

### Part 3 — Seamless FF-measurement integration: `run_fake_factor_measurement.py` + `run.sh FF-MEASURE`

Before this phase, running the fake-factor measurement meant knowing to invoke four separate
`run.sh` modes by hand, in the right order (`GEN-TFF-CONFIGS`, `PRESEL`, `FF`, `FF-CORR`) — each
already existed and was already documented in `run.sh --help`, but nothing tied them together as
"one step of the pipeline," and nothing enforced the ordering (e.g. forgetting `GEN-TFF-CONFIGS`
after a `config/cuts.yaml` edit silently measures FFs against stale cuts).

New **`run_fake_factor_measurement.py`** (repo root, Python per the framework's "new scripts are
Python" convention) chains all four steps for a given `--era`/`--channels`
(`config.analysis.RUN3_ERAS`/`get_channels()`-defaulted, same convention as `condor/submit_*.py`):
`config/generate_tff_configs.py` → `TauFakeFactors/preselection.py` (per channel) →
`TauFakeFactors/ff_calculation.py` (per channel) → `TauFakeFactors/ff_corrections.py` (per
channel). `--steps` lets you run a subset (e.g. just `ff-corr` after tweaking a correction, without
rerunning preselection). Output lands exactly where `shapes/preselect.py --tff-dir` and
`shapes/produce_shapes.py`'s `--*-friend-directory`/`run.sh`'s `FF_FRIENDS_DIR` already expect —
this script only chains the existing steps, it doesn't change any output path.

Wired into `run.sh` as a new **`FF-MEASURE`** mode (added to the top-of-file mode list and
`--help` text); the four underlying modes (`GEN-TFF-CONFIGS`/`PRESEL`/`FF`/`FF-CORR`) are kept
exactly as-is for granular single-step reruns, not replaced.

**Three real, pre-existing bugs found and fixed while making this chain actually work
end-to-end** (none introduced by this phase — all were latent in `run.sh`'s existing PRESEL/FF/
FF-CORR modes, presumably never actually exercised for a real multi-channel run before):
1. `run.sh`'s `PRESEL` mode passed `--columns "${OUTPUT_FEATURES[@]}"` to
   `TauFakeFactors/preselection.py` — its argparse (checked exhaustively: `--config-file`,
   `--nthreads`, `--ncores`, `--disable-multiprocessing`, `--log-level` only) defines no
   `--columns` argument at all (it reads `output_features` from the config file itself, per Part
   1's audit). Every real `PRESEL` invocation would have failed with "unrecognized arguments:
   --columns ...". Removed.
2. `run.sh`'s `FF`/`FF-CORR` mode defaults assumed one joined config file per invocation
   (`fake_factors_${CHANNELS}.yaml`/`ff_corrections_${CHANNELS}.yaml` with `$CHANNELS` defaulting
   to the raw comma-joined string `"et,mt,tt"`), but confirmed on disk
   (`TauFakeFactors/configs/smhtt_ul/2024/`) that these configs only ever ship **one file per
   single channel** (`fake_factors_et.yaml`, `fake_factors_mt.yaml`, `fake_factors_tt.yaml`,
   `corrections_et.yaml`, etc.) — the old default only ever matched a real file when `$CHANNELS`
   happened to be a single channel. Fixed to loop per channel (same as `PRESEL`); explicit
   `$FF_CONFIG`/`$FF_CORR_CONFIG` overrides still work unchanged for a single explicit file.
3. `FF-CORR`'s default filename prefix was simply wrong: `ff_corrections_{ch}.yaml` vs. the real
   files' `corrections_{ch}.yaml` (no `ff_` prefix) — fixed.

**Validated:** `bash -n run.sh` (syntax); `run_fake_factor_measurement.py --help` runs cleanly;
a real `--steps gen-configs` invocation (safe, idempotent) executed `main()` end-to-end against
real `config/cuts.yaml`/`TauFakeFactors/configs/smhtt_ul/2024/preselection_mt.yaml`; argv
construction for the `presel`/`ff`/`ff-corr` steps (captured via a patched `_run`) was checked
against real filenames confirmed present on disk for era 2024 — all match after the three fixes
above.

### Files changed / added (full list for this phase)

- `config/generate_tff_configs.py` — removed `_build_event_selection()`/`_build_mc_weights()`;
  now calls `config.analysis.get_preselection_cuts()`/`get_mc_weights()` directly.
- **New** `btag_efficiencies/__init__.py`, `calculate_efficiency.py` (moved + `sys.path`
  bootstrap), `generate_configs.py`, `run_btag_efficiency.py`, `configs/{2022preEE,2022postEE,
  2023preBPix,2023postBPix,2024,2025}/*.yaml` (moved; `preselection_{et,mt,tt}.yaml`'s
  `event_selection:` regenerated, `preselection_em.yaml`/`btag_efficiency*.yaml`/
  `common_settings.yaml` unchanged content, just relocated).
- **New** `condor/submit_btag_efficiency.py`.
- **New** `run_fake_factor_measurement.py`.
- `run.sh` — new `FF-MEASURE` mode; `PRESEL`/`FF`/`FF-CORR` modes fixed (see the three bugs above);
  mode list/`--help` text updated.
- **Inside the `TauFakeFactors` submodule** (committed separately, as its own commit
  `518f561 "Remove btag-efficiency code..."` on its existing `run3_smhtt` branch — the submodule's
  gitlink pointer in this repo's own tree is **not** touched/staged, matching the established
  Phase 3/4/4b/5.2 workaround for this submodule; the user's own pre-existing uncommitted
  `CustomLogging`/`datasets` changes were left completely untouched, confirmed via `git status`
  before and after): removed `btag_efficiency.py`, `configs/btag_efficiency/`, `run_eff.sh`,
  `run_presel.sh`.

### Worktree note (for whoever reads this next)

This phase's work was done in a **freshly created** worktree/branch
(`.claude/worktrees/phase6e-tff-slimdown`, branched from `master`), not the worktree path this
session started in (`.claude/worktrees/agent-a262615a30a42ee81`, referenced in this session's
early tool calls) — that path no longer existed partway through the session, and the shared main
checkout at the repo root (`/work/sgiappic/TauKITFlow`) was observed switching branches out from
under this session between tool calls (seen on `phase6f-ntuple-processor`, then
`phase6a-run2-2018-validation`, within the same minute, with no action taken by this session) —
almost certainly a concurrent sibling agent (6a/6f) using that same directory rather than its own
isolated worktree. To avoid any risk of clobbering that concurrent work or the user's own
uncommitted `TauFakeFactors` submodule changes, this phase created its own dedicated worktree
before doing anything further, mirroring the pattern the 6c agent already used
(`.claude/worktrees/phase6c-remove-law`). **If the merge step for Phase 6e finds the main
checkout on an unexpected branch, that's this pre-existing multi-agent-shared-directory issue, not
something Phase 6e did.**

TauFakeFactors/ntuple_processor were symlinked into this worktree from the main checkout's real
submodule content for the session (same one-time workaround Phase 3/4/4b/5.2 documented), and
restored to empty placeholder directories before every commit (confirmed via `git status --short`
showing no submodule-pointer changes staged in any of this phase's three commits).
