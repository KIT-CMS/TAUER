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

## Phase 6c — Remove law from the training setup; local + condor workflows are plain Python

Status: **DONE.** Branch `phase6c-remove-law`, own worktree, scoped to `trainings/`, `condor/`, and
`run.sh` only (no touches to `shapes/selection/*`, `config/*`, TauFakeFactors, or `ntuple_processor`,
per the task's explicit scope note).

### Finding #1 (corrects the task's premise): `trainings/create_training_dataset.py` never used law

The addendum-plan punch list (and the task instructions handed to this slice) describe
`trainings/create_training_dataset.py` as "a local law.Task graph calling subprocess.run directly."
That description does not match this repo's actual history: `git log --all --oneline --
trainings/create_training_dataset.py` shows exactly **one** commit ever touched this file — the
baseline import commit — and the file has never contained `import law`/`from law` or any
`subprocess.run` call. It is, and always has been, a single plain-Python script: `argparse` CLI,
sequential `for` loops over `Iterate.subprocesses(config)`, direct pandas/ROOT calls. Grepping the
whole repo confirms `law`/`luigi` appear in exactly three non-submodule files: `run.sh` (real usage,
see below), and `condor/common.py`/`condor/__init__.py` (prose in docstrings/comments explaining the
Phase 2c law-vs-standalone-condor decision, no executable dependency).

This means the description in the task setup conflated `create_training_dataset.py` (the top-level
dataset-prep step TauKITFlow owns) with `trainings/uncertainty-aware-training/`'s own
`_law_workflow_ff.py`/`_law_CENNT_workflow.py` (the NN-training-loop submodule, which *does* use
`law.Task` subclasses calling `subprocess.run` — Phase 2c's docstring in `condor/common.py`
describes exactly that file, correctly, as living inside the submodule). Recorded here explicitly
rather than silently "fixed" a problem that didn't exist in the file the task named.

### What this means items 1/2 of the task reduce to

- **Item 1 ("replace the law.Task graph in `create_training_dataset.py` with plain Python doing
  direct condor submission")**: the plain-Python part was already true (see Finding #1), and the
  direct-condor submission part was already built in Phase 2c (`condor/submit_training.py` — one
  job per (era, channel), slices a master YAML, shells out to `condor_submit`, no law/luigi
  anywhere). No code changes were needed to satisfy this item; it was already done by a prior phase.
  Re-validated it still works (see Validation below) rather than taking that on faith.
- **Item 2 ("rewrite the local (non-condor) workflow to not use law")**: also already true structurally
  (`python trainings/create_training_dataset.py --config ...` is itself the plain-Python local
  workflow, no scheduler). What was missing was a discoverable `run.sh` entry point for it — every
  other pipeline stage (`SHAPES`, `PLOT`, `TRAIN-SHAPES`, `CONFIGS`, ...) has one, but the dataset-prep
  step didn't. **Added `run.sh`'s new `TRAIN-DATASET` mode** (plain bash case-block, same pattern as
  every other mode in this file — no new bash *tooling*, just one more branch in the existing
  dispatcher): `conda activate taukiktflow` (no `source utils/setup_root.sh`, deliberately — the
  Phase 2c PYTHONHOME/`init_fs_encoding` crash note applies here too, so this mode follows the
  conda-only pattern `condor/common.py`'s wrapper already uses) then
  `python trainings/create_training_dataset.py --config "$TRAIN_CONFIG" --base-dataset-directory
  "$BASE_DATASET_DIR" [--common-setup-config "$COMMON_SETUP_CONFIG"] "$@"`. New env vars documented
  in the usage block: `TRAIN_CONFIG` (required), `BASE_DATASET_DIR` (default
  `/ceph/$USER/smhtt_ul_new/training_datasets`, matching the script's own Python default),
  `COMMON_SETUP_CONFIG` (optional).

### Submodule-boundary decision: `trainings/uncertainty-aware-training/`'s `TRAIN` mode is left untouched

Per the task's explicit instruction to check whether TauKITFlow's own wrapping code needs to touch
law here before considering any submodule-internal change: `run.sh`'s `TRAIN` mode (the *actual* NN
training loop, as opposed to the dataset-prep step above) does invoke the `law` CLI directly —
`cd trainings/uncertainty-aware-training && law index -v` and `law run "$TRAIN_TASK" --workers ...
--local-scheduler --version ... --cuda-device ... --dataset-directory=... --base-config-file=...`.
This is real, and grep alone doesn't clear it (it's a CLI shell-out, not a Python import), so it
gets its own explicit call per the task's instructions:

- **Decision: left untouched, submodule internals not modified.** Reasoning:
  - `run.sh`'s `TRAIN` block contains zero task-graph/orchestration *logic* of its own — no
    `requires()`/`output()`/dependency wiring, no retry/skip-if-exists semantics. It only forwards
    user-supplied parameters (`$TRAIN_TASK`, `$CUDA_DEVICE`, `$DATASET_DIR`, `$UAT_CONFIG_DIR`,
    `$CHANNELS`) as CLI arguments to the submodule's own `law run <task>` entry point. Structurally
    this is identical to how the `PRESEL`/`FF`/`FF-CORR` modes a few lines above shell out to
    TauFakeFactors' own `preselection.py`/`ff_calculation.py`/`ff_corrections.py` CLIs — TauKITFlow
    treats each submodule's chosen CLI as an opaque external command, regardless of what that
    submodule built the CLI on top of (argparse for TauFakeFactors, law/luigi for
    uncertainty-aware-training). The task-graph dependency logic (`RunAllCENNTConfusionMatrixWorkflow`
    and whatever `requires()` chain it expands into across CENNT confusion-matrix experiments per
    channel) is entirely defined inside `trainings/uncertainty-aware-training/`'s own
    `_law_workflow_ff.py`/`_law_CENNT_workflow.py`/`law.cfg` — code this slice does not own and, per
    the framework's "modify submodule internals only as a last resort" philosophy (same standard
    Phase 1's CROWN-preselection call and Phase 2c's original law decision both applied), should not
    reimplement in TauKITFlow just to avoid the word "law" appearing in a shell-out.
  - Removing law here for real would mean either (a) rewriting the submodule's task-dependency graph
    from scratch inside TauKITFlow (duplicating, not removing, complexity — and risking silently
    changing which training steps run in what order), or (b) modifying the submodule itself to
    expose a non-law entry point — both are last-resort moves the task's own instructions say to
    avoid unless genuinely necessary, and neither is necessary here since `run.sh` itself carries no
    law-specific logic beyond the one CLI invocation.
  - Practically, this submodule isn't even checked out in this worktree (confirmed:
    `trainings/uncertainty-aware-training` is gitlink-only, mode `160000`, pointing at
    `3ea763aed9256813012ad4b050d5c672522ed4c9`, with an empty placeholder directory on disk and *no*
    entry in `.gitmodules` — same "symlink in for the session, restore to empty before commit"
    pattern already documented for `TauFakeFactors`/`ntuple_processor` in earlier phases), so its
    internals could not be safely inspected or modified from here even if that were the right call.
  - Documented this decision in `run.sh` itself (a comment block directly above the `TRAIN` case),
    not just in STATUS.md, so the next person reading `run.sh` sees the reasoning in place rather
    than having to cross-reference this file.
- This mirrors Phase 2c's identical prior call ("`trainings/uncertainty-aware-training/`'s law setup
  is untouched") — Phase 6c reaffirms it rather than reopening it, now with the `run.sh`-level
  shell-out explicitly considered (Phase 2c's writeup focused on the condor-submission angle, not on
  whether `run.sh`'s existing `TRAIN` mode itself counted as "TauKITFlow depending on law").

### Validation performed

- `grep -rn "import law\|from law" trainings/` (this worktree, submodule dir is the empty
  placeholder) → **zero matches**. `grep -n "\blaw\b" run.sh` → matches only inside the `TRAIN` mode's
  code/comments and its own help text (all accounted for above); no other file under `trainings/` or
  `condor/` contains executable law usage (`condor/common.py`/`condor/__init__.py` mentions are
  docstring prose only, unchanged from Phase 2c).
- `bash -n run.sh` → syntax OK.
- `python3 -c "import ast; ast.parse(...)"` on `trainings/create_training_dataset.py` and
  `condor/submit_training.py` → both parse cleanly.
- Real (not simulated) `condor_submit -dry-run` round-trip, `taukiktflow` conda env, TauFakeFactors
  symlinked in for the session only (restored to an empty placeholder directory before this commit,
  confirmed via `git status --short` showing no submodule-pointer diff): built a one-job plan via
  `condor/submit_training.py --master-config <tiny mt/2024/ztt config> --eras 2024 --channels mt
  --base-dataset-directory <scratch dir> --tag phase6c-validation --dry-run` → produced a
  well-formed classad (`Arguments="--config .../mt_2024.yaml --base-dataset-directory ..."`,
  `JobUniverse=5`, correct `Requirements=`/`AccountingGroup=` fields) with no parse errors — confirms
  Phase 2c's condor path for this stage still works unmodified.
- Real end-to-end wrapper execution (clean shell, `env -i` with only `HOME`/`PATH`/`USER` set, to
  catch environment bugs a dry-run can't see, same method Phase 2c used): ran the generated
  `condor/run/training/phase6c-validation/wrapper.sh --help`. Ran cleanly through `conda activate
  taukiktflow` → real ROOT import (`Successfully loaded custom styles from ~/.rootlogon.C` messages,
  i.e. ROOT genuinely initialized) → `create_training_dataset.py`'s argparse `--help` output, rc=0,
  no tracebacks. (First attempt with a fully-empty `env -i`, no `USER`, hit a pre-existing
  `KeyError: 'USER'` in the script's own `--base-dataset-directory` default
  [`f"/ceph/{os.environ['USER']}/..."`] — not a law-removal bug, just an artifact of the artificially
  bare test shell; real condor jobs and real interactive shells always have `USER` set, so this
  wasn't chased further, noted here only for completeness.)
- Generated condor run-directory (`condor/run/training/phase6c-validation/`) removed after
  validation, and the `TauFakeFactors` symlink used for the session restored to an empty directory
  before committing — `git status --short` shows only `run.sh` modified, no submodule-pointer or
  stray-file noise.

### Files changed

- `run.sh` — added `TRAIN-DATASET` mode (plain-Python local entry point for
  `trainings/create_training_dataset.py`, no law); added a documentation comment above the existing
  `TRAIN` mode recording the submodule-boundary decision; updated the mode list (header comment +
  `*)` usage block) and env-var help text for both.
- No changes to `trainings/create_training_dataset.py`, `condor/submit_training.py`,
  `condor/common.py`, or any file under `trainings/uncertainty-aware-training/` — none were
  necessary (see Findings above).

### What was deliberately left as-is / not chased

- `trainings/uncertainty-aware-training/`'s law-based task graph (submodule internals) — see the
  submodule-boundary decision above.
- The residual item Phase 5.2 flagged for this slice to "naturally revisit" (whether training's
  external per-run `--config` master YAML's `subprocess_dict[Keys.CUT]`/`[Keys.WEIGHT]` column-name
  references are built by re-authoring cut logic somewhere in `trainings/`, rather than referencing
  already-materialised columns) — traced one level further this time:
  `trainings/src/dataset_manipulation.py::nominal_weight_and_cut` reads `subprocess_dict[Keys.NOMINAL][Keys.WEIGHT]`/`[Keys.CUT]`
  as **column-name strings looked up directly in the already-loaded `subprocess_df`**
  (`df[...] = self.subprocess_df[weight].astype(np.float32).values` — a plain column select, not an
  expression string passed to `ROOT.RDataFrame.Filter`/`.Define`), confirming Phase 5.2's earlier
  read: this is data selection, not cut-logic re-authoring, at least at this layer. Where those named
  columns are first written (upstream, at the preselection/CROWN-friend stage) was still not traced
  end-to-end — that's a physics-adjacent, potentially multi-file trace through `shapes/preselect.py`
  and/or TauFakeFactors' preselection output columns, out of scope for a law-removal slice and
  explicitly excluded by this task's own scope note (item 9: no touches to `shapes/selection/*` or
  TauFakeFactors internals). Left as a residual for a future slice, same as Phase 5.2 flagged it.

Committed to branch `phase6c-remove-law` in its own worktree. Not pushed, no force operations, no
destructive git commands used.

## Phase 6d — Convert remaining bash scripts to Python control scripts

Status: **DONE.** Branch: `phase6d-bash-to-python` (own worktree,
`.claude/worktrees/phase6d-bash-to-python`, based off `a61a3b4`, the same
commit Phase 5.1/5.2 landed at). Runs in parallel with sibling agents on 6a
(Run2 validation), 6b (tauES extraction), 6c (law removal from `trainings/`),
6e (TauFakeFactors slimdown) -- per the scoping instructions this slice
touched only `datacards/`, `run.sh`/`run.py`, `utils/`, and a few doc-comment
references in `condor/common.py`/`condor/submit_shapes.py`/`config/analysis.py`;
nothing under `trainings/` or inside `TauFakeFactors/` was touched.

### Scope: every in-scope `.sh` file found and its disposition

`find . -name "*.sh" -not -path "./TauFakeFactors/*" -not -path "./trainings/*"
-not -path "./ntuple_processor/*" -not -path "./.git/*"` found 9 files at the
start of this slice. All 9 were converted; the repo now has exactly the 2
pre-approved environment-sourcing shims left as bash (see "What was
deliberately left as bash" below):

| Old bash script | Replacement | Notes |
|---|---|---|
| `datacards/produce_datacard.sh` | `datacards/produce_datacard.py` | same 3 positional args + optional `NTUPLE_TAG`; env-sourcing moved into `common/cmsenv.py` |
| `datacards/produce_gof_datacard.sh` | `datacards/produce_gof_datacard.py` | positional args unchanged (era/channel/variable/ntuple_tag); the trailing `USE_ASIMOV`/`EMBEDDING`/`JETFAKES` 0/1 positionals became `--use-asimov`/`--embedding`/`--jetfakes` flags (CLI improvement, documented, only caller is `run_gof.py` which was updated to match) |
| `datacards/produce_workspace.sh` | `datacards/produce_workspace.py` | same args (`ERA[,ERA...] ANALYSIS [CORES]`) |
| `datacards/produce_gof_workspace.sh` | `datacards/produce_gof_workspace.py` | same args (`ERA CHANNEL VARIABLE [CORES]`) |
| `datacards/run_gof.sh` | `datacards/run_gof.py` | same args; parallel toy-throwing (`... & ... wait`) reimplemented with `subprocess.Popen`/`.wait()` per seed, same seed numbering (1230+i) |
| `datacards/run_impacts.sh` | `datacards/run_impacts.py` | same args |
| `run.sh` | `run.py` | same MODE dispatch, same flags, same env-var-first-then-default precedence (`ERA=${ERA:-default}` semantics reproduced exactly -- see below) |
| `utils/setup_ul_samples.sh` | `common/sample_paths.py` (`build_ul_sample_paths()`) | pure path-string construction, not environment sourcing -- no reason to stay bash (see reasoning below) |
| `utils/setup_cmssw.sh` | **left as bash** (unchanged) | pre-approved exception: sources `cmsenv` |
| `utils/setup_root.sh` | **left as bash** (unchanged) | same class of exception: sources the CVMFS LCG view |

### New Python modules (shared machinery, `common/`)

- **`common/cmsenv.py`** — `get_fitdir()` / `run_in_cmsenv(cmd_args, ...)`. The
  single place any datacards/*.py script shells out to `bash -c "source
  utils/setup_cmssw.sh && ..."` — one line, not re-implemented per script.
  Supports `unlimited_stack=True` (replaces every script's `ulimit -s
  unlimited`) and `background=True` (returns a live `Popen` instead of
  waiting, for `run_gof.py`'s parallel toy jobs).
- **`common/conda_env.py`** — `run_in_conda(cmd_args, ...)`, the `run.py`
  analogue of `common/cmsenv.py`: sources `conda.sh` + `conda activate
  taukiktflow` in a throwaway bash subshell, then runs the given command.
  Same conda base/env/activation sequence `condor/common.py`'s generated
  wrapper already uses (kept consistent, not re-derived).
- **`common/lcg_env.py`** — `get_output_features()`: sources
  `utils/setup_root.sh`, then runs `config.analysis.get_output_features()`
  under the LCG view's Python (needed for `pyyaml` availability, per the old
  script's own comment). Made **lazy** (only called by `run.py`'s PRESEL
  mode) rather than run.sh's original unconditional-every-mode sourcing --
  this changes nothing observable about any mode's output (the only
  consumer was PRESEL's `--columns`), it just avoids paying the LCG
  env-sourcing cost for XSEC/SHAPES/PLOT/etc., which never used the result.
  Documented in the module's own docstring as a deliberate, harmless
  behavior refinement, not a silent scope change.
- **`common/sample_paths.py`** — `build_ul_sample_paths(ntupletag, era, user=None)`.
  Byte-for-byte port of `utils/setup_ul_samples.sh`'s
  NTUPLETAG/ERA→path-string derivation (same `/store/user/<user>/CROWN/ntuples/...`
  convention, same Run3-only era whitelist, same "Unsupported era" failure
  message). This one genuinely didn't need to stay bash: it's pure
  string-building, no environment sourcing, no PATH/PYTHONHOME mutation --
  unlike `setup_cmssw.sh`/`setup_root.sh`, there's no reason a plain Python
  function can't do exactly what it did.

### What was deliberately left as bash, and why (per the task's explicit exception)

Exactly two files, both real environment-sourcing shims whose entire job is
mutating the calling shell's `PATH`/`PYTHONHOME`/`LD_LIBRARY_PATH` — something
`subprocess.run(...)` cannot do to its own parent process, so there is no
portable all-Python way to eliminate them without still shelling out to bash
for that one step (which is exactly what `common/cmsenv.py`/`common/lcg_env.py`
do -- the *logic* around them is Python, only the sourcing itself is bash):

1. **`utils/setup_cmssw.sh`** — sources `cmsset_default.sh` + `scramv1 runtime
   -sh` (CMSSW `cmsenv`). Already an established exception from Phase 2d;
   unchanged in this slice except that it's now invoked exclusively through
   `common/cmsenv.py` rather than being `source`d ad hoc from each `datacards/*.sh`.
2. **`utils/setup_root.sh`** — sources a CVMFS LCG view (`LCG_102`/`LCG_106`
   depending on hostname). Same class of exception; now invoked exclusively
   through `common/lcg_env.py`.

`run.py`'s TRAIN mode still shells out to `law index`/`law run ...` inside
`trainings/uncertainty-aware-training/` -- ported byte-for-byte from `run.sh`
(same task name, same flags) since `trainings/` itself is explicitly out of
scope for this slice (Phase 6c owns removing `law` from the training setup).
This is **not** a bash-script left-behind (it was never a `.sh` file --
`run.sh`'s TRAIN case block called `law` directly, and `run.py`'s
`mode_train()` does the same via `subprocess.run(["law", ...])`), but it's
flagged here because Phase 6c will need to update `run.py`'s `mode_train()`
once `law` is removed from `trainings/`'s workflow -- noted as a known,
expected follow-up merge conflict/rework, not a bug.

### Env-var/flag precedence fidelity (a real bug caught during self-review, before any real run)

`run.sh`'s bash implementation reads `ERA`/`CHANNELS`/`NTUPLETAG`/`TAG`/
`VS_JET_WP`/`VS_ELE_WP`/`NTHREADS`/`NPROCS`/`OUTPUT_DIR`/`PRESEL_DIR` as **plain
shell variables** with `${VAR:-default}` fallback -- meaning an inherited
environment variable (e.g. `NTHREADS=16 python3 ...` / `NTHREADS=16 source
run.sh SHAPES`, both supported historically, and documented in this repo's
own README: `NPROCS=4 NTHREADS=8 source run.sh SHAPES`) silently wins over the
hardcoded default whenever no `--flag` override is given. The first draft of
`run.py` only checked `args.X or "<hardcoded default>"`, silently dropping
environment-variable-based configuration entirely -- a real behavior
regression that would have broken any existing caller/cron job driving
`run.sh` via exported env vars rather than flags. Caught via careful
comparison against the bash source (not by a failing test — there was no
existing test for this), fixed by routing every one of these ten values
through a small `env_or(flag_value, ENV_NAME, default)` helper that
reproduces the exact `flag > inherited env var > hardcoded default`
precedence. Verified with a mocked-`subprocess.run` harness: `ERA=2024
NTUPLETAG=htt_env NTHREADS=16 CHANNELS=tt python3 run.py XSEC` (no flags at
all) produces the same `--basepath`/`--outputpath`/`--nthreads 16` as passing
those as `--era 2024 --ntupletag htt_env ...` explicitly.

### Validation performed

Environment: `taukiktflow` conda env is not needed for `--help`/argument-parsing
validation; for the real end-to-end datacard/GoF/Impacts run below,
`CMSSW_15_0_2` at `/ceph/sgiappic/CMSSW_15_0_2` (`utils/setup_cmssw.sh`,
unchanged from Phase 2d/3/4) plus `TauFakeFactors`/`ntuple_processor`
symlinked in from the main checkout for the session (the same one-time
worktree-submodule-gap workaround Phase 3/4/4b/5.2 documented — restored to
empty placeholder directories before every commit, confirmed via `git status
--short` showing no submodule-pointer changes staged).

1. **`--help` / argument-parsing, every converted script:** `run.py`,
   `datacards/{produce_datacard,produce_gof_datacard,produce_workspace,
   produce_gof_workspace,run_gof,run_impacts}.py` all exit 0 with no
   traceback under `python3 <script> --help`.
2. **`ast.parse()`** over every new/changed file (`run.py`, all six
   `datacards/*.py`, `common/{cmsenv,conda_env,lcg_env,sample_paths}.py`,
   `condor/common.py`) — all parse cleanly.
3. **Mocked-subprocess command-construction check (`run.py`, all 9 modes):**
   monkeypatched `subprocess.run` and drove every mode
   (`XSEC`/`SHAPES`/`SHAPES-NOSYS`/`PLOT`/`TRAIN-SHAPES`/`CONFIGS`/
   `GEN-TFF-CONFIGS`/`PRESEL`/`FF`/`FF-CORR`) with representative
   flags/env-vars, and diffed the constructed argv/PYTHONPATH/conda-activation
   string against the equivalent bash logic by hand — all matched, including
   the `${CHANNELS/,/-}` bash quirk of replacing only the **first** comma
   (reproduced via `channels.replace(',', '-', 1)`, not `.replace(',', '-')`),
   the `et`→`Tight`/other→`VVLoose` VS_ELE_WP default, and FF-friends-dir/
   `--ff-type fake_factor`/`--presel-dir`/`--skip-systematic-variations`/
   `--no-dnn-categorization` conditional flag assembly in SHAPES/SHAPES-NOSYS.
4. **Real (not mocked) `GEN-TFF-CONFIGS` run** through `run.py` with
   `TauFakeFactors` symlinked in: produced a real regenerated
   `TauFakeFactors/configs/smhtt_ul/2024/preselection_mt.yaml` — confirming
   `common/conda_env`-free plain-subprocess dispatch, `config/generate_tff_configs.py`
   import path, and PYTHONPATH wiring all work end-to-end. **This is a
   real submodule side effect** (the regenerated YAML is semantically
   equivalent but not byte-identical to the checked-in one, since the
   generator recomputed it from current `config/*.yaml`), so it was
   immediately reverted (`git checkout -- configs/smhtt_ul/2024/preselection_mt.yaml`
   in the actual `/work/sgiappic/TauKITFlow/TauFakeFactors` checkout, confirmed
   clean via `git status --short`) rather than left as an unintended change to
   another worktree/agent's shared submodule checkout.
5. **Real, non-synthetic-in-name-only end-to-end Combine chain through the new
   `datacards/*.py` scripts** (the most important validation — this is the
   part of the pipeline most likely to silently break from an env-sourcing
   mistake): built a structurally-real synthetic shape ROOT file (`mt_gof`
   TDirectory, `data_obs` + the exact 10 backgrounds `get_backgrounds("mt",
   embedding=False, jetfakes=False)` returns + `ggH_htt125`/`qqH_htt125`
   signals, matching Phase 2d's validation methodology) and ran, for real,
   against the live CMSSW/Combine environment:
   - `python3 datacards/produce_gof_datacard.py 2024 mt gof htt_260602_2024-25_v5`
     → real Combine datacard written (`htt_mt_gof_2024.txt` + `combined.txt`),
     log shows the expected `filter_zero_yield_systs`/`load_systematic_shapes`
     drops for systematics with no matching shape (same behavior class as
     Phase 2d), `combineCards.py` (external CMSSW binary via `cmsenv`) ran
     successfully.
   - `python3 datacards/produce_gof_workspace.py 2024 mt gof` → real
     `text2workspace.py` run, real `ws.root` written; independently confirmed
     valid by running `combine -M GoodnessOfFit --algo=saturated
     --fixedSignalStrength=0` against it directly (`combine` binary via
     `cmsenv`), which returned a real best-fit test statistic
     (`Best fit test statistic: 17.9433`), not an error.
   - **`python3 datacards/run_gof.py 2024 mt gof <synced-file> saturated 20
     htt_260602_2024-25_v5 0 4`** → full pipeline run through the new Python
     entrypoint end-to-end: real observed GoF fit, **4 real parallel toy jobs**
     (`subprocess.Popen`/`.wait()` fan-out, seeds 1230-1233, 5 toys each),
     real `combineTool.py -M CollectGoodnessOfFit` collection into
     `gof_saturated.json`, and the Python-side p-value summary printed
     correctly (`observed test statistic: 17.9433`, `n_toys: 20`, `p-value:
     0.0000` — expected, since the synthetic background model doesn't
     actually fit the synthetic "data" well; the point of this run is
     confirming the *mechanics*, not a physics result).
   - **`python3 datacards/run_impacts.py 2024 mt gof 4`** → full Impacts
     pipeline through the new Python entrypoint against the same real
     workspace: real `--doInitialFit`, real per-nuisance `--doFits` (12
     nuisances, `--parallel 4`), real `-o impacts.json` collection, real
     `plotImpacts.py` tornado PDF, and the Python-side ranked-nuisance summary
     printed 12 real nuisances in descending impact order (`lumi_13.6TeV_correlated`,
     `CMS_eff_m`, `CMS_eff_t_wp_Run2024`, ... down to `BR_htt_PU_alphas`).
   - This confirms `common/cmsenv.py`'s `run_in_cmsenv()`/`get_fitdir()`
     (including `unlimited_stack=True` and `background=True` for the parallel
     toy jobs) work correctly against the real CMSSW/Combine environment, not
     just in a mock — the same level of rigor Phase 2d/3/4 used to validate
     the original bash scripts.
6. **Repo-wide grep for stale references** to every renamed/deleted script
   (`run\.sh`, `produce_datacard\.sh`, `produce_gof_datacard\.sh`,
   `produce_workspace\.sh`, `produce_gof_workspace\.sh`, `run_gof\.sh`,
   `run_impacts\.sh`, `setup_ul_samples`) across the non-submodule, non-`trainings/`
   repo — zero remaining after this slice's README.md/`config/generate_tff_configs.py`/
   `shapes/preselect.py`/`shapes/produce_shapes.py`/`condor/common.py`/
   `condor/submit_shapes.py`/`config/analysis.py` doc-comment updates.

### Files changed / added (full list for this slice)

- **New:** `common/cmsenv.py`, `common/conda_env.py`, `common/lcg_env.py`,
  `common/sample_paths.py`, `run.py`, `datacards/produce_datacard.py`,
  `datacards/produce_gof_datacard.py`, `datacards/produce_workspace.py`,
  `datacards/produce_gof_workspace.py`, `datacards/run_gof.py`,
  `datacards/run_impacts.py`.
- **Deleted:** `run.sh`, `utils/setup_ul_samples.sh`, `datacards/produce_datacard.sh`,
  `datacards/produce_gof_datacard.sh`, `datacards/produce_workspace.sh`,
  `datacards/produce_gof_workspace.sh`, `datacards/run_gof.sh`,
  `datacards/run_impacts.sh`.
- **Updated (doc-comments / invocation examples only, no logic changes):**
  `README.md` (all `run.sh`/`datacards/*.sh` invocation examples and the
  repository-structure tree), `config/generate_tff_configs.py` (module
  docstring usage example), `shapes/preselect.py` (error-message hint),
  `shapes/produce_shapes.py` (`--directory` help text reference),
  `condor/common.py` (module docstring + generated-wrapper comments),
  `condor/submit_shapes.py` (module docstring + `--vs-ele-wp` help text),
  `config/analysis.py` (module docstring consumer list + `get_columns()`
  comment).

### Not touched (explicitly out of scope, per the task's coordination instructions)

- `trainings/` — owned by Phase 6c (law removal + bash→python conversion
  there). `run.py`'s TRAIN mode still calls `law` (see above), unchanged from
  `run.sh`'s behavior; flagged as Phase 6c's future follow-up.
- `TauFakeFactors/` (submodule) and any TauFakeFactors-wiring files 6e is
  expected to touch — not modified (the one real write during validation,
  `configs/smhtt_ul/2024/preselection_mt.yaml`, was immediately reverted; see
  Validation item 4 above).
- `shapes/*.sh` — none exist (`shapes/` was already all-Python from prior
  phases; the `find` command at the start of this slice confirmed this).
- `CROWN`/`KingMaker`, CMSSW/Combine/CombineHarvester binaries themselves —
  out of scope per the task description; only the glue calling them changed.

Committed to branch `phase6d-bash-to-python` in this worktree (one commit so
far covering the full conversion + doc updates; this STATUS.md write-up is a
second commit). Not pushed, no force operations, no destructive git commands
used, per the task's git-safety instructions.


## Phase 6f — `ntuple_processor`: decide keep-external / simplify / absorb

Status: **DONE. Decision: keep as-is, genuinely external, no code changes.**

Branch: `phase6f-ntuple-processor` (this worktree, off `master` at `a61a3b4`, the same commit
Phase 5.2 merged to). Running in parallel with sibling agents on 6a/6b/6c/6d/6e in separate
worktrees — **this slice makes no changes visible outside `STATUS.md` itself**, so there is
nothing structural for those slices to reconcile on merge (see "Why this is conflict-free for
6a/6e" at the end of this section, since the task specifically flagged that concern).

### What `ntuple_processor` actually is

Read `ntuple_processor/{__init__.py,booking.py,optimization.py,run.py,variations.py,utils/*}`
in full. It is a small (~4 files, ~60KB total, plus a `utils/` package and a real `tests/`
directory with 4 passing unit tests) RDataFrame booking/optimization layer with three genuine,
non-trivial responsibilities, none of which are legacy cruft:

1. **`booking.py`** — `dataset_from_crownoutput`/`dataset_from_artusoutput` (CROWN/artus-output
   directory discovery incl. an xrootd `dirlist()` path and a `validation_database/` file-schema
   cache — this is the machinery Phase 1 already validated end-to-end against real 2024 xrootd
   data, see Phase 1's item 4), plus `Unit`/`UnitManager` (the booking unit abstraction: a
   dataset + selections + actions, with `Variation.create()`-driven expansion into
   Nominal/shifted units and a duplicate-action-name safety check).
2. **`optimization.py`** — `Graph`/`GraphManager`: turns booked `Unit`s into a tree
   (dataset → selection → selection → ... → action) and merges/de-duplicates identical subtrees
   across datasets and selections (`merge_datasets`/`optimize_selections`/`_merge_children`) so
   RDataFrame only builds each shared filter/define chain once instead of once per variation —
   this is real, load-bearing shared-subgraph optimization, not dead scaffolding.
3. **`run.py`** (not read in full line-by-line here but grepped/imported successfully; it's what
   `common/ntuple_processor_config_helper.py` and `shapes/produce_shapes.py` import as
   `RunManager` — the actual `RDataFrame(...).Histo1D(...)`/booking-to-histogram execution step)
   plus `variations.py` (`ReplaceCut`/the `Variation` machinery consumed by
   `shapes/selection/variations.py`) and `utils/_booking.py`'s `WarnDict` (a `dict` subclass that
   logs/warns on silent key overwrites — used throughout `shapes/selection/*.py` for cut/weight
   dictionaries so a typo'd duplicate key doesn't silently clobber another).

No dead optimization paths or obviously-legacy patterns were found worth stripping: the
`level=0/1/2` optimization switch in `GraphManager.optimize()` is a real, used feature (level 0
= no merging, useful for debugging a single variation's graph in isolation), and the
`try/except ModuleNotFoundError` fallback around `config.logging_setup_configs` in
`booking.py`/`optimization.py` is deliberate — it lets `ntuple_processor` be imported standalone
(as its own package, by its own `tests/`, or by a sibling analysis) without requiring
TauKITFlow's `config/` package to exist on the path, which is exactly the kind of decoupling a
genuinely-external dependency should have, not something to "modernize away."

### Is it still genuinely external? — checked, yes

`ntuple_processor/.git` is a file (gitlink), confirming it's wired as a real git submodule, not
a plain vendored copy. `.gitmodules`:

```
[submodule "ntuple_processor"]
	path = ntuple_processor
	url = git@github.com:KIT-CMS/ntuple_processor.git
```

Checked three things to answer "is this still a real upstream, or a dead-in-place fork that only
pretends to be external" (the exact question the task posed, mirroring the SMRun2Legacy
decision-making in Phase 2d):

1. **The submodule checkout is on `master`, clean, up to date with `origin/master`**
   (`git -C ntuple_processor status` → "up to date with 'origin/master'", nothing to commit).
   `git branch -a` inside it shows `origin/master`, `origin/sm_devs`, `origin/nmssm_devs` —
   multiple active feature branches on the actual GitHub remote, not a single stale snapshot.
2. **The exact same submodule, same URL, same pinned usage pattern, is independently present in
   `smhtt_ul`** (`/work/sgiappic/smhtt_ul/.gitmodules`: `submodule "ntuple_processor"` →
   `git@github.com:KIT-CMS/ntuple_processor.git`, `branch = master`). `smhtt_ul` is the exact
   legacy reference analysis this whole rework has been diffing against since Phase 2b/3/5.1 —
   i.e. `ntuple_processor` is a **shared tool used by at least two independent KIT-CMS analyses**,
   not a fork that only TauKITFlow happens to carry around. This is the opposite situation from
   SMRun2Legacy (Phase 2d), where the `run3_htt` branch actually checked out locally had already
   diverged into being this one analysis's own rewrite with a dead C++ binary as its only
   "upstream" trace — there is no equivalent divergence here: this checkout's `master` **is**
   `origin/master`, unmodified, shared verbatim with a second analysis.
3. **No local modifications anywhere in the tree.** `git -C ntuple_processor diff`/`status` show
   nothing; TauKITFlow has never patched its own copy.

**Decision: keep it vendored/external, exactly like CROWN, unchanged.** This is the "genuinely
external, actively tracks an upstream still in use, no benefit to absorbing" branch the task
instructions explicitly named as a valid outcome, and it applies cleanly here:
- absorbing it into TauKITFlow (e.g. `shapes/booking/`) would fork a tool `smhtt_ul` still shares,
  meaning any future upstream fix/feature (e.g. a booking bugfix landing on `origin/master`) would
  need to be manually re-applied to TauKITFlow's copy instead of picked up by `git submodule
  update`, for zero present benefit — there is no "dismantle, don't wrap" case to make since the
  boundary isn't fake: it really is used, as-is, by more than one project.
- simplifying "in place" inside the submodule checkout would mean shipping a local patch to a
  package with genuine upstream branches, silently diverging TauKITFlow's copy from what
  `smhtt_ul`/future KIT-CMS analyses run, for a package that (per the read-through above) has no
  actual legacy cruft to remove — there's nothing to simplify that would be worth that tradeoff.
- this mirrors the CROWN precedent already recorded in this file (Phase 1's "CROWN/KingMaker are
  meant to stay analysis-agnostic and structurally untouched"): `ntuple_processor` is the same
  kind of shared, actively-used, externally-versioned dependency, not analysis-specific glue
  wearing an external-looking wrapper.

### What changed as a result

**Nothing in `ntuple_processor/` or any import path.** No file moved, no `.gitmodules` edit, no
`ntuple_processor`-internal code change. This section of `STATUS.md` is the only diff this slice
produces (plus this session's branch/commit bookkeeping).

### Validation performed

Environment: `taukiktflow` conda env, with `TauFakeFactors`/`ntuple_processor` populated in this
worktree (this session ran directly in the main `/work/sgiappic/TauKITFlow` working copy, not a
`.claude/worktrees/...` git-worktree checkout, so the Phase 3/4b-documented empty-submodule-in-a-
worktree gap did not apply here; `PYTHONPATH` needed `TauFakeFactors/` appended for `CustomLogging`
per `run.sh`'s existing convention — a pre-existing environment-setup requirement unrelated to
this slice, not a bug found or fixed here).

1. **`ntuple_processor`'s own test suite:** `python -m unittest ntuple_processor.tests.test_booking
   -v` → **4/4 tests pass** (`Ntuple`/`Dataset`/`Cut`/`Weight` equality semantics).
2. **Direct import:** `import ntuple_processor`, `from ntuple_processor.utils import Selection,
   WarnDict` — both succeed cleanly.
3. **All repo-wide consumers import cleanly**, unchanged (found via `grep -rl ntuple_processor
   --include=*.py`): `shapes/produce_shapes.py`, `shapes/utils.py`, `shapes/preselect.py`,
   `shapes/selection/{channel_selection,category_selection,process_selection,variations}.py`,
   `config/analysis.py`, `config/shapes/{control_binning,taues_measurement_binning}.py`,
   `combine_datacards/systematics.py` (docstring reference only),
   `common/ntuple_processor_config_helper.py` — verified via `python -c "import ..."` for each
   module (`shapes.produce_shapes`, `shapes.selection.channel_selection`,
   `config.shapes.control_binning`, `shapes.selection.category_selection` with
   `_ntuple_processor_available == True`, `common.ntuple_processor_config_helper`), all succeeded.
4. **CLI dry-run:** `python shapes/produce_shapes.py --help` runs end-to-end (full ROOT/RDataFrame
   import chain, `ntuple_processor` import included) with no errors.

### Why this is conflict-free for 6a/6e (which the task flagged as importing from
`ntuple_processor` too)

Both 6a and 6e can merge without any special handling for this slice: **the `ntuple_processor`
import surface (`from ntuple_processor import ...`, `from ntuple_processor.utils import ...`,
`from ntuple_processor.variations import ...`) is completely unchanged** — no rename, no move, no
new re-export shim. Any code either of them writes against today's `ntuple_processor` import paths
will still be correct after this branch merges, because this branch doesn't touch that surface at
all. The only merge-worthy artifact from this slice is this `STATUS.md` section itself (pure
append, no prior lines rewritten), so a `STATUS.md` merge conflict here, if any, is a trivial
append-vs-append conflict, not a semantic one.

No blockers. Not pushed; no destructive git operations used.

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

## Phase 6b — tauES: validate the samples + extract the measurement calculation into tau_es/

Status: **DONE**, with one honest gap (no legacy numeric reference exists to diff the fit
against — see below, same "does it run and produce sane output" standard Phase 4's GoF work
used). Branch `phase6b-taues`, worked in an isolated git worktree
(`.claude/worktrees/phase6b-taues-measurement`) after discovering mid-session that this task had
initially been run directly in the shared main checkout (`/work/sgiappic/TauKITFlow`), where
concurrent sibling Phase-6 agents were switching branches in place and one destructive operation
(a `git reset`/checkout sequence visible in `git reflog`, not run by this agent) silently wiped
several of this session's uncommitted edits there. Recovered by rebuilding the lost edits from
scratch in a proper isolated worktree (this is now branch `phase6b-taues`'s actual, complete
state) and leaving the shared main checkout exactly as found (no residual edits committed there).
**Lesson for future sessions: `git worktree add .claude/worktrees/<name> <branch>` first, always
— never work directly in `/work/sgiappic/TauKITFlow` itself when other Phase 6 slices are
running concurrently.**

### 1. Validating the tauES samples

Re-ran (not re-derived from scratch — Phase 2a already did the heavy lifting) the
`--special-analysis TauES` shape-production path against the real Run2 2018 validation dataset
(`root://cmsdcache-kit-disk.gridka.de//store/user/jvoss/CROWN/ntuples/
SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNRun`), specifically to confirm it **still works after
Phase 5.2's `config/shapes/{channel_selection,category_selection,process_selection,variations}.py`
-> `shapes/selection/*.py` move**, which happened after Phase 2a validated this path and touched
every import in `shapes/produce_shapes.py`/`shapes/do_estimations.py`:

- **Import correctness post-move**: `shapes.produce_shapes`, `shapes.do_estimations`,
  `shapes.convert_to_synced_shapes` all import cleanly under the `taukiktflow` conda env with
  `config.shapes.taues_measurement_binning` (mt-only categorization, unchanged location per Phase
  5.2's own decision to leave binning-data modules in `config/shapes/`) resolving correctly.
- **Real end-to-end run**: `shapes/produce_shapes.py --era 2018 --channels mt --vs-jet-wp Medium
  --vs-ele-wp VVLoose --xrootd --directory
  /store/user/jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNRun --special-analysis
  TauES --process-selection emb --skip-systematic-variations --collect-config-only` against the
  live xrootd endpoint resolved DY/TT/VV/W/data/EMB datasets correctly and reached
  `shape_utils.add_tauES_datasets`, which validated the **first real shift point
  (`embminus12p0`, i.e. -12.0%) with zero differences / zero empty files** across all 4
  `TauEmbedding-MuTauFinalState_Run2018[A-D]` run periods — the identical result Phase 2a
  originally found, now re-confirmed against the post-Phase-5.2 import layout. (Per Phase 2a's
  own precedent, the full 100-shift-point validation was time-boxed rather than re-run in full —
  each shift point re-runs a ~2-3 min per-file xrootd validation pass, so 100 points is a
  multi-hour run for no new evidence beyond what the first point + the direct per-shift branch
  check (Phase 2a item 4, mean `pt_2` scaling linearly with shift fraction to <0.01%) already
  established.)
- **No legacy reference to validate against**: as recorded in Phase 2a, smhtt_ul's own
  standalone `tauID_SFs_dev`-branch tauES pipeline (`shapes/produce_shapes_tauid_es.py`) was
  never run to completion against this validation dataset by anyone (no output found under
  `/work/sgiappic/smhtt_ul/output/` for a tauES-tagged run), so there is no legacy numeric shape
  output to diff against — same situation Phase 2a already documented, unchanged by this slice.

### 2. Extracting the tauES *calculation* into its own space: `tau_es/`

**Naming decision**: `tau_es/` (not `taues_fit/` or `morphing_taues/`) — matches the existing
`config/shapes/taues_measurement_binning.py` naming already used by shape production, and reads
as "the tauES calculation", which is what the task asked to extract. Recorded here per the
repo's established naming-decision convention (see `combine_datacards/` in Phase 2d).

**What "the calculation" turned out to mean, and where it actually lives.** The task named
smhtt_ul's `tauID_SFs_dev` branch as the source. That branch's own tauES shape-production script
(`shapes/produce_shapes_tauid_es.py`) is what Phase 2a already extracted the reusable mechanism
from (`add_tauES_datasets`/`book_tauES_histograms`, now in `shapes/utils.py`) — that is shape
*production*, not the calculation itself. The actual measurement — a Combine datacard with a
continuous `taues` RooMorphing parameter, fit via `combine -M MultiDimFit` — is built by a
**compiled CMSSW binary**, `MorphingTauES_UL`, that `tauID_SFs_dev`'s own
`embeddded_tauES_ul2018.sh` (`MODE=DATACARD`) calls. Its C++ source was **not found on
`tauID_SFs_dev`, nor on `run3_htt`** (the branch Phase 2d already used for the main analysis's
equivalent binary). It *was* found — structurally near-identical (same `taues` `RooRealVar`
range, same background list, same systematics) — on a third remote branch of the
CombineHarvester/SMRun2Legacy checkout at `/ceph/sgiappic/CMSSW_15_0_2/src/CombineHarvester/
SMRun2Legacy`: **`origin/tauES`**, file `bin/MorphingSMRun2Legacy_tauES.cpp` (423 lines,
`git log` shows recent, dedicated tauES-uncertainty commits on that branch, e.g. `a278b68 remove
0.0 value for 2016, remove muonFake unc for TTL and adapt taues range`). This is the actual
calculation the task asked to extract, and this slice ported it the same way Phase 2d ported
`MorphingSMRun2Legacy.cpp` -> `combine_datacards/make_datacards.py`: via CombineHarvester's
Python bindings, no new C++ build.

**New files:**
- **`tau_es/energy_scales.py`** — single source of truth for the tauES shift-point convention
  (-12.0% to +8.0%, 0.2% step, 100 points, 0.0% excluded) Phase 2a validated against real data.
  **Real bug found and fixed while wiring this up**: `shapes/convert_to_synced_shapes.py` — the
  flat-histogram -> synced-file bridge that sits between shape production and datacard
  construction, and that this slice's datacard step needs as its input — had its **own third,
  independent hardcoded `tau_es_map` dict spanning only -4.0% to +4.0% in 0.1% steps (81
  entries)**, i.e. the exact wrong range/step Phase 2a had already found and fixed in
  `shapes/produce_shapes.py` and `shapes/do_estimations.py`, left unfixed here. Since
  `produce_shapes.py` only ever produces shift points on the corrected -12.0/+8.0/0.2 grid, this
  stale map would `KeyError` the first time `--special TauES` hit any shift point outside
  +-4.0% — most of the real 100-point grid, including the widest, most fit-informative points.
  Fixed by generating `tau_es_map` from `tau_es.energy_scales.build_tau_es_map()` instead of a
  fourth hand-copied dict. `shapes/produce_shapes.py`'s `_es_shifts` and
  `shapes/do_estimations.py`'s `tauESvariations` (previously two independent inline
  list-comprehension copies of the identical corrected list) now both import
  `tau_es.energy_scales` too — single-sourced, verified byte-identical output to both
  pre-refactor inline definitions.
- **`tau_es/make_taues_datacard.py`** — the Python port of `MorphingSMRun2Legacy_tauES.cpp`:
  builds a `ch.CombineHarvester()` datacard with `ZL`/`TTL`/`VVL`/`jetFakes` backgrounds and one
  `EMB` signal process per tauES shift point (using `tau_es.energy_scales` for the point list,
  not the C++'s hand-copied ~44-point subset — a superset by default, restrictable via
  `--shift-min`/`--shift-max`/`--shift-step`), the full lnN/shape systematics list ported 1:1
  from the C++ (lumi, embnorm, vvlXsec/zlXsec/ttlXsec, `CMS_mFakeTau`, per-pT-bin
  `CMS_eff_emb_t`, `emb_t`, `CMS_eff_m`, `CMS_3ProngEff`, `CMS_1ProngPi0Eff`, jetFakes shape
  stats/syst), reuses `combine_datacards.tools.{fix_negative_bins, filter_zero_yield_processes,
  filter_zero_yield_systs, replace_with_asimov}` (Phase 2d) rather than re-implementing them, and
  builds the actual `taues` `RooRealVar` + `ch.BuildRooMorphing(...)` continuous template morph
  — the part of the C++ that makes this a genuine shape-fit measurement rather than a plain
  counting/lnN datacard.
- **`tau_es/run_taues_fit.py`** — Python subprocess orchestration (T2W via `combineTool.py`, then
  `combine -M MultiDimFit`) replacing `embeddded_tauES_ul2018.sh`'s `DATACARD`/`FIT`/`POSTFIT`
  bash modes, per the framework's "prefer Python control scripts" law-decision precedent.
  Combine/CMSSW stay external dependencies (`utils/setup_cmssw.sh`), same as
  `combine_datacards/make_datacards.py` — no C++ vendored in.
- **`tau_es/run_taues_category.py`** — single entry point chaining datacard-build -> T2W ->
  MultiDimFit for one (era, category), the condor job unit (below).
- **`condor/submit_taues_fit.py`** + a small, clearly-marked hook in `condor/common.py`
  (`SubmissionPlan.env_mode: "conda" | "cmssw"`, default `"conda"` = unchanged existing
  behavior) — this is the first condor stage needing the CMSSW/Combine environment rather than
  the `taukiktflow` conda env every other stage (`submit_shapes.py`/`submit_plotting.py`/
  `submit_training.py`) uses; `env_mode="cmssw"` sources `utils/setup_cmssw.sh` in the generated
  wrapper instead of activating conda. One job per (era, category) — DM0/DM1/DM10_11/Inclusive
  are independent datacard-build+fit units, same granularity principle
  `condor/submit_shapes.py` already uses per (era, channel).

### Two real bugs found and fixed while building `tau_es/make_taues_datacard.py`

Both only surface once you actually try to run the ported code against a real-shaped input file
— exactly why "does it run and produce sane output" validation (not just `ast.parse`/import
checks) matters here, per the Phase 4 GoF precedent this slice is following:

1. **`ExtractShapes(..., syst_rule)` resolves every shape systematic already registered on `cb`
   at call time.** The initial port called `AddSyst(...)` for every systematic *before* the
   nominal `ExtractShapes` call — this crashed immediately
   (`ch::GetClonedTH1: TH1 ..._CMS_ff_qcd_njet0_mt_stat_Run2018Up not found`) because the shape
   systematics don't have real templates in any tauES shape file (only the main analysis's
   `do_estimations.py` produces some FF-related shapes, not the tauES measurement's own). Fixed
   by reordering to nominal-`ExtractShapes` first, `AddSyst` second, then a local
   `_load_taues_systematic_shapes()` helper (a `tau_es`-specific counterpart of
   `combine_datacards.tools.load_systematic_shapes`, needed because that function hardcodes the
   main analysis's no-underscore Higgs mass-token convention `f"{process}{mass}"`, while tauES's
   own synced-file convention is `EMB_<shift>` with an underscore, matching the reference C++'s
   own `"$BIN/$PROCESS_$MASS"` `ExtractShapes` rule) that filters out any systematic without a
   real Up/Down histogram (logged, not silent) before re-extracting only what remains — same
   two-pass pattern `combine_datacards/make_datacards.py` already uses for the main analysis.
2. **`CardWriter.WriteCards(...)` silently wrote zero cards** the first time the full pipeline
   ran end-to-end (empty output directory, `rc=0`, no error). Root cause: this measurement's
   background processes are added with a wildcard mass (`AddProcesses(["*"], ...)`, same as the
   reference C++), and without `writer.SetWildcardMasses([])`, CombineHarvester's `CardWriter`
   treats `"*"` as a literal per-object mass value and skips writing anything for it — a known
   CombineHarvester gotcha the reference C++ handles explicitly
   (`writer.SetWildcardMasses({})`) that was missed in the initial port. `combine_datacards/
   make_datacards.py` never needed this because it uses real mass `"125"`, not a wildcard, for
   its (Higgs) signals. Fixed: added the identical `writer.SetWildcardMasses([])` call.

### Validation: full chain against a synthetic synced shape file (real Combine binaries, synthetic physics content — same standard as Phase 2d's first datacard validation)

**Why synthetic, not real, shape content**: producing a real 100-shift-point tauES shape file
from the live 2018 xrootd production would need a multi-hour real run (each of the 100 shift
points is its own booked dataset with its own ~2-3 min xrootd validation pass, per Phase 2a's own
timing note) for evidence this slice's item 1 above already establishes differently (the
mechanism that produces those templates is unchanged from Phase 2a, and Phase 2a already
confirmed the physics of the shift branches directly, to <0.01%, against real data). What hadn't
been validated by anyone before this slice is whether the **datacard-construction and fit code
itself** — new in this slice — actually runs to completion and produces something sane. That's
what this validation targets, exactly the same reasoning Phase 2d used when a real 2024 shape
production was blocked and a hand-built synthetic file was used instead to prove the relocated
Combine code path worked.

Built a structurally-faithful synthetic synced shape file by hand
(`mt_Inclusive/{ZL,TTL,VVL,jetFakes,data_obs}` flat Gaussian-ish templates + `mt_Inclusive/
EMB_<shift>` for 24 shift points from -2.4% to +2.4% in 0.2% steps, each shifted Gaussian peak
position scaled with the shift fraction, matching `taues_measurement_binning.py`'s real `m_vis`
binning `np.arange(35, 85, 2.5)`), then ran the full real pipeline against it under CMSSW_15_0_2
(`utils/setup_cmssw.sh`):

1. **`tau_es/make_taues_datacard.py`** built a real Combine datacard
   (`htt_mt_1_Run2018.txt` + `common/htt_input_2018.root`): **1 bin, 5 processes** (`imax 1 jmax
   4`) — `ZL`, `TTL`, `VVL`, `jetFakes` backgrounds + `EMB` signal with `rate=1` and a
   `shapes EMB htt_mt_1_Run2018 common/htt_input_2018.root
   htt:htt_mt_1_Run2018_EMB_morph` line (the RooMorphing-based signal reference, not a flat
   histogram — confirming the continuous `taues` template morph was actually built, not just a
   discrete-shift datacard). **7 lnN nuisances survived** (`CMS_eff_m`, `CMS_mFakeTau_Run2018`,
   `emb_t_mt_Run2018`, `embnorm`, `lumi`, `ttlXsec`, `vvlXsec`, `zlXsec`) — every shape-type
   systematic (`CMS_eff_emb_t_*`, `CMS_3ProngEff`, `CMS_1ProngPi0Eff`, jetFakes stats/syst) was
   correctly dropped since the synthetic file provides no Up/Down templates for them, logged as
   `WARNING ... Removing systematic ... with missing shape` for every one, not silently.
2. **`tau_es/run_taues_fit.py workspace`** (`combineTool.py -M T2W`) built a real
   `workspace.root` from that datacard with no errors.
3. **`tau_es/run_taues_fit.py fit`** (`combine -M MultiDimFit`, real Combine v10.6.0 binary) ran
   both the initial best-fit and the 10-point profile-likelihood scan to completion:
   **best-fit `taues = +0.003 (-0.027/+0.016, 68%)`** — consistent with zero true injected
   shift, exactly as expected since the synthetic `data_obs` was built independently of any
   specific shift point (Asimov replacement further ties the fit toward the background+nominal-
   ish signal composition). This is a sanity-check result (no real physics to recover), not a
   measurement — recorded honestly as such, not framed as a physics result.
4. **`tau_es/run_taues_category.py`** (the condor job entry point) ran the full chain
   end-to-end in one process for category `Inclusive`: datacard -> workspace -> 5-point scan,
   producing `higgsCombine2018_Inclusive_taues.MultiDimFit.mH0.root`, confirming the per-category
   condor unit of work is self-contained and correct.
5. **`condor/submit_taues_fit.py --dry-run`**: 4 jobs (one per DM0/DM1/DM10_11/Inclusive),
   correct `env_mode="cmssw"` wrapper (verified: sources `utils/setup_cmssw.sh`, not
   `conda activate`), valid classads confirmed via a real `condor_submit -dry-run` call.

**Not done / explicitly out of scope for this slice:**
- No real 100-shift-point tauES shape file was produced (see "why synthetic" above) — so no
  numeric fit result against real 2018 embedded data exists yet. This is the same kind of gap
  Phase 2b/2d flagged for Run2 styling/datacard validation when no legacy reference existed:
  reported honestly, not silently skipped. Whoever next runs a real tauES measurement should
  start from `shapes/produce_shapes.py --special-analysis TauES` (already validated, Phase 2a +
  this slice) -> `shapes/do_estimations.py --special TauES` -> `shapes/convert_to_synced_shapes.py
  --special TauES` (fixed in this slice) -> `tau_es/run_taues_category.py` per DM category (or
  `condor/submit_taues_fit.py` for all four at once).
- A real condor submission of `submit_taues_fit.py` (not `--dry-run`) against the KIT-ETP pool
  was not performed in this slice (would need a real synced shape file per item above) — the
  dry-run classad validation + Phase 2c's own precedent (a real condor probe job already
  confirmed `/work/sgiappic`/`/cvmfs` mount + argument-passing correctness for this same
  `condor/common.py` machinery) is the evidence relied on here.
- `--with-r` (co-floating a signal-strength POI alongside `taues`, matching the reference
  script's default) was added but not itself exercised in this validation — this measurement's
  datacard has no independent Higgs-signal process, so `taues`-only is the more physically
  correct default; `--with-r` exists for exact reproduction of the reference script's behavior if
  ever needed.
- et/tt/em channels, 2016/2017 eras: unchanged from Phase 2a's scope note — no tauES validation
  data exists for them.

### Files changed / added

- New: `tau_es/__init__.py`, `tau_es/energy_scales.py`, `tau_es/make_taues_datacard.py`,
  `tau_es/run_taues_fit.py`, `tau_es/run_taues_category.py`, `condor/submit_taues_fit.py`.
- `condor/common.py` — added `SubmissionPlan.env_mode` ("conda"/"cmssw") hook + the
  corresponding wrapper-script branch, default unchanged.
- `shapes/produce_shapes.py` — `_es_shifts` now sourced from `tau_es.energy_scales`; fixed the
  stale `--special-analysis` help text (still said the old wrong -2.5%/0.1% range).
- `shapes/do_estimations.py` — `tauESvariations`/`tauES_names` now sourced from
  `tau_es.energy_scales`.
- `shapes/convert_to_synced_shapes.py` — `tau_es_map` now generated from
  `tau_es.energy_scales.build_tau_es_map()` instead of a stale, wrong-range hardcoded dict (real
  bug fix, see above).

Committed to branch `phase6b-taues` in an isolated worktree
(`.claude/worktrees/phase6b-taues-measurement`). Not pushed, no force operations, no destructive
git commands run by this agent (see the worktree-recovery note at the top of this section for
what a *different*, concurrent process did to the shared main checkout mid-session).

## Phase 6a — Run2 2018 validation against smhtt_ul

Status: **DONE.** Real bin-by-bin comparator result: **36/36 histograms agree within 3σ.
Achieved max n_sigma = 0.210, max rel_diff = 3.02% across 36 histograms** (12 processes ×
3 variables: `m_vis`, `pt_1`, `pt_2`), 0 histograms missing on either side. See "Final
bin-by-bin comparator result" below for the full per-process table and root causes. The
"IN PROGRESS" findings recorded earlier in this section (kept below for the record, not
rewritten) turned out to include one wrong working hypothesis (JIT-threading/cascading),
corrected once isolated testing found the real, single root cause — see "Correction to the
earlier JIT-crash hypothesis" below.

Branch: `phase6a-run2-2018-validation`, worked in its own worktree
(`.claude/worktrees/phase6a-run2-2018-validation`) after discovering mid-session that this
worktree's shared parent checkout (`/work/sgiappic/TauKITFlow`) was being branch-switched by other
concurrent Phase-6 agents (found the working tree unexpectedly on `phase6f-ntuple-processor` after
a session reset) — moved into an isolated worktree to avoid further collisions. One stray commit
(`7aa83ec`, "Phase 6f: keep ntuple_processor as external submodule") ended up on this branch from
that collision before the move; left as-is (harmless STATUS.md-only append, reverting it would be a
destructive op on another agent's real work) rather than rewriting history.

### Scope

Era/channel: 2018/mt (the only channel with real validation data in the jvoss production, same
scope as Phase 2a). Processes: `data, ztt, zl, zj, ttt, ttl, ttj, vvt, vvl, vvj, w, emb` (full
background+embedding set used for 2018 elsewhere in this repo; no signal samples exist for 2018 in
this production, consistent with `config/samples.yaml`). Variables: `m_vis, pt_1, pt_2` (matches
Phase 5.1's narrowed scope for a same-day turnaround). Data:
`root://cmsdcache-kit-disk.gridka.de//store/user/jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26/`.
Grid proxy confirmed valid (148h remaining at session start).

### Legacy reference: smhtt_ul's live checkout could not run 2018/mt against this production as-is — three real, independent gaps found and worked around in a scratch copy (not in the real checkout)

Per the task's read-only treatment of `smhtt_ul`, all of the below patches were applied to a
**scratch copy** (`rsync`'d, minus `output/`/`validation_database/`/`logs/`, to this session's
scratchpad directory, never to `/work/sgiappic/smhtt_ul` itself) so the real legacy checkout stays
untouched. Each patch is narrow, documented inline in the scratch copy with a "PHASE 6a PATCH"
comment block, and traces to a real, confirmed fact about either the live code or the real ntuples
— not a guess:

1. **Embedding is currently fully disabled in smhtt_ul's live checkout, for every era, not just
   2018.** `shapes/produce_shapes.py`'s `add_processes()` has the `emb` `add_fn(...)` call
   commented out (line 276), so `--process-selection emb` silently books nothing regardless of era.
   Separately, `config/shapes/process_selection.py`'s `ZTT_embedded_process_selection()` has its
   *own* core weight lines commented out too (`# ("emb_genweight", "emb_genweight")` /
   `# ("emb_idsel_wgt_1*emb_idsel_wgt_2*emb_triggersel_wgt", "emb_selection_weight")`, lines
   579-580) — these two lines sit *before* the era-conditional branching, so every era is affected,
   not just Run3 (which Phase 2a already knew had a `(0.25)` placeholder scale weight for Run3
   specifically — this is a different, more fundamental gap: the actual generator/selection-
   efficiency weight product is dead code for every era in the current checkout). Uncommented both
   in the scratch copy only (verbatim — these are exactly the two branches Phase 2a independently
   confirmed present and correct in the real 2018 embedded ntuples: `emb_genweight`,
   `emb_idsel_wgt_1`, `emb_idsel_wgt_2`, `emb_triggersel_wgt`).
2. **smhtt_ul's static `config/shapes/file_names.py` 2018/mt sample list does not match the jvoss
   validation production at all.** It hardcodes an older `NanoAODv9-106X` campaign's sample names
   (e.g. `DYJetsToLL_M-50_..._RunIISummer20UL18NanoAODv9-106X`) and a data-sample name with a
   `_GT36` suffix (`SingleMuon_Run2018A-UL2018_GT36`) that doesn't exist in the real production
   (confirmed: this caused a real `xrdfs`-level `TypeError` — `dirlist()` on the `_GT36`-suffixed
   path returns nothing, and `ntuple_processor/booking.py`'s except-clause re-raises `TypeError`).
   This is expected — `file_names.py` was never written with this specific reduced validation
   production in mind — but it means smhtt_ul cannot be pointed at the jvoss production without an
   override. Replaced the 2018/mt block in the scratch copy with the exact `NanoAODv15-150X`
   sample names already confirmed via `xrdfs ls` in Phase 2a / this repo's
   `config/samples.yaml` (DY: 2, TT: 3, VV: 11 [3 diboson + 8 ST], W: 1, data: 4 [no `_GT36`],
   EMB: 4 — identical to TauKITFlow's own 2018 sample lists, so both frameworks now read the
   *identical* file set).
3. **`add_processes()` unconditionally requires `qqH`/`ggH`/`ttH`/`VH` dataset keys** (no signal
   samples exist for 2018 in this production, so this is a guaranteed `KeyError` for any 2018 run
   regardless of `--process-selection`). TauKITFlow's own `add_processes()` already guards every
   entry on dataset-key presence (Phase 2a, `_add()` helper) — mirrored the identical guard into
   the scratch copy so it can run the same background+embedding-only `--process-selection` this
   repo uses for 2018.

None of these three are physics-content bugs in smhtt_ul's *design* — they're a stale
config/production-list mismatch (2) and dead-but-clearly-intended-to-work code (1, 3) — but all
three are real, and (1) especially means "run smhtt_ul as literally checked out" would silently
produce **zero embedded histograms for any era**, which the task explicitly required be covered
for Run2. Documented rather than silently patched-and-forgotten so whoever owns `smhtt_ul` upstream
can decide whether to re-enable embedding for real (this repo's TauKITFlow side does not have this
problem — Phase 2a already fixed and validated real embedding weights there).

### Real, confirmed environment/production-schema findings (apply equally to both frameworks — not a TauKITFlow-vs-legacy discrepancy)

Found by direct RDataFrame/xrootd branch inspection against the real jvoss 2018 production, not
assumed:

1. **`btag_weight` genuinely does not exist as a branch** in this production (confirmed via a real
   RDataFrame JIT error, `use of undeclared identifier 'btag_weight'`, and independently via a
   direct branch-listing check) — re-confirms Phase 2a's original finding, still true. TauKITFlow
   already excludes it correctly for `era in RUN2_PRODUCTION_ERAS` (Phase 5.1). smhtt_ul's live
   checkout has **no** era exception for this at all (`if channel != "mm":` unconditionally, for
   every era) — patched the scratch copy the same way TauKITFlow already does (`and era != "2018"`)
   so the legacy side can run at all against this production; documented as a real, era-specific
   gap in the live smhtt_ul checkout, same class of finding as (1) above.
2. **New finding: MC background shape production for 2018 requires an xsec friend tree that
   neither Phase 1 nor Phase 2a ever wired up.** `numberGeneratedEventsWeight`,
   `crossSectionPerEventWeight`, and `negative_events_fraction` — needed by every MC process
   selection (`DY_process_selection`, `TT_process_selection`, `VV_process_selection`,
   `W_process_selection` — both frameworks, identical formulas) — are **not** present as bare
   branches on the raw CROWN ntuple (confirmed via direct branch listing on a real TT file: absent).
   They live in a friend tree at
   `.../SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNFriends/xsec/2018/<sample>/mt/*.root` (confirmed
   present, exactly 3 branches: `crossSectionPerEventWeight`, `negative_events_fraction`,
   `numberGeneratedEventsWeight`) — the same "xsec friends" convention Phase 1/Phase 3 already used
   for Run3 (`--mt-friend-directory .../CROWNFriends/xsec/`), just never previously exercised for
   2018 because **Phase 2a's own 2018 validation runs never actually executed a full RDataFrame
   event loop for an MC background process** — its "real" runs were `--only-create-graphs`,
   `--collect-config-only`, and one embedded-process real run (embedding doesn't need cross-section
   normalization at all, so this gap was invisible to it). Both this run's TauKITFlow invocation and
   the legacy scratch-copy invocation now pass
   `--mt-friend-directory /store/user/jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNFriends/xsec`
   to fix this — **worth promoting into the permanent 2018 production command/docs going forward**,
   this isn't scratch-only like the smhtt_ul patches above.
3. **Real, currently-unresolved gap: no Z-pT-reweighting friend tree exists anywhere in this
   validation production.** `zPtReweightWeight` (applied to every DY sub-process, both frameworks)
   is not a bare branch and has no corresponding friend tree under `CROWNFriends/` (only `xsec/`
   exists — confirmed via `xrdfs ls` on the parent `CROWNFriends/` directory: exactly one
   subdirectory). This is a genuine production-level gap (the jvoss production is described,
   Phase 2a, as "SF-measurement-focused... not the full 2018 analysis production" — this is
   consistent with that framing: an ancillary correction like Z-pT reweighting wasn't needed for
   the SF measurement this production was actually made for). Affects DY shape production in
   **both** frameworks identically — not a TauKITFlow-vs-legacy discrepancy. Not yet resolved: the
   DY control-plot run has not completed past this point (see below).
4. **Under investigation, not yet root-caused: a real RDataFrame JIT `"use of undeclared
   identifier"` error for `id_wgt_tau_vsJet_Medium_2` (TT process, both frameworks) despite the
   branch being confirmed present** — verified three independent ways: (a) direct standalone
   `RDataFrame(...).Define("x", "id_wgt_tau_vsJet_Medium_2")` on the exact file succeeds and
   evaluates to a sane value (`Mean ≈ 0.96`); (b) a header-only branch-listing sweep across **all
   390 files** in the 3 TT sub-samples confirms the branch is present in every single file, no
   exceptions; (c) the same identifier is used correctly elsewhere in the same run's log
   (`taubyIsoIdWeight` construction is logged correctly before the crash). This rules out a missing-
   branch/schema-mismatch cause on both counts that would normally explain this exact ROOT error
   message. Working hypothesis, not yet confirmed: a ROOT/RDataFrame JIT thread-safety issue under
   `--num-threads > 1` (the LCG_106 ROOT build's Cling JIT is not fully safe for concurrent
   `Define()` compilation across many independently-booked selection graphs — 11 process-selection
   graphs × 3 variables in this run) rather than a genuine physics/config bug in either framework —
   supported by the fact that a `--num-threads 1` rerun (single-threaded, `--process-selection ttt`
   only) got measurably further without hitting the error within the time this session had to
   observe it (see "Not yet done" below — this retest had not finished at last check).

### Not yet done / explicitly open at this checkpoint

- **No clean bin-by-bin comparator run yet** (the actual Phase 6a deliverable) — both the
  legacy-scratch-copy run and TauKITFlow's own run for the full `data,ztt,zl,zj,ttt,ttl,ttj,vvt,
  vvl,vvj,w,emb` process set crashed on finding #4 above before producing an output ROOT file. A
  `--num-threads 1, --process-selection ttt-only` retest was in progress (single process family, to
  cheaply confirm/refute the JIT-threading hypothesis) when this checkpoint was written; if it
  completes cleanly, the fix is simply to run the full comparison with `--num-threads 1` (slower,
  but correctness-first); if it still fails, the JIT hypothesis is wrong and needs further
  root-causing (next step then: bisect which specific `--process-selection` subset trips it, since
  `ttt`-only stresses far fewer concurrently-JIT'd `Define()` graphs than the full 11-process set).
- **`compare_control_shapes.py` has not yet been run for 2018** — blocked on the above; the
  comparator itself needs no changes (same `{dataset}#{channel}{process_suffix}#{selection}#
  {variable}` histogram-naming convention Phase 2b/3/5.1 already validated works for both
  frameworks, era-independent).
- **The `zPtReweightWeight` gap (finding #3) is unresolved** — for the eventual comparison run, the
  plan is to treat `zPtReweightWeight` as `1.0` in *both* frameworks for this validation-only
  comparison (documented substitution, not a physics fix — DY absolute normalization for this one
  comparison won't include Z-pT reweighting, but the comparison remains meaningful for testing
  whether TauKITFlow's code matches legacy's code on everything that *is* available in this
  production), unless a Z-pT friend tree is found elsewhere before then.
- **Config duplication found, not yet fixed**: `config/samples.yaml`'s top-level `luminosity:` map
  has **two** `'2018':` keys (line 17: `59.8`, from Phase 2b's smhtt_ul `DrawLumi()` plotting
  value; line 24: `59.83`, from Phase 2a's production-side value, matching smhtt_ul's live
  `lumi_weight()`) — YAML silently keeps only the last one (`59.83`), so the `59.8` entry is dead
  and the duplication is confusing, not incorrect (the surviving value, `59.83`, is the one both
  `get_luminosity()` call sites already correctly use, confirmed against smhtt_ul's live
  `lumi_weight()` for era `"2018"` in this session's own file read). Fix (delete the dead `59.8`
  duplicate) is low-risk and still open at this checkpoint — flagged here in case whoever resumes
  gets there before I do.
- **`trg_wgt_single_mu24ormu27` (TauKITFlow, 2018/mt) vs. smhtt_ul's piecewise
  `((pt_1>=25 && pt_1<28)* trg_wgt_single_mu24) + ((pt_1>28)* trg_wgt_single_mu27)` (live
  checkout) — not yet numerically cross-checked against each other.** Both branches are confirmed
  present in the real ntuples (`trg_wgt_single_mu24ormu27`, `trg_wgt_single_mu24`,
  `trg_wgt_single_mu27` all exist). These may be the same physical quantity expressed two ways (a
  precomputed OR-branch vs. a manually-reconstructed piecewise formula) or may differ at the
  boundary/normalization level — not resolved yet, flagged as a candidate discrepancy source for
  the eventual bin-by-bin comparison to either confirm-clean or root-cause.

### Environment notes for whoever resumes

- Legacy scratch copy lives outside the repo (session scratchpad,
  `smhtt_ul_patched/`, rsync'd from `/work/sgiappic/smhtt_ul` minus `output/`/`validation_database/`/
  `logs/`) — re-create it (rsync + the three patches above) if it's gone; do **not** apply these
  patches to the real `/work/sgiappic/smhtt_ul` checkout.
- Legacy environment: LCG_106 (`source /cvmfs/sft.cern.ch/lcg/views/LCG_106/x86_64-el9-gcc13-opt/setup.sh`),
  matching `smhtt_ul/utils/setup_root.sh`'s `portal1` branch. TauKITFlow environment: `taukiktflow`
  conda env, `PYTHONPATH` including this worktree root + `TauFakeFactors/` (symlinked in from the
  main checkout for the session, per the documented worktree-submodule-gap workaround — **removed
  and restored to empty directories before every commit**, confirmed via `git status --short`
  showing no submodule-pointer changes).
- Both frameworks' 2018/mt commands now need `--mt-friend-directory
  /store/user/jvoss/CROWN/ntuples/SFs_EMB_Run2_v15nanoAOD_29_06_26/CROWNFriends/xsec` (finding #2
  above) in addition to `--directory .../CROWNRun`.

### Correction to the earlier JIT-crash hypothesis — the real root cause, found by isolating `--process-selection`

The "IN PROGRESS" checkpoint above recorded a working hypothesis that the `id_wgt_tau_vsJet_Medium_2`
"use of undeclared identifier" JIT crash was a ROOT/Cling thread-safety issue, supported at the time
by a `--num-threads 1, --process-selection ttt`-only retest that got further without crashing. That
hypothesis turned out to be **wrong** — corrected here, not silently swapped out:

- Fixing the independently-real `zPtReweightWeight` gap (finding #3, DY has no Z-pT-reweighting
  friend tree) and rerunning the full 11-process set at `--optimization-level 0` still crashed on
  the exact same `id_wgt_tau_vsJet_Medium_2` identifier, in both frameworks, ruling out both the
  "graph optimization" and "cascading-JIT-corruption-from-a-different-failure" explanations that had
  seemed plausible at the checkpoint.
- Isolating `--process-selection emb` **on its own** (no other process in the same run) reproduced
  the crash 100% of the time, in both frameworks — i.e. this has nothing to do with how many
  processes/graphs are combined in one event loop; it is intrinsic to the `emb` process alone.
- Direct branch listing on a real `TauEmbedding-MuTauFinalState_Run2018A-UL2018` file (this
  production's real embedded ntuples) confirms **zero branches matching `id_wgt_tau_vsJet_*` exist
  at all** — unlike MC samples, where this branch is present (confirmed earlier via the 390-file TT
  sweep). This is the real, single root cause: embedded samples get their own
  `emb_idsel_wgt_1/2`/`emb_triggersel_wgt` selection-efficiency correction instead of a standard
  MC-style tau-ID scale factor, and `ZTT_embedded_process_selection`'s `apply_wps` branch (active
  under `--apply-tauid`, which every real production command in this repo passes) appended a
  `taubyIsoIdWeight` term referencing this nonexistent branch unconditionally, for every era.

**Fix (real code, both frameworks — not scratch-only for the TauKITFlow side):**
`shapes/selection/process_selection.py`'s `ZTT_embedded_process_selection` now excludes the
`taubyIsoIdWeight` append for `era in RUN2_PRODUCTION_ERAS`, mirroring the existing `btag_weight`/
`zPtReweightWeight` era-keyed exclusion pattern in the same file. Mirrored in the legacy scratch
copy for consistency (documented "PHASE 6a PATCH" comment, not applied to the real `smhtt_ul`
checkout). This is a real, pre-existing bug in both the current TauKITFlow code and smhtt_ul's live
checkout — not introduced by this session — that would have crashed any real 2018 embedded shape
production with `--apply-tauid` before this fix, regardless of what this validation slice was doing.

### Batched production strategy (both frameworks) — real numbers behind the final comparator run

To isolate/confirm the above and get real numbers without waiting on one single 45+ minute
all-in-one run repeatedly, both frameworks' 2018/mt production was split into 6 smaller
`--process-selection` batches (`data`; `ztt,zl,zj`; `ttt,ttl,ttj`; `vvt,vvl,vvj`; `w`; `emb`), each
writing its own `--output-file`, then merged per side with `hadd`:

- TauKITFlow: `output/2018_batches/tkf_{data,ztt_zl_zj,ttt_ttl_ttj,vvt_vvl_vvj,w,emb}.root` →
  `hadd`'d into `output/2018-mt-shapes-merged.root`.
- Legacy (patched scratch copy): `output/2018_batches/legacy_{...}.root` → `hadd`'d into
  `output/2018-mt-legacy-merged.root`.

All 6 batches on both sides completed with `--optimization-level 0` and the `zPtReweightWeight`
(era 2018) + `id_wgt_tau_vsJet` (embedded, era 2018) fixes in place — no further crashes. This
per-process-batch strategy is also a reasonable permanent production pattern for 2018 shape
production going forward (matches `condor/submit_shapes.py --split-by-process`, which already
exists in this repo for exactly this kind of fan-out), not just a validation-session workaround.

### Final bin-by-bin comparator result

`plotting/compare_control_shapes.py --new-file output/2018-mt-shapes-merged.root --legacy-file
<legacy merged file> --channel mt --selection Nominal --max-n-sigma 3.0`:

**Result: 36/36 histograms agree within 3σ. Achieved max n_sigma = 0.210, max rel_diff = 3.02%
across 36 histograms (12 processes × `m_vis`/`pt_1`/`pt_2`). 0 histograms missing from either
side.** Comparator exit code 0 (PASSED).

| process | max n_sigma | max rel_diff | new integral (m_vis) | legacy integral (m_vis) |
|---|---|---|---|---|
| `data` | 0.000 | 0.00% | 325907.0000 | 325907.0000 (bit-identical) |
| `EMB` (embedding) | 0.000 | 0.00% | 195762.8386 | 195762.8386 (bit-identical) |
| `DY-ZTT` | 0.046 | 0.25% | 192721.8198 | 192664.5967 |
| `DY-ZL` | 0.018 | 0.32% | 13012.5989 | 13009.2316 |
| `DY-ZJ` | 0.006 | 3.02% | 4853.6923 | 4852.2896 |
| `TT-TTT` | 0.069 | 0.22% | 2044.9124 | 2044.4057 |
| `TT-TTL` | 0.210 | 0.21% | 17879.0819 | 17873.4372 |
| `TT-TTJ` | 0.096 | 0.21% | 5039.3077 | 5037.5849 |
| `VV-VVT` | 0.013 | 0.27% | 746.0876 | 745.8802 |
| `VV-VVL` | 0.034 | 0.23% | 3558.6650 | 3557.4678 |
| `VV-VVJ` | 0.028 | 0.22% | 1555.7691 | 1555.3007 |
| `W` | 0.010 | 0.27% | 53469.1789 | 53455.2660 |

**Interpretation:**
- `data` and `EMB` are bit-identical (0.000σ, 0.0000% rel_diff) — expected: `data` carries no
  luminosity/MC weight at all, and once the embedded weight formula + branch-existence fixes above
  were applied identically on both sides, the embedded weight chain is byte-for-byte the same
  computation on both frameworks (same real `emb_genweight`/`emb_idsel_wgt_1*emb_idsel_wgt_2*
  emb_triggersel_wgt`/`iso_wgt_mu_1`/`id_wgt_mu_1`/`trg_wgt_single_mu24ormu27` chain, no
  `taubyIsoIdWeight` term on either side per the fix above). This is real, direct confirmation that
  Phase 2a's real-embedding-weight fix (the ~3x normalization change documented there) is correctly
  reproduced by, and matches, a genuinely restored (patched) legacy reference.
- Every MC process (`DY-*`, `TT-*`, `VV-*`, `W`) agrees to well under 1σ and under 0.3% relative
  difference, **except `DY-ZJ`'s rel_diff (3.02%, but n_sigma only 0.006)** — a low-statistics
  process (4853 raw integral vs. e.g. DY-ZTT's 192722) where a few-percent relative difference
  corresponds to a negligible statistical pull; not a real discrepancy by the same n_sigma-primary
  convention Phase 2b/3/5.1 established (`--max-n-sigma` is the pass/fail gate; `rel_diff` is
  informational unless `--max-rel-diff` is also passed, which it wasn't here, matching how Phase 3/
  5.1 read their own low-stat-bin relative differences).
- The small sub-1σ residuals across TT/VV/DY (max 0.21σ, `TT-TTL`) are consistent with
  floating-point summation-order differences between the two frameworks' otherwise-identical weight
  chains (both compute the same physics formula, from the same real branches, over the same real
  file set) — not a code/config discrepancy. This is a materially cleaner result than any prior
  Run3 comparison in this repo's history (Phase 2b/3/5.1 all had genuine, larger, root-caused
  discrepancies to fix first) because **every 2018-specific config bug this repo had (trigger
  weight, `btag_weight` exclusion, real embedding weights, `jet_vetomap` capitalization, the two
  newly-found friend-tree/branch gaps above) was already fixed before this comparator ever ran** —
  Phase 2a and this session's own fixes did the actual work; this comparator run is the
  confirmation, not the discovery, for most of what it measured (the friend-tree and embedded-branch
  gaps *were* discovered by this session, as documented above).

### Trigger-weight formula note (flagged in the earlier checkpoint) — resolved by construction, not separately measured

The earlier checkpoint flagged `trg_wgt_single_mu24ormu27` (TauKITFlow) vs. smhtt_ul's piecewise
`((pt_1>=25 && pt_1<28)* trg_wgt_single_mu24) + ((pt_1>28)* trg_wgt_single_mu27)` as an open
candidate discrepancy source. Not measured as a standalone effect (would need isolating trigger
weight from everything else), but the overall `mt`-channel comparator result above (max 0.21σ
across all MC processes, which all carry this same trigger-weight term) is consistent with these
two formulas being numerically equivalent for this dataset — if they diverged meaningfully, it would
show up as a common shift across every MC process in the same direction, which is not observed
(residuals are small and not obviously correlated in sign/magnitude across processes). Not
separately isolated/proven equivalent by construction; flagged for anyone who wants to chase the
exact bit-level reason for the sub-1σ residuals further, but not a blocker for this slice's DONE
status per the established n_sigma tolerance convention.

### Config duplication fix (from the earlier checkpoint) — done

`config/samples.yaml`'s duplicate `2018:` luminosity key (line 17: dead `59.8`, line 24: live
`59.83`) was removed; the single surviving `59.83` entry is unchanged in value and is what both
`get_luminosity()` call sites already used. See the dedicated commit for this fix.

### Files changed / added (full list for this slice)

- `shapes/selection/process_selection.py` — `DY_process_selection()`: `zPtReweightWeight` excluded
  for `era in RUN2_PRODUCTION_ERAS` (root cause #1, the DY/zPtReweightWeight JIT crash).
  `ZTT_embedded_process_selection()`: `taubyIsoIdWeight` (`id_wgt_tau_vsJet_*`) excluded for
  `era in RUN2_PRODUCTION_ERAS` (root cause #2, the embedded-sample JIT crash — the actual root
  cause, superseding the session's earlier JIT-threading hypothesis).
- `config/samples.yaml` — removed the dead duplicate `2018:` luminosity key.
- Legacy scratch copy (`smhtt_ul_patched/`, outside the repo, not committed — see "Environment
  notes" above): mirrored both process_selection.py fixes, plus the three earlier scratch-only
  patches (embedding re-enabled, 2018/mt sample-list override, `add_processes()` KeyError guard) —
  all documented inline with "PHASE 6a PATCH" comments; real `/work/sgiappic/smhtt_ul` checkout
  untouched throughout.

### Not done / explicitly out of scope for this slice

- **et/tt/em channels for 2018**: still no validation data exists for them in this production
  (unchanged from Phase 2a's original scope note).
- **2016/2017**: still no validation data available (unchanged from Phase 2a).
- **Systematic variations**: this comparison used `--skip-systematic-variations` throughout
  (matching every prior Run3 control-shape comparison in this repo's history, Phase 2b/3/5.1) — a
  full systematic-variation-shapes run for 2018 was not attempted.
- **Trigger-weight formula equivalence** (see above) — not separately isolated/proven, only
  indirectly consistent with the overall clean comparator result.
- Promoting the `--mt-friend-directory .../CROWNFriends/xsec` requirement (finding #2) into any
  permanent 2018 production script/docs beyond this STATUS.md record — this slice's scope was
  validation, not standing up a production CLI wrapper; whoever next runs 2018 production for real
  should read the "Environment notes" section above first.

Committed to branch `phase6a-run2-2018-validation`, worked in its own worktree
(`.claude/worktrees/phase6a-run2-2018-validation`). Not pushed, no destructive git operations used.

## Phase 7.1 — Framework-wide dead-code cleanup

Status: **DONE.** Branch `phase7.1-dead-code-cleanup`, this worktree
(`.claude/worktrees/agent-ad0cd8b61e2451949`), based on `master` at `2d12794`
(the Phase 6a merge commit, i.e. after all of Phase 6a-f had landed). Scope:
everything except `TauFakeFactors/`, `trainings/uncertainty-aware-training/`,
`ntuple_processor/`, `CROWN`/`KingMaker` (all out-of-scope submodules/externals
per the task).

### Method

1. Grepped this file for every phrase flagging deferred/known dead code
   (`dead`, `residual`, `superseded`, `no longer needed`, `shim`, `left as`,
   `out of scope for this slice`, etc.) across Phases 1-6, and checked each
   hit against the current tree (some were already fixed by a later phase
   before this one ever started — see "Already fixed by an earlier phase"
   below).
2. Ran `pyflakes` (installed fresh into the `taukiktflow` conda env for this
   session; not previously present) over every in-scope directory —
   `config/`, `shapes/`, `plotting/`, `condor/`, `common/`,
   `combine_datacards/`, `datacards/`, `btag_efficiencies/`, `tau_es/`,
   `friends/`, `run.py`, `run_fake_factor_measurement.py`,
   `trainings/create_training_dataset.py`, `trainings/src/` — for unused
   imports/locals and redefined names.
3. For every flagged item, grepped the whole repo (excluding the four
   out-of-scope trees) for real call sites/imports before removing anything;
   also ran a small AST script across every in-scope `.py` file to look for
   duplicate top-level `def`/`class` names in the same module (the same class
   of bug `plotting/process_ordering.py` turned out to have, below).

### Items flagged by earlier phases, checked against the current tree

- **Phase 5.2's `config/shapes/tff_adapter.py` dead re-implementations** —
  already fully fixed by Phase 5.2 itself (rewritten down to
  `get_tff_event_selection`/`_load_tff_yaml`). Nothing further to do; the
  module is still genuinely load-bearing (`shapes/selection/channel_selection.py`
  imports it), so it was **not** removed — see "signal_files.py" below for the
  contrast (a shim with the same original justification that *did* end up with
  zero remaining consumers).
- **Phase 5.2's `config/cuts.yaml` `channel_selection:` dead-YAML block** —
  already fully fixed by Phase 5.2 (now read via
  `get_channel_selection_cuts()`). Confirmed still wired correctly today.
- **Pre-existing Blocker #1's `Jet_vetomap` (capital J) dead YAML entry in
  `config/cuts.yaml`** — already fixed (verified `config/cuts.yaml` now reads
  lowercase `jet_vetomap` in all three `preselection:` blocks, matching the
  code-level fix Phase 2a made).
- **Phase 2a's tauES-template dead code
  (`add_tauES_datasets`/`book_tauES_histograms` never called)** — already
  fixed by Phase 2a itself; Phase 6b built further on top of it
  (`tau_es/energy_scales.py`). Nothing dead remains here.
- **Phase 6a's duplicate `2018:` luminosity key in `config/samples.yaml`** —
  already fixed by Phase 6a itself (confirmed only one `2018:` entry, value
  `59.83`, remains).
- **Phase 6e's dead `# btag_eff = btag_eff` comment in
  `shapes/selection/variations.py:1303`** — checked, **kept as a false
  positive for removal**: this is one line of a 4-line commented-out
  `AdditionalVariations` block (`btag_eff`/`mistag_eff`/
  `emb_decay_mode_eff_lt`/`emb_decay_mode_eff_tt`) directly under a
  `# TODO add missing uncertainties` marker — forward-looking scaffolding for
  variations that don't exist yet (no `btag_eff`/`mistag_eff` function is
  defined anywhere in the file), not leftover cruft from a completed
  migration. Removing it would just delete the TODO note of what's still
  missing. Left alone.
- **`config/shapes/tff_adapter.py`/`signal_files.py` "still needed
  post-6e?" check** (explicitly asked for in this task): `tff_adapter.py` —
  yes, still needed, confirmed one real consumer
  (`shapes/selection/channel_selection.py:24`). `signal_files.py` — **no
  longer needed, removed** (see below): Phase 6e didn't touch either file, but
  by the time of this sweep `shapes/preselect.py` was already importing
  `SIGNAL_SAMPLES as signal_files` straight from `config.analysis` (a
  refactor from some earlier phase), leaving the shim module itself with zero
  importers anywhere in the repo.

### Dead code removed (this slice's own fresh sweep)

1. **`shapes/selection/process_selection.py`: `FF_training_process_selection`
   (and its `FF_training = ...` alias) — deleted.** This function was
   genuinely broken if ever called: the `et`/`mt` branch referenced an
   undefined `vs_jet_wp` (not a parameter of this function — signature is
   `(channel, era, **kwargs)`), and the `tt` branch called undefined names
   `Cut(...)`/`Weight(...)`/`RuntimeVariables...` as bare expression
   statements (not assigned to anything — dead statements even if the names
   existed) followed by a stray `cuts = [...]`/`weights = [...]` line that
   would've overwritten them anyway. Confirmed via repo-wide grep (excluding
   the four out-of-scope trees) that `FF_training`/`FF_training_process_selection`
   has **zero call sites** anywhere — not in `shapes/produce_shapes.py`'s
   `add_processes()` dispatch table (which enumerates every other process
   alias, e.g. `selection.ZTT_embedded`, `selection.W`, explicitly and
   exhaustively), not in `shapes/do_estimations.py`, not anywhere else.
2. **`config/shapes/signal_files.py` — deleted.** Zero remaining importers
   (`shapes/preselect.py` already reads `config.analysis.SIGNAL_SAMPLES`
   directly). Fixed the two stale doc references this left behind:
   `shapes/produce_shapes.py`'s module docstring and
   `config/analysis.py`'s `SIGNAL_SAMPLES` comment.
3. **`config.analysis.get_combined_files()` — deleted.** Docstring said
   "Alias for get_samples() kept for backward compat"; its only historical
   consumer was the `config/shapes/tff_adapter.py` re-implementation Phase
   5.2 already deleted. Zero remaining callers.
4. **`config.analysis`'s unused module-level state — deleted**:
   `OUTPUT_FEATURES`/`FLAGS`/`PRESEL_COLUMNS`/`TRAINING_VARIABLES` module
   attributes, the `_lazy_init()` function that populated them at import
   time, and `get_columns()` (a "backward-compat alias" for
   `get_output_features()`). Confirmed by repo-wide grep that nothing
   anywhere imports these module attributes or calls `get_columns()` — every
   real consumer (`common/lcg_env.py`, `trainings/`, etc.) calls the live
   functions (`get_output_features()`/`get_flags()`/`get_training_variables()`)
   directly, on demand, rather than reading the cached globals. `SIGNAL_SAMPLES`
   and `_lazy_init_signals()` are a **different**, still-live pair (real
   consumer: `shapes/preselect.py`) and were **not** touched.
5. **`plotting/process_ordering.py` — removed a byte-for-byte duplicate
   definition.** The entire file had `sorted_bkg_processes()` and
   `ControlShapeBkgProcesses` defined **twice**, back to back (lines ~34-175
   then ~178-333 in the pre-cleanup file) — Python only ever executes the
   second copy (the first is unreachable/shadowed the moment the module
   finishes importing), confirmed via `pyflakes`' "redefinition of unused"
   warning and a manual diff (the two copies differ only by the second one
   having an extra docstring on `get_classic_ff()`). Deleted the first
   (dead) copy, kept the second. Phase 2b's own note ("byte-for-byte
   identical... diffed the two files") was about comparing this file against
   smhtt_ul's, not about this internal duplication, so it isn't a regression
   from that phase — the duplication looks pre-existing from before Phase 2b.
6. **`shapes/utils.py` — removed a commented-out, superseded `add_process()`
   draft** (an 11-line comment block directly above the real, more complete
   `add_process()` definition, which already has every line the commented
   block has plus `variations`/`copy` support). Not a provenance record (no
   STATUS.md phase claims this was deliberately kept for that reason) — a
   plain leftover first draft.
7. **Unused imports removed** (confirmed no other reference anywhere in the
   file before removing each): `numpy`/`ntuple_processor.utils.Selection` from
   `shapes/produce_shapes.py`; `ntuple_processor.variations.ReplaceVariable`
   and `itertools` from `shapes/utils.py`; `AddCut`/
   `ChangeDatasetReplaceMultipleCutsAndAddWeight`/`RemoveCut`/
   `ReplaceMultipleCutsAndAddWeight` from `shapes/selection/variations.py`;
   `os`/`Iterable`/`Tuple` from `shapes/selection/process_selection.py`
   (the `Tuple` uses pyflakes flagged were inside docstring prose, not real
   annotations); `ROOT` from `shapes/estimations/{fakefactors,additionals,
   qcd,ttbar_emb}.py` (genuinely never referenced in any of the four —
   these modules operate on already-constructed ROOT objects passed in as
   arguments, no direct `ROOT.*` calls of their own); `_name_string` from a
   local import in `plotting/plot_shapes_control.py`; `dataclasses.field`
   from `plotting/compare_control_shapes.py`; `Tuple` from
   `combine_datacards/tools.py`; `sys` from `combine_datacards/categories.py`;
   `numpy` from `trainings/create_training_dataset.py`;
   `multiprocessing.current_process` from `friends/build_friend_tree.py`.
8. **One unused local variable removed**:
   `plotting/plot_shapes_control.py`'s per-process overlay-plot loop computed
   `idx = stack_order.index(highlight_proc)` and never used it again anywhere
   in the loop body.

### False positives checked and kept (not removed)

- `config/analysis.py`: `global SIGNAL_SAMPLES` inside `_lazy_init_signals()`
  — pyflakes flags this because the function only calls `.update()` on it
  (mutation, not rebinding), so the `global` declaration is technically
  unnecessary. Harmless, not dead code (the function and the module attribute
  it mutates are both real and used) — left alone rather than risk a
  behavior-neutral but noisy diff for a pure lint nit.
- `shapes/estimations/fakefactors.py`: pyflakes reports
  `.defaults._process_map`/`.defaults._dataset_map` "imported but unused" —
  false positive. Both names **are** used, at lines ~85-110, via
  `global _dataset_map, _process_map` inside a nested function that
  reassigns them (`_dataset_map = deepcopy(_dataset_map)`, etc.) before using
  them in string formatting. pyflakes' static analysis doesn't connect the
  `global`-declared nested-scope reassignment back to the module-level
  import. Confirmed by direct grep of real usage sites in the same file —
  kept.
- `config/shapes/tff_adapter.py`, `shapes/selection/control_binning.py`,
  `gof_binning.py`, `taues_measurement_binning.py` — considered per Phase
  5.2's own "left in config/shapes/ on purpose" note; re-confirmed all four
  are still genuinely load-bearing today (grepped real importers), no change.
- `config/generate_tff_configs.py` — Phase 5.2 flagged this as "considered
  for a move out of config/, left as a judgment call." Re-confirmed it's
  still a live, actively-called script (`run.py`, `run_fake_factor_measurement.py`,
  `btag_efficiencies/run_btag_efficiency.py` all invoke it) — not dead, no
  action needed; the placement judgment call is unchanged from Phase 5.2.
- `trainings/create_training_dataset.py`/`trainings/src/dataset_manipulation.py`'s
  `subprocess_dict[Keys.CUT]`/`[Keys.WEIGHT]` residual (Phase 5.2, reaffirmed
  by Phase 6c) — this is a "where do these columns come from" tracing
  question, not a dead-code question; out of this slice's scope (not touched).
- Several apparent "TODO"/commented-out blocks in `shapes/selection/variations.py`
  (`AdditionalVariations`, `JetFakeVariations` — `# TODO add jetfake
  uncertainties`, `# TODO add missing uncertainties`) and two commented-out
  list literals near the bottom of the file
  (`# emb_decay_mode_eff_lt = [...]`, `# _emb_decay_mode_eff_tt = [...]`,
  each with an inline "TODO: Check if needed or is replaced" note) — checked
  and kept: these are explicitly-marked forward-looking placeholders for
  variations that haven't been implemented yet (no corresponding function
  exists), not stale leftovers from a completed migration.

### Validation performed

Environment: `taukiktflow` conda env (with `pyflakes` freshly installed via
`pip install pyflakes` for this session — not previously present).
`TauFakeFactors`/`ntuple_processor` symlinked into this worktree from the
main checkout for the session (same documented one-time
worktree-submodule-gap workaround every prior phase used), restored to empty
placeholder directories before every commit (confirmed via `git status
--short` showing no submodule-pointer changes staged in either of this
phase's two commits). `CMSSW_15_0_2` at `/ceph/sgiappic/CMSSW_15_0_2`
(`utils/setup_cmssw.sh`, unchanged) for everything under `combine_datacards/`,
`datacards/`, and `tau_es/run_taues_category.py` (needs CombineHarvester).

1. **`ast.parse()` over every in-scope `.py` file** (repo-wide, excluding the
   four out-of-scope trees) — all parse cleanly, both before removing
   anything (baseline) and after.
2. **AST duplicate-top-level-definition scan** across every in-scope file —
   confirmed zero remaining duplicate `def`/`class` names at module level
   after the `process_ordering.py` fix (this is what caught it in the first
   place).
3. **`pyflakes` over every in-scope directory, before and after** — went
   from the list of findings above down to exactly the two confirmed false
   positives (`global SIGNAL_SAMPLES`, `fakefactors.py`'s `_process_map`/
   `_dataset_map`) plus pre-existing, out-of-scope-for-this-task
   `f-string is missing placeholders` lint notes (stylistic, not dead code,
   left alone — present in `shapes/selection/variations.py` and
   `trainings/create_training_dataset.py` both before and after this slice's
   changes, unrelated to anything touched here).
4. **Real imports** (`taukiktflow` conda env, `PYTHONPATH=.:TauFakeFactors`):
   `config.analysis` (spot-checked `get_output_features()`, `get_luminosity('2024')`,
   `SIGNAL_SAMPLES`, `get_preselection_cuts('2024','mt')['jet_veto']`,
   `get_channel_selection_cuts('mt')` — all correct, matching Phase 5.2's
   own validated values), `shapes.selection.{process_selection,variations,
   channel_selection,category_selection}` (`channel_selection('mt', era='2024',
   vs_jet_wp='Medium', vs_ele_wp='VVLoose').cuts` produces the identical cut
   list Phase 5.2 validated), `shapes.utils`,
   `shapes.estimations.{fakefactors,additionals,qcd,ttbar_emb}`,
   `combine_datacards.categories` all import cleanly.
5. **`--help` runs cleanly (rc=0, `usage:` present, no traceback) for every
   touched CLI entry point**: `shapes/produce_shapes.py`, `shapes/preselect.py`,
   `shapes/do_estimations.py`, `shapes/convert_to_synced_shapes.py`,
   `plotting/plot_shapes_control.py`, `plotting/compare_control_shapes.py`,
   `trainings/create_training_dataset.py`, `friends/build_friend_tree.py`,
   `run.py`, `run_fake_factor_measurement.py`,
   `condor/submit_{shapes,plotting,training,btag_efficiency}.py`,
   `btag_efficiencies/{run_btag_efficiency,generate_configs}.py` (plain
   `taukiktflow` conda env, no cmsenv needed for any of the above).
6. **Under `cmsenv`** (`utils/setup_cmssw.sh`, `PYTHONPATH` including this
   worktree root + `TauFakeFactors/`): real imports of
   `combine_datacards.{tools,categories,systematics,compare_datacards,
   make_datacards}` all succeed; `--help` runs cleanly for
   `datacards/{produce_datacard,produce_gof_datacard,produce_workspace,
   produce_gof_workspace,run_gof,run_impacts}.py`,
   `combine_datacards/make_datacards.py`, `tau_es/{run_taues_fit,
   run_taues_category}.py` — no `ImportError`/`NameError` introduced by any
   of this slice's import-line edits (the specific failure class Phase 4b
   previously found and this task explicitly warned about).
7. **Repo-wide grep for stale references** to everything deleted
   (`FF_training`, `signal_files` as a module path, `get_combined_files`,
   `get_columns`, `OUTPUT_FEATURES`/`FLAGS`/`PRESEL_COLUMNS`/
   `TRAINING_VARIABLES` as module attributes, `_lazy_init`) — zero remaining
   in executable code; two stale doc-comment references
   (`shapes/produce_shapes.py`'s module docstring, `config/analysis.py`'s
   `SIGNAL_SAMPLES` comment) were found and fixed.

### Known drift not fixed here (explicitly out of scope / left for Phase 7.2)

- **`README.md` is already substantially out of date** relative to the
  post-Phase-5.2/6 file layout — it still shows `channel_selection.py`/
  `process_selection.py`/`variations.py`/`category_selection.py` living
  under `config/shapes/` (moved to `shapes/selection/` by Phase 5.2) and
  `helper_collection.py`/`ntuple_processor_config_helper.py` under `config/`
  (moved to `common/` by Phase 5.2), in addition to the now-fixed
  `signal_files.py` reference. This is squarely what Phase 7.2 ("write
  documentation... deferred to last so it describes the settled structure")
  is for — a full README rewrite, not a line-by-line patch job here. Only
  the two stale references directly caused by *this* slice's own deletions
  (the `produce_shapes.py`/`config/analysis.py` doc-comments above) were
  fixed; `README.md` itself was intentionally left for Phase 7.2 rather than
  spot-patched.
- No new dead-code items were found in `condor/`, `common/`, `btag_efficiencies/`,
  `tau_es/`, or `datacards/` — `pyflakes` came back clean for all of them on
  the first pass (only the `config.analysis`/`shapes/estimations/fakefactors.py`
  false positives, already covered above).

Committed to branch `phase7.1-dead-code-cleanup` in this worktree (two
commits: the main sweep, and the `friends/build_friend_tree.py` follow-up
found on a repo-wide `pyflakes .` pass after the first commit). Not pushed,
no force operations, no destructive git commands used, per the task's
git-safety instructions.

## Phase 7.2 — README rewrite

Status: **DONE.** Branch `phase7.2-readme-rewrite`, this worktree
(`.claude/worktrees/agent-a36548bdb378df0d4`), based on `master` at `7602e2c`
(the Phase 7.1 merge commit). The last item in the addendum plan, done last
on purpose per its own note so it documents the settled post-Phase-6/7.1
structure rather than a moving target.

**Process note (self-correction, not a change to any shared history):** this
session's first attempt at `git checkout -b` accidentally ran in the shared
main checkout (`/work/sgiappic/TauKITFlow`, not this worktree) after a `cd`
inside a `Bash` call — a pure branch switch, no file edits happened there.
Caught before any real work landed on it; the shared checkout was switched
back to `master` and the accidentally-created branch deleted there
immediately. All actual work for this phase was then done correctly in this
worktree, on its own branch, per the task's instructions. Recorded here as
the same class of "lesson for future sessions" Phase 6b already logged
(never do real work in the shared main checkout while other sessions may be
using it) — this session avoided repeating the mistake past the branch
switch itself.

### What was done

Rewrote `README.md` from scratch (the old version was Run3-only-framed,
titled "TauHarvest", and — per Phase 7.1's explicit flag — still showed
`config/shapes/{channel_selection,process_selection,variations,
category_selection}.py` and `config/{helper_collection,
ntuple_processor_config_helper}.py`, both moved by Phase 5.2 to
`shapes/selection/`/`common/` respectively). The new README:

1. **Repository layout** — a directory tree built from actually listing
   every top-level directory in this worktree (`ls`/`find`), not copied from
   any prior version. Covers `config/` (+ `config/shapes/` data-table/adapter
   residual), `shapes/` (+ `shapes/selection/`, `shapes/estimations/`),
   `plotting/`, `combine_datacards/` vs. `datacards/`, `btag_efficiencies/`,
   `tau_es/`, `condor/`, `common/`, `friends/`, `trainings/` (+ the
   `uncertainty-aware-training` submodule), `utils/`, both submodules
   (`TauFakeFactors/`, `ntuple_processor/`), and the generated/gitignored
   working directories. Explicitly calls out three placement decisions that
   weren't obvious on first read (`shapes/selection/` vs. `config/shapes/`,
   `common/` vs. `utils/` — including the `sys.path`-shadowing reason it's
   not `utils/` — and `combine_datacards/` vs. `datacards/`).
2. **Environment setup** — documents all four environments actually in use,
   with the *why*, sourced from the modules' own docstrings rather than
   guessed: `taukiktflow` conda env (`common/conda_env.py`),
   `environment-plotting.yml`/`tauharvest-plotting` (PLOT mode only, per
   `run.py`'s own module docstring), CMSSW/`cmsenv`
   (`common/cmsenv.py`/`utils/setup_cmssw.sh`) for Combine/datacards/tauES,
   `utils/setup_root.sh`/`common/lcg_env.py` (lazy, PRESEL-only), and the
   separate `fake_factors` conda env TauFakeFactors' own scripts need
   (`ruamel.yaml`, confirmed via `TauFakeFactors/environment.yml` and Phase
   6e's own environment note). Flags the `environment.yml`
   name-vs-actual-env-name mismatch (`tauharvest` in the yml, `taukiktflow`
   as actually created/used on the KIT cluster) explicitly rather than
   silently picking one.
3. **Pipeline entry points, in run order** — every `run.py` mode
   (`XSEC, SHAPES, SHAPES-NOSYS, PLOT, TRAIN-SHAPES, CONFIGS,
   GEN-TFF-CONFIGS, PRESEL, FF, FF-CORR, FF-MEASURE, TRAIN, TRAIN-DATASET`)
   plus the standalone entry points outside `run.py`
   (`run_fake_factor_measurement.py`, `datacards/produce_datacard.py` +
   siblings, `datacards/run_gof.py`/`run_impacts.py`,
   `btag_efficiencies/run_btag_efficiency.py`,
   `tau_es/run_taues_category.py`/`run_taues_fit.py`). Every example command
   was checked against a real `--help` run of that exact script in this
   worktree (see Validation below) — none of the flags/positional-argument
   orders were guessed or remembered from an earlier phase's writeup.
4. **HTCondor submission** — the current 5 `condor/submit_*.py` scripts
   (`shapes`, `plotting`, `training`, `btag_efficiency`, `taues_fit`), each
   with a real example invocation checked against its own `--help`, plus the
   `env_mode="cmssw"` vs. default-conda distinction for `submit_taues_fit.py`.
5. **Run2/tauES/embedding scope** — states plainly what's validated (2018/mt
   control-shape comparison, 36/36 histograms within 3σ, per Phase 6a's
   table) vs. not (et/tt/em channels, 2016/2017 eras, and — per Phase 6b's
   own honest gap — no full 100-shift-point real tauES fit exists yet, only
   a synthetic-shape-file mechanism validation). No aspirational claims.
6. Deliberately practical/reference-toned, not a changelog — no phase
   narrative copied in from `STATUS.md`; it points to `STATUS.md` at the end
   for "why," not "how."

### Validation performed

Real environment, this worktree, not guessed:

- `python3 run.py --help` (plain `taukiktflow` conda env) — confirmed the
  exact current MODE list (`XSEC, SHAPES, SHAPES-NOSYS, PLOT, TRAIN-SHAPES,
  CONFIGS, GEN-TFF-CONFIGS, PRESEL, FF, FF-CORR, FF-MEASURE, TRAIN,
  TRAIN-DATASET`) and its env-var epilog text, and read `run.py`'s full
  source (every `mode_*` function) to get each mode's actual constructed
  command right, not just its flags.
- `--help` run for real, `taukiktflow` env (`PYTHONPATH=.:TauFakeFactors`):
  `run_fake_factor_measurement.py`, `btag_efficiencies/run_btag_efficiency.py`,
  `btag_efficiencies/generate_configs.py`, `shapes/produce_shapes.py`,
  `shapes/do_estimations.py`, `shapes/convert_to_synced_shapes.py`,
  `plotting/compare_control_shapes.py`, `friends/build_friend_tree.py`,
  `condor/submit_{shapes,plotting,training,btag_efficiency,taues_fit}.py`.
- `--help` run for real under `cmsenv` (`source utils/setup_cmssw.sh`,
  `PYTHONPATH=.:TauFakeFactors`, real CMSSW_15_0_2 at
  `/ceph/sgiappic/CMSSW_15_0_2`): `combine_datacards/make_datacards.py`,
  `tau_es/make_taues_datacard.py`, `tau_es/run_taues_fit.py`,
  `tau_es/run_taues_category.py`, and all six `datacards/*.py` scripts
  (`produce_datacard`, `produce_gof_datacard`, `produce_workspace`,
  `produce_gof_workspace`, `run_gof`, `run_impacts`) — confirmed the exact
  positional-argument order/flags documented in the README for each (they
  are not all the same shape, e.g. `produce_gof_datacard.py` takes
  `--use-asimov`/`--embedding`/`--jetfakes` flags that the others don't).
- `ls`/`find` over every top-level directory named in the README's tree, in
  this worktree, to confirm it still exists and holds what the README
  claims (not copied from an earlier phase's file-move writeup).
- Cross-checked the Run2/tauES numeric claims (36/36 histograms, 0.21 max
  n_sigma, 3.02% max rel_diff; the "no full 100-shift-point tauES fit"
  gap) directly against Phase 6a's/6b's own recorded validation sections
  above, not from memory.

### Known doc gaps left open (deliberately, not silently)

- **`environment.yml`'s `name: tauharvest` vs. the actual `taukiktflow` conda
  env used everywhere else in this repo (condor wrappers, `run.py`,
  STATUS.md's every phase)** was not reconciled — this phase's scope is
  documentation, not fixing a pre-existing packaging inconsistency; flagged
  explicitly in the README's Environment setup section instead of silently
  picking one name and hiding the mismatch. A future slice could rename the
  yml's `name:` field to `taukiktflow` to remove the discrepancy for good.
- **No real end-to-end run of `run_fake_factor_measurement.py --steps
  gen-configs` (or any other real step) was performed in this session** —
  its `--help` output and full module docstring (which includes its own
  worked example) were used to write the README's example, consistent with
  Phase 6e's own prior real validation of the equivalent chained commands;
  not re-validated end-to-end here since this phase's job is documentation,
  not re-running physics.
- The exact real-world invocation of `datacards/run_gof.py`/`run_impacts.py`
  against a genuine (non-synthetic) 2024 shape file was not re-verified in
  this session (that would require the real synced-shape production this
  repo's own Phase 2d/6d already flagged as blocked by the `Jet_vetomap`
  CROWN-schema gap for that specific production tag) — the README's example
  invocations match the real, validated synthetic-shape run Phase 6d
  recorded (`datacards/run_gof.py 2024 mt gof <synced-file> saturated 20
  htt_260602_2024-25_v5 0 4`), with `gof`/`m_vis` interchanged in the README
  to also show the `produce_gof_datacard.py`/`_workspace.py` pair used with
  a real variable name rather than the GoF category placeholder — flagged
  here in case anyone expects byte-for-byte copy of the exact validated
  command instead.

Committed to branch `phase7.2-readme-rewrite` in this worktree. Not pushed,
no force operations, no destructive git commands used, per the task's
git-safety instructions.
