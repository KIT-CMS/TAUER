"""
tau_es -- tau energy-scale (tauES) measurement: datacard construction + fit.

Phase 6b of the TauKITFlow rewrite (see STATUS.md, "## Phase 6b"). This
package is the *measurement/calculation* half of tauES support -- it turns
already-produced tauES shape files (see below) into a Combine datacard with a
continuous ``taues`` morphing parameter, and runs/orchestrates the actual
fit. It is deliberately separate from the tauES *application* machinery that
already existed in TauKITFlow before this slice:

- ``shapes/utils.py`` (``add_tauES_datasets``/``book_tauES_histograms``) and
  ``shapes/produce_shapes.py --special-analysis TauES`` (Phase 2a) -- these
  produce the per-shift embedded ("emb<shift>") shape templates from CROWN
  ntuples. That is shape *production*, unchanged by this package.
- ``config/shapes/taues_measurement_binning.py`` (Phase 2a) -- the
  DM0/DM1/DM10_11/Inclusive categorization used both by shape production
  above and by this package's datacard step.
- ``tau_es/energy_scales.py`` (new in this slice) -- the single source of
  truth for the tauES shift-point convention (-12.0% to +8.0% in 0.2% steps,
  100 points, 0.0% excluded), which Phase 2a had already validated against
  real data but left duplicated as near-identical inline list comprehensions
  in ``shapes/produce_shapes.py`` and ``shapes/do_estimations.py``. See that
  module's docstring for the single-sourcing fix.

What lives here (naming: "tau_es", not "taues_fit" or "morphing_taues" --
matches the existing ``config/shapes/taues_measurement_binning.py`` naming
and reads as "the tauES calculation", the thing the task asked to extract):

- ``energy_scales.py`` -- canonical shift-point list + naming-convention
  helpers (single-sourced, see above).
- ``make_taues_datacard.py`` -- Python port (via CombineHarvester's Python
  bindings, same approach Phase 2d used for ``combine_datacards/
  make_datacards.py``) of smhtt_ul's ``tauID_SFs_dev``-branch tauES
  measurement pipeline's datacard-construction step. The original C++
  entry point for this (``MorphingSMRun2Legacy_tauES.cpp``) was found on
  CombineHarvester/SMRun2Legacy's ``origin/tauES`` branch (not on
  ``tauID_SFs_dev`` itself, nor on ``run3_htt`` -- see STATUS.md Phase 6b
  for how it was located), analogous to how ``MorphingSMRun2Legacy.cpp``
  used to build the main SM H->tautau datacard before ``run3_htt`` replaced
  it with a pure-Python script.
- ``run_taues_fit.py`` -- Python orchestration of the actual measurement fit
  (``text2workspace.py``/``combineTool.py -M T2W`` then
  ``combine -M MultiDimFit`` with ``taues`` as a floated signal-strength-like
  POI), replacing the bash ``DATACARD``/``FIT``/``POSTFIT`` modes of
  smhtt_ul's ``embeddded_tauES_ul2018.sh`` with Python subprocess calls to
  the same external Combine binaries (Combine/CMSSW themselves stay external
  dependencies, consumed via ``utils/setup_cmssw.sh``, exactly like
  ``combine_datacards/make_datacards.py`` already does -- no C++ vendored in).
"""
