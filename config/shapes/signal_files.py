"""
Backward-compatibility shim.

Signal samples live in config/samples.yaml, loaded via config.analysis.SIGNAL_SAMPLES.
Existing imports of the form::

    from config.shapes.signal_files import signal_files

continue to work unchanged.
"""
from config.analysis import SIGNAL_SAMPLES as signal_files  # noqa: F401

__all__ = ["signal_files"]
