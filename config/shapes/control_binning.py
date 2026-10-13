import importlib

from ntuple_processor import Histogram
import numpy as np
from typing import Any, Dict, Union
from common.helper_collection import ObjBuildingDict
from config.analysis import ACTIVE_ANALYSIS


class HistogramBuildingDict(ObjBuildingDict):

    def __init__(self, *args: Any, **kwargs: Dict[str, Any]):
        super().__init__(*args, obj=Histogram, **kwargs)

    def build_obj(self, key: str, value: Union[np.ndarray, list]) -> Histogram:
        if isinstance(value, (np.ndarray, list)):
            return self.obj(key, key, value)
        else:
            raise ValueError(f"Value for key {key} is not a list or numpy array")


common_binning = HistogramBuildingDict(
    {
        "mass_1": np.arange(0, 2.1, 0.1),
        "mass_2": np.arange(0, 2.1, 0.1),
        "deltaR_ditaupair": np.arange(0, 5.2, 0.2),
        "mTdileptonMET": np.arange(0, 200, 4),
        "pzetamissvis": np.arange(-150, 150, 5),
        "m_vis": np.linspace(0, 256, 33),
        "mt_tot": np.arange(0, 305, 8),
        "pt_1": np.arange(0, 165, 5),
        "pt_2": np.arange(0, 165, 5),
        "eta_1": np.arange(-2.5, 2.6, 0.6),
        "eta_2": np.arange(-2.5, 2.6, 0.6),
        "jpt_1": np.arange(0, 165, 5),
        "jpt_2": np.arange(0, 165, 5),
        "jeta_1": np.linspace(-5, 5, 50),
        "jeta_2": np.linspace(-5, 5, 50),
        "jphi_1": np.linspace(-np.pi, np.pi, 50),
        "jphi_2": np.linspace(-np.pi, np.pi, 50),
        "njets": np.arange(-0.5, 7.5, 1),
        "nbtag": np.arange(-0.5, 7.5, 1),
        "tau_decaymode_1": np.arange(-0.5, 12.5, 1),
        "tau_decaymode_2": np.arange(-0.5, 12.5, 1),
        "jet_hemisphere": [-0.5, 0.5, 1.5],
        "mt_1": np.arange(0, 160, 5),
        "mt_2": np.arange(0, 160, 5),
        "pt_vis": np.arange(0, 165, 5),
        "pt_tt": np.arange(0, 165, 5),
        "pt_dijet": np.arange(0, 165, 5),
        "pt_ttjj": np.arange(0, 160, 5),
        "mjj": np.arange(0, 300, 10),
        "dxy_1": np.linspace(-1, 1, 50),
        "dxy_2": np.linspace(-1, 1, 50),
        "dz_1": np.linspace(-1, 1, 50),
        "dz_2": np.linspace(-1, 1, 50),
        "puppimet": np.arange(0, 160, 5),
        "puppimet_norec": np.arange(0, 160, 5),
        "metSumEt": np.arange(0, 360, 5),
        "iso_1": np.linspace(0, 0.3, 50),
        "iso_2": np.linspace(0, 1.0, 50),
        "bpt_1": np.arange(0, 170, 10),
        "bpt_2": np.arange(0, 160, 5),
        "beta_1": np.linspace(-5, 5, 20),
        "beta_2": np.linspace(-5, 5, 20),
        "bphi_1": np.linspace(-np.pi, np.pi, 50),
        "bphi_2": np.linspace(-np.pi, np.pi, 50),
        "btag_value_1": np.linspace(0, 1, 50),
        "btag_value_2": np.linspace(0, 1, 50),
        "deltaEta_ditaupair": np.linspace(-10, 10, 20),
        "deltaPhi_ditaupair": np.linspace(-2 * np.pi, 2 * np.pi, 20),
        "deltaR_jj": np.arange(0, 6, 0.2),
        "deltaR_1j1": np.arange(0, 6, 0.2),
        "deltaR_1j2": np.arange(0, 6, 0.2),
        "deltaR_2j1": np.arange(0, 6, 0.2),
        "deltaR_2j2": np.arange(0, 6, 0.2),
        "deltaR_12j1": np.arange(0, 6, 0.2),
        "deltaR_12j2": np.arange(0, 6, 0.2),
        "deltaR_12jj": np.arange(0, 6, 0.2),
        "deltaEta_jj": np.arange(-9, 9, 0.6),
        "deltaEta_1j1": np.arange(-9, 9, 0.6),
        "deltaEta_1j2": np.arange(-9, 9, 0.6),
        "deltaEta_2j1": np.arange(-9, 9, 0.6),
        "deltaEta_2j2": np.arange(-9, 9, 0.6),
        "deltaEta_12j1": np.arange(-9, 9, 0.6),
        "deltaEta_12j2": np.arange(-9, 9, 0.6),
        "deltaEta_12jj": np.arange(-9, 9, 0.6),
        "deltaPhi_jj": np.arange(-2 * np.pi, 2 * np.pi, 0.6),
        "deltaPhi_1j1": np.arange(-2 * np.pi, 2 * np.pi, 0.6),
        "deltaPhi_1j2": np.arange(-2 * np.pi, 2 * np.pi, 0.6),
        "deltaPhi_2j1": np.arange(-2 * np.pi, 2 * np.pi, 0.6),
        "deltaPhi_2j2": np.arange(-2 * np.pi, 2 * np.pi, 0.6),
        "deltaPhi_12j1": np.arange(-2 * np.pi, 2 * np.pi, 0.6),
        "deltaPhi_12j2": np.arange(-2 * np.pi, 2 * np.pi, 0.6),
        "deltaPhi_12jj": np.arange(-2 * np.pi, 2 * np.pi, 0.6),
        # fastmtt variables
        "m_fastmtt": np.arange(0, 225, 5),
        "pt_fastmtt": np.arange(0, 160, 5),
        "eta_fastmtt": np.linspace(-2.5, 2.5, 50),
        "phi_fastmtt": np.linspace(-np.pi, np.pi, 50),
        "npartons": np.arange(-0.5, 7.5, 1),
        "phi_1": np.linspace(-2.5, 2.5, 25),
        "phi_2": np.linspace(-2.5, 2.5, 25),
        "q_1": [-4, 4],  # for overall yield
    }
)

try:
    _analysis_binning = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.config.shapes.control_binning")
    common_binning.update(getattr(_analysis_binning, "EXTRA_BINNING", {}))
except ModuleNotFoundError:
    pass

control_binning = {ch: common_binning for ch in ["et", "mt", "tt", "em", "ee", "mm"]}
