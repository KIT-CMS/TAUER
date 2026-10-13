"""
Binning used for goodness-of-fit (GoF) shape production (shapes/produce_shapes.py
``--gof-inputs``).

STUB: delegates to the same binning used for control plots (control_binning.py) rather
than a dedicated GoF-tuned binning. Replace with real per-variable GoF binning if needed;
nothing downstream (datacard production) assumes any particular granularity.
"""
from config.shapes.control_binning import control_binning


def load_gof_binning(era, channel):
    return control_binning
