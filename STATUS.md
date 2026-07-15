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

## Phase 5.1 — Root-cause TTL/VVJ discrepancies (IN PROGRESS — checkpoint)

Status: **IN PROGRESS.** This is a checkpoint written mid-slice per an explicit
instruction to checkpoint incrementally rather than risk losing work to a context
cutoff. If you are resuming this: read this section, check `git log` on branch
`phase5.1-ttl-vvj-rootcause` for what's already committed, and check whether the
background shape-production runs mentioned below completed (they were fired off
right before this checkpoint was written and are not yet reflected in results below).

**Scope:** re-examine the TT-TTL (+3.9% Phase 2b / ~1.6% Phase 3, era-dependent) and
VV-VVJ (~26.6% low, Phase 3) discrepancies with fresh 2024 data from both frameworks,
find root cause(s), fix in TauKITFlow (not a fudge factor).

**Confirmed root cause #1 (TT-TTT/TT-TTL residual) - FIXED:** `ttbar_em_weight()` in
`config/shapes/process_selection.py` (both frameworks) applies a hardcoded, per-era
data/MC normalization scale factor to all ttbar (TTT+TTL) events, derived from an
em-channel control-region measurement. TauKITFlow's copy of this function had a
**stale** set of `ratio_em` values (comment: computed on `m_vis>100` only, no nbtag
cut - e.g. 2024: `0.926025`). smhtt_ul's *live* checkout has since been recalibrated
(`config/shapes/calculate_ttbar_weights.py`, "260602" tag, nbtag>=0 selection to
better isolate ttbar) to a **different, newer** set of values (2024: `0.945792`) -
confirmed by reading smhtt_ul's `process_selection.py` directly: the old values are
still there, commented out, immediately above the new ones, with an explicit
"old weigths ... wrong weight for 24-25" comment marking them stale. Ratio of
old/new for 2024: `0.926025/0.945792 = 0.9791` -> TauKITFlow was applying a weight
**~2.09% lower** than smhtt_ul's current reference - same direction and closely
matching magnitude as the Phase 3-reported TT-TTT (1.66% low) / TT-TTL (1.63% low)
residuals. This is a real, dated, single-number recalibration in the legacy
reference, not a code/logic difference (the `TTT_process_selection`/
`TTL_process_selection`/`TTJ_process_selection` cut expressions themselves are
byte-identical between the two frameworks for `mt`/`et`/`tt`/`em` - diffed directly,
only `mm`/`ee` branches differ, and TauKITFlow doesn't support `mm`/`ee` at all so
that's moot).

**Fix applied:** `config/shapes/process_selection.py`'s `ttbar_em_weight()` updated
to the current smhtt_ul "260602" `ratio_em` values for all 6 Run3 eras (2022preEE:
`0.827018`, 2022postEE: `0.955392`, 2023preBPix: `1.016815`, 2023postBPix:
`0.977028`, 2024: `0.945792`, 2025: `0.918900`), old values kept commented out for
provenance (same convention smhtt_ul itself uses). **Not yet numerically
re-validated end-to-end against a fresh legacy file** - see below.

**VV-VVJ investigation so far:** `VVT_process_selection`/`VVJ_process_selection`/
`VVL_process_selection` cut expressions are also byte-identical between frameworks
for the channels TauKITFlow supports (diffed directly). No `ttbar_em_weight`-style
per-process normalization factor exists for VV in either framework - `VV_process_selection`
only carries the generic `MC_base_process_selection` weights + `numberGeneratedEventsWeight`
+ `crossSectionPerEventWeight`, same on both sides. **Checked the VV sample list
specifically** (since Phase 3 flagged VVJ as a low-stat process where a single
sample's presence/absence would swing the ratio): smhtt_ul's `config/shapes/file_names.py`
`common_files_2024["VV"]` is a **20-sample list that merges diboson (WW/WZ/ZZ, 10
samples) with single-top (ST t-channel + tW, 10 samples)** under one "VV" key.
TauKITFlow's `config/samples.yaml` has these as two separate top-level background
keys, `diboson` (10 samples, exact match) and `ST` (10 samples, exact match) - but
`config/analysis.py`'s `_TFF_TO_DATASET` dict **already maps both `"diboson"` and
`"ST"` to the same ntuple_processor key `"VV"`** (line ~91-92, with an explicit
`# single-top merged into VV` comment), and `get_background_samples()` merges them
via `result.setdefault(ds_key, []).extend(...)`. So the merged 20-sample VV list is
**already identical between the two frameworks** - this is not (or not simply) a
sample-list bug. Diffed every individual sample name in both 20-sample lists:
identical set, same production tag (`RunIII2024Summer24NanoAODv15-150X`). VVJ
specifically (gen_match_2==6, i.e. the genuinely-faked-tau subset of VV) is a very
low-statistics slice of an already lower-cross-section process family, so the 26.6%
residual is plausibly dominated by MC statistical fluctuation rather than a
selection/weight bug - **not yet confirmed either way with fresh numbers**, next
step below is designed to settle this.

**In progress at checkpoint time:** launched two real, fresh background shape
productions restricted to `--process-selection ttt,ttl,ttj,vvt,vvl,vvj` and
`--control-plot-set m_vis,pt_1,pt_2` (narrowed scope to make a same-day rerun
practical) for 2024/mt against the live CROWN production:
- TauKITFlow (this worktree, `taukiktflow` conda env, with the `ttbar_em_weight` fix
  above already applied): `shapes/produce_shapes.py --era 2024 --channels mt
  --vs-jet-wp Medium --vs-ele-wp VVLoose --apply-tauid --control-plots
  --control-plot-set m_vis pt_1 pt_2 --xrootd --directory
  /store/user/sgiappic/CROWN/ntuples/htt_260602_2024-25_v5/CROWNRun
  --mt-friend-directory .../CROWNFriends/xsec/ --process-selection
  ttt,ttl,ttj,vvt,vvl,vvj --skip-systematic-variations --no-dnn-categorization
  --num-processes 8 --num-threads 8 --output-file output/2024-mt-ttvv-phase51`
- smhtt_ul (`/work/sgiappic/smhtt_ul`, LCG_106 view via `utils/setup_root.sh`, no
  conda - same house rule as previous phases): same processes/variables via
  `shapes/produce_shapes.py` directly (equivalent to `control_plots_ul.sh -m SHAPES`),
  output `output/2024-mt-ttvv-phase51-legacy.root`.

**Next steps once these complete (not yet done as of this checkpoint):**
1. Run `shapes/do_estimations.py` on both outputs if needed (probably not required
   for a pure MC bin-by-bin comparison, no QCD/FF estimation involved for TT/VV).
2. Run `plotting/compare_control_shapes.py --new-file <TauKITFlow output>
   --legacy-file <smhtt_ul output> --channel mt --selection Nominal --processes
   TT-TTT,TT-TTL,TT-TTJ,VV-VVT,VV-VVL,VV-VVJ --variables m_vis,pt_1,pt_2` and record
   the actual before/after ratios (before = using the old TauKITFlow numbers, which
   Phase 3 already measured; after = with the `ttbar_em_weight` fix).
3. If TT-TTT/TTL now agree within tolerance (3-sigma / whatever rel-diff convention
   Phase 2b/3 established) and VVJ still doesn't, chase VVJ further (statistical
   significance test: is 26.6% within VVJ's own Poisson uncertainty at this
   sample's stats? if yes, this is a statistics-limited process, not a bug, and
   should be documented as such rather than "fixed" further).
4. Write the final numbers into a proper (non-checkpoint) version of this section,
   replacing this IN PROGRESS marker.

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
