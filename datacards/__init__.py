"""
datacards -- TAUER's CombineHarvester datacard construction (make_datacards.py with categories/systematics/tools,
run inside CMSSW) and the CLI wrappers that enter the CMSSW environment for it and run Combine (produce_datacard.py,
produce_workspace.py, run_gof.py, run_impacts.py). CombineHarvester/Combine stay external, see utils/setup_cmssw.sh.
"""
import importlib
from pathlib import Path

from config.analysis import ACTIVE_ANALYSIS

DEFAULT_NTUPLE_TAG = "htt_260602_2024-25_v5"

try:
    MASS = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.datacards.combine_model").MASS
except (ModuleNotFoundError, AttributeError):
    MASS = "125"


def gof_card_dir(fitdir, era: str, channel: str, variable: str) -> Path:
    """Directory of the GoF datacard and workspace of one era/channel/variable (make_datacards.py's {channel}/{era} layout)."""
    return Path(fitdir) / "output" / "datacards" / f"{era}-{channel}-{variable}-gof" / channel / era
