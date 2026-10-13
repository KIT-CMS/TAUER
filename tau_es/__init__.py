"""
tau_es -- tau energy-scale (tauES) measurement: datacard construction + fit.

This package is the *measurement/calculation* half of tauES support -- it turns
already-produced tauES shape files (see below) into a Combine datacard with a
continuous ``taues`` morphing parameter, and runs/orchestrates the actual
fit. It is deliberately separate from the tauES *application* machinery that
already existed in TAUER before this slice:

- ``shapes/utils.py`` (``add_tauES_datasets``/``book_tauES_histograms``) and
  ``shapes/produce_shapes.py --special-analysis TauES`` (Phase 2a) -- these
  produce the per-shift embedded ("emb<shift>") shape templates from CROWN
  ntuples. That is shape *production*, unchanged by this package.
- ``tau_es/taues_measurement_binning.py`` (Phase 2a) -- the
  DM0/DM1/DM10_11/Inclusive categorization used both by shape production
  above and by this package's datacard step.
- ``tau_es/energy_scales.py`` (new in this slice) -- the single source of
  truth for the tauES shift-point convention (-12.0% to +8.0% in 0.2% steps,
  100 points, 0.0% excluded), which Phase 2a had already validated against
  real data but left duplicated as near-identical inline list comprehensions
  in ``shapes/produce_shapes.py`` and ``shapes/do_estimations.py``. See that
  module's docstring for the single-sourcing fix.

What lives here (naming: "tau_es", not "taues_fit" or "morphing_taues" --
matches the existing ``tau_es/taues_measurement_binning.py`` naming
and reads as "the tauES calculation", the thing the task asked to extract):

- ``energy_scales.py`` -- canonical shift-point list + naming-convention helpers.
- ``make_taues_datacard.py`` -- builds the tauES RooMorphing datacard via
  CombineHarvester's Python bindings.
- ``run_taues_fit.py`` -- runs the fit itself (``text2workspace.py``/``combineTool.py -M
  T2W`` then ``combine -M MultiDimFit`` with ``taues`` as a floated POI). Combine/CMSSW stay
  external dependencies, reached via ``utils/setup_cmssw.sh``.
"""
