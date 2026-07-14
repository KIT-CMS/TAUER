"""
Binning used for goodness-of-fit (GoF) shape production (shapes/produce_shapes.py
``--gof-inputs``).

STUB, added as part of Phase 2d (datacard-code relocation, see STATUS.md) purely
to unblock end-to-end validation of the relocated combine_datacards/ code: this
was a missing import (config.shapes.gof_binning did not exist at all -- a real
gap in shape-production config, not a datacard-side issue) that made
``--gof-inputs`` crash before it could produce any shape file to feed into
datacard production.

Today this just delegates to the same binning used for control plots
(config/shapes/control_binning.py) -- i.e. GoF shapes get produced with the
regular control-plot binning per variable, rather than a dedicated
(finer/coarser, GoF-tuned) binning. Whoever owns the GoF shape-production
config should replace this with real per-variable GoF binning if a different
binning is actually needed there; nothing downstream (datacard production)
assumes any particular binning granularity.
"""
from config.shapes.control_binning import control_binning


def load_gof_binning(era, channel):
    """Return the {channel: {variable: binning}} dict used for GoF shapes.

    era is accepted (and ignored) for interface compatibility with a possible
    future era-dependent GoF binning -- today's binning is era-independent,
    same as config/shapes/control_binning.py.
    """
    return control_binning
