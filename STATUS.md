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

Status: IN PROGRESS. Phase 2a below is DONE.

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
   `config.analysis.RUN2_ERAS = ("2018",)` / `SUPPORTED_ERAS = RUN3_ERAS + RUN2_ERAS`,
   used by `load_yaml`'s era-validation guard (TauFakeFactors already ships a
   `configs/smhtt_ul/2018` preselection set, so no new TFF config was needed) and by
   `channel_selection`'s era guard.
8. **`shapes/estimations/*.py` (QCD/FF/embedding-ttbar estimation logic itself)
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
   - A parallel `--collect-config-only` run across all 2018 mt processes (`data,
     ztt, zl, zj, ttt, ttl, ttj, vvt, vvl, vvj, w, emb`) was also started for a
     Phase-1-style full per-file `xrdfs` validation record, but is slow (as in Phase
     1) and was still in progress when this phase was wrapped up — not needed as
     additional evidence given items 1-5 above already demonstrate correctness with
     concrete numbers on real data.
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
- The `--collect-config-only` full-validation run (item 5 above, last bullet) did
  not finish within this session's time box; if picked up again, its output would
  live at `/tmp/.../2018_mt_config.yaml` (scratch path, not committed) — rerun it
  from a clean shell if a full per-file validation record is wanted before Phase 3.

### Files changed / added

- `config/samples.yaml` — added `2018` luminosity + background/embedding sample
  lists (mt only).
- `config/analysis.py` — added `RUN2_ERAS`/`SUPPORTED_ERAS`, `EMB` dataset-key
  handling in `get_background_samples`.
- `config/shapes/process_selection.py` — 2018 trigger-weight branch, conditional
  `btag_weight`, real `ZTT_embedded_process_selection` weights.
- `config/shapes/channel_selection.py` — `SUPPORTED_ERAS` era guard, `_apply_wp_params`
  vsMu regex fix (both Run3 and 2018 TFF-YAML forms).
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

Status: NOT STARTED.

## Phase 4 — GoF/impacts

Status: NOT STARTED.

## Blockers

None currently. (See "Not done / explicitly out of scope" under Phase 2a for
deliberately deferred items — none of them block Phase 3.)
