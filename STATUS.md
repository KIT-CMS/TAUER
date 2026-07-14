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

Status: STARTING. Not yet validated against 2024 dataset.

## Phase 2 — Vertical slices

Status: NOT STARTED (blocked on Phase 1 validation).

## Phase 3 — Validation comparators

Status: NOT STARTED.

## Phase 4 — GoF/impacts

Status: NOT STARTED.

## Blockers

None currently.
