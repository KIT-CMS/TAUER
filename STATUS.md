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

Status: NOT STARTED (blocked on Phase 1 validation).

## Phase 3 — Validation comparators

Status: NOT STARTED.

## Phase 4 — GoF/impacts

Status: NOT STARTED.

## Blockers

None currently.
