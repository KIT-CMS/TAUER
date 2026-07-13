from ntuple_processor import Histogram
import numpy as np
from typing import Any, Dict, Union
from config.helper_collection import ObjBuildingDict


class HistogramBuildingDict(ObjBuildingDict):
    """
    Constructing Histogram objects from raw data arrays using `Histogram(tag, name, value)`.

    Assumption: each key in the dictionary corresponds to a Histogram or bin edges,
    either as a list or numpy array.
    """

    def __init__(self, *args: Any, **kwargs: Dict[str, Any]):
        super().__init__(*args, obj=Histogram, **kwargs)

    def build_obj(self, key: str, value: Union[np.ndarray, list]) -> Histogram:
        """
        Build a Histogram object for the given key from the raw data using
        `Histogram(tag, name, value)` constructor.

        Parameters
        ----------
        key : str
            The key associated with the histogram.
        value : Union[np.ndarray, list]
            The raw data, which must be either a numpy array or a list of values.

        Returns
        -------
        Histogram
            A new Histogram object built from the provided data.
        """
        if isinstance(value, (np.ndarray, list)):
            return self.obj(key, key, value)
        else:
            raise ValueError(f"Value for key {key} is not a list or numpy array")


common_binning = HistogramBuildingDict(
    {
        "mass_1": np.arange(0, 2.1, 0.1),
        "mass_2": np.arange(0, 2.1, 0.1),
        "genbosonpt": np.arange(0, 150, 10),
        "deltaR_ditaupair": np.arange(0, 5.2, 0.2),
        "mTdileptonMET_puppi": np.arange(0, 200, 4),
        "mTdileptonMET": np.arange(0, 200, 4),
        "pzetamissvis": np.arange(-150, 150, 5),
        "pzetamissvis_pf": np.arange(-150, 150, 5),
        "m_sv_puppi": np.arange(0, 225, 5),
        "pt_sv_puppi": np.arange(0, 160, 5),
        "eta_sv_puppi": np.arange(-2.5, 2.6, 0.1),
        "m_vis": np.linspace(0, 256, 33),
        "ME_q2v1": np.arange(0, 300000, 6000),
        "ME_q2v2": np.arange(0, 300000, 6000),
        "ME_costheta1": np.linspace(-1, 1, 50),
        "ME_costheta2": np.linspace(-1, 1, 50),
        "ME_costhetastar": np.linspace(-1, 1, 50),
        "ME_phi": np.linspace(-np.pi, np.pi, 50),
        "ME_phi1": np.linspace(-np.pi, np.pi, 50),
        "pfmetphi": np.linspace(-np.pi, np.pi, 50),
        "metphi": np.linspace(-np.pi, np.pi, 25),
        "metphi_uncorrected": np.linspace(-np.pi, np.pi, 50),
        "mt_tot": np.arange(0, 305, 8),
        "mt_tot_puppi": np.arange(0, 305, 8),
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
        "jdeta": np.arange(0, 6, 0.6),
        "njets": np.arange(-0.5, 7.5, 1),
        "nbtag": np.arange(-0.5, 7.5, 1),
        "tau_decaymode_1": np.arange(-0.5, 12.5, 1),
        "tau_decaymode_2": np.arange(-0.5, 12.5, 1),
        "jet_hemisphere": [-0.5, 0.5, 1.5],
        "rho": np.arange(0, 100, 2),
        "m_1": np.linspace(0, 3, 50),
        "m_2": np.linspace(0, 3, 50),
        "mt_1": np.arange(0, 160, 5),
        "mt_2": np.arange(0, 160, 5),
        "mt_1_pf": np.arange(0, 160, 5),
        "mt_2_pf": np.arange(0, 160, 5),
        "pt_vis": np.arange(0, 165, 5),
        "pt_tt": np.arange(0, 165, 5),
        "pt_dijet": np.arange(0, 165, 5),
        "pt_tt_pf": np.arange(0, 160, 5),
        "pt_ttjj": np.arange(0, 160, 5),
        "mjj": np.arange(0, 300, 10),
        "dxy_1": np.linspace(-1, 1, 50),
        "dxy_2": np.linspace(-1, 1, 50),
        "dz_1": np.linspace(-1, 1, 50),
        "dz_2": np.linspace(-1, 1, 50),
        "met": np.arange(0, 160, 5),
        "met_raw": np.arange(0, 160, 5),
        "TypeIMET_pt": np.arange(0, 160, 5),
        "met_uncorrected": np.arange(0, 160, 5),
        "met_p4_jetcorrected_pt": np.arange(0, 160, 5),
        "met_p4_jetcorrected_pt_1": np.arange(0, 160, 5),
        "metSumEt": np.arange(0, 360, 5),
        "pfmet": np.concatenate((np.arange(0, 160, 5), [200, 400])),
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
        "Jet_rawPt": np.arange(0, 165, 5),
        "Jet_pt_corrected": np.arange(0, 165, 5),
        "Jet_pt": np.arange(0, 165, 5),
        "Jet_eta": np.linspace(-5, 5, 50),
        "Jet_phi": np.linspace(-5, 5, 50),
        "CorrT1METJet_rawPt": np.arange(0, 165, 5),
        "CorrT1METJet_eta": np.linspace(-5, 5, 50),
        "CorrT1METJet_phi": np.linspace(-5, 5, 50),
        "HTXS_stage1_2_cat_pTjet25GeV": np.linspace(100,118,19),
        "HTXS_stage1_2_cat_pTjet30GeV": np.linspace(100,118,19),
        "HTXS_stage1_2_fine_cat_pTjet25GeV": np.linspace(100,128,29),
        "HTXS_stage1_2_fine_cat_pTjet30GeV": np.linspace(100,128,29),
    }
)

control_binning = {ch: common_binning for ch in ["et", "mt", "tt", "em", "ee", "mm"]}
