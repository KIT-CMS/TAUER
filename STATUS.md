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

Status: IN PROGRESS. Phase 2b (below) is DONE.

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

## Phase 3 — Validation comparators

Status: NOT STARTED (Phase 2b's `plotting/compare_control_shapes.py` is usable as-is for
control-plot comparisons; Phase 3 covers datacards/other shape stages not in this slice's
scope).

## Phase 4 — GoF/impacts

Status: NOT STARTED.

## Blockers

None currently.
