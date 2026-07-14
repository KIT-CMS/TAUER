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

Status: IN PROGRESS.

### Phase 2c — HTCondor submission for shapes/plotting/training

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

## Phase 3 — Validation comparators

Status: NOT STARTED.

## Phase 4 — GoF/impacts

Status: NOT STARTED.

## Blockers

None currently.
