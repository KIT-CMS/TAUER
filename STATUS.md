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

Status: IN PROGRESS. Sub-slice 2d (below) done; 2a/2b/2c (shape-production condor
submission, friend-tree wiring, etc.) not started by this agent.

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

## Phase 3 — Validation comparators

Status: NOT STARTED. Blocked on real (non-synthetic) shape files — see
"## Blockers".

## Phase 4 — GoF/impacts

Status: NOT STARTED.

## Blockers

1. **Real 2024 shape production crashes on a missing `Jet_vetomap` branch.**
   `shapes/produce_shapes.py --era 2024 --xrootd --directory
   /store/user/sgiappic/CROWN/ntuples/htt_260602_2024-25_v5/CROWNRun
   --gof-inputs ...` fails with `RDataFrame: error: use of undeclared
   identifier 'Jet_vetomap'` during JIT compilation of the (global,
   era/channel-independent) `jet_veto` cut defined in `config/cuts.yaml` /
   `config/shapes/channel_selection.py`. This affects every process
   selection, not just the one tried (`ggh`) — the cut is applied unconditionally.
   Two plausible causes, not distinguished here (out of this slice's scope):
   either this specific CROWN production (`htt_260602_2024-25_v5`) genuinely
   doesn't write a `Jet_vetomap` branch (naming/producer-config mismatch on
   the CROWN side), or `config/cuts.yaml`'s branch name doesn't match what
   this production calls it. Whoever owns shape-production config should
   check `xrdfs` + `TTree::Print()` on one real 2024 file for the actual
   branch name. This blocked full physics-content validation of Phase 2d
   (worked around with a synthetic shape file, documented above) and will
   block Phase 3's real bin-by-bin comparator until fixed.
2. **`convert_to_synced_shapes.py` referenced but never found.** SMRun2Legacy's
   original `categories.py` comment ("Category names match
   convert_to_synced_shapes.py output") implies a per-category shape-file-
   splitting step between shape production and `stxs_stage0_run3` datacard
   production. Grepped the whole filesystem (`find / -iname
   "convert_to_synced_shapes*"`) — does not exist anywhere accessible,
   including in the SMRun2Legacy checkout itself (would have lived in the now-
   merged-into-TauKITFlow smhtt_ul). Blocks `--categories stxs_stage0_run3`
   end-to-end use until either found (if it exists in a smhtt_ul checkout not
   examined here) or written fresh.
3. **`config/shapes/category_selection.py` lacks `DNN_CLASS_MAPPING`** (see
   Phase 2d above) — blocks `--categories stxs_stage0_run3` specifically;
   `gof`/`stxs_stage0` are unaffected.
