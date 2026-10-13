"""
Categorization for tau energy-scale (tauES) measurement shape production.

mt channel only -- the only channel this analysis's embedded tauES fit covers today.
Decay-mode categorization reads the `tau_decaymode_2` branch (this repo's CROWN ntuples,
Run3 and 2018 alike).
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
