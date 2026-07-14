"""
Categorization for tau energy-scale (tauES) measurement shape production.

Ported from smhtt_ul's tauID_SFs_dev branch
(config/shapes/taues_measurement_binning.py), mt channel only — the only
channel this analysis's embedded tauES fit covers today, and the only one
covered by the Phase 2a validation dataset.

One change from the smhtt_ul original: the decay-mode branch is named
`tau_decaymode_2` in this repo's CROWN ntuples (Run3 and the 2018 Phase 2a
validation production alike — confirmed via `config/cuts.yaml` and a direct
branch listing of the real 2018 ntuples), not `decaymode_2`.
"""
import numpy as np
from ntuple_processor.utils import Selection
from ntuple_processor import Histogram

discriminator_variable = "m_vis"
discriminator_binning = np.arange(35, 85, 2.5)


categories = {
    "mt": {
        "DM0": {
            "var": discriminator_variable,
            "bins": discriminator_binning,
            "expression": discriminator_variable,
            "cut": "(tau_decaymode_2 == 0)",
        },
        "DM1": {
            "var": discriminator_variable,
            "bins": discriminator_binning,
            "expression": discriminator_variable,
            "cut": "(tau_decaymode_2 == 1)",
        },
        "DM10_11": {
            "var": discriminator_variable,
            "bins": discriminator_binning,
            "expression": discriminator_variable,
            "cut": "(tau_decaymode_2 == 11 || tau_decaymode_2 == 10)",
        },
        "Inclusive": {
            "var": discriminator_variable,
            "bins": discriminator_binning,
            "expression": discriminator_variable,
            "cut": "(pt_2 >= 20)",
        },
    }
}

categorization = {
    "mt": [
        (
            Selection(
                name=x, cuts=[(categories["mt"][x]["cut"], "category_selection")]
            ),
            [
                Histogram(
                    categories["mt"][x]["var"],
                    categories["mt"][x]["expression"],
                    categories["mt"][x]["bins"],
                )
            ],
        )
        for x in categories["mt"]
    ]
}
