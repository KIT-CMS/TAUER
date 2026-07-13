"""
Backward-compatibility shim.

Signal samples have moved to config/analysis.SIGNAL_SAMPLES.
Existing imports of the form::

    from config.shapes.signal_files import signal_files

continue to work unchanged.
"""
from config.analysis import SIGNAL_SAMPLES as signal_files  # noqa: F401

__all__ = ["signal_files"]

signal_files: dict[str, dict[str, list[str]]] = {
    "2022preEE": {
        "ggH": [
            "GluGluHTo2TauUncorrelatedDecay_Filtered_M-125_CP5_13p6TeV_powheg-pythia8_Run3Summer22NanoAODv12-130X",
        ],
        "qqH": [
            "VBFHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-pythia8_Run3Summer22NanoAODv12-130X",
        ],
        "VH": [
            "WminusHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-minnlo-pythia8_Run3Summer22NanoAODv12-130X",
            "WplusHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-minnlo-pythia8_Run3Summer22NanoAODv12-130X",
        ],
        "ttH": [
            "TTHtoNon2B_M-125_TuneCP5_13p6TeV_powheg-pythia8_Run3Summer22NanoAODv12-130X",
        ],
    },
    "2022postEE": {
        "ggH": [
            "GluGluHTo2TauUncorrelatedDecay_Filtered_M-125_CP5_13p6TeV_powheg-pythia8_Run3Summer22EENanoAODv12-130X",
        ],
        "qqH": [
            "VBFHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-pythia8_Run3Summer22EENanoAODv12-130X",
        ],
        "VH": [
            "WminusHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-minnlo-pythia8_Run3Summer22EENanoAODv12-130X",
            "WplusHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-minnlo-pythia8_Run3Summer22EENanoAODv12-130X",
        ],
        "ttH": [
            "TTHtoNon2B_M-125_TuneCP5_13p6TeV_powheg-pythia8_Run3Summer22EENanoAODv12-130X",
        ],
    },
    "2023preBPix": {
        "ggH": [
            "GluGluHTo2TauUncorrelatedDecay_Filtered_M-125_CP5_13p6TeV_powheg-pythia8_Run3Summer23NanoAODv12-130X",
        ],
        "qqH": [
            "VBFHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-pythia8_Run3Summer23NanoAODv12-130X",
        ],
        "VH": [
            "WminusHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-minnlo-pythia8_Run3Summer23NanoAODv12-130X",
            "WplusHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-minnlo-pythia8_Run3Summer23NanoAODv12-130X",
        ],
        "ttH": [
            "TTHtoNon2B_M-125_TuneCP5_13p6TeV_powheg-pythia8_Run3Summer23NanoAODv12-130X",
        ],
    },
    "2023postBPix": {
        "ggH": [
            "GluGluHTo2TauUncorrelatedDecay_Filtered_M-125_CP5_13p6TeV_powheg-pythia8_Run3Summer23BPixNanoAODv12-130X",
        ],
        "qqH": [
            "VBFHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-pythia8_Run3Summer23BPixNanoAODv12-130X",
        ],
        "VH": [
            "WminusHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-minnlo-pythia8_Run3Summer23BPixNanoAODv12-130X",
            "WplusHTo2TauUncorrelatedDecay_Filtered_M-125_TuneCP5_13p6TeV_powheg-minnlo-pythia8_Run3Summer23BPixNanoAODv12-130X",
        ],
        "ttH": [
            "TTHtoNon2B_M-125_TuneCP5_13p6TeV_powheg-pythia8_Run3Summer23BPixNanoAODv12-130X",
        ],
    },
    "2024": {
        "ggH": [
            "GluGluH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_TuneCP5_13p6TeV_powheg-pythia8_RunIII2024Summer24NanoAODv15-150X",
        ],
        "qqH": [
            "VBFH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_TuneCP5_13p6TeV_powheg-pythia8_RunIII2024Summer24NanoAODv15-150X",
        ],
        "VH": [
            "WminusH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_TuneCP5_13p6TeV_powhegMINNLO-pythia8_sgiappic-RunIII2024Summer24NanoAODv15_ReNano-00000000000000000000000000000000",
            "WplusH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_TuneCP5_13p6TeV_powhegMINNLO-pythia8_RunIII2024Summer24NanoAODv15-150X",
        ],
        "ttH": [
            "TTH-HtoNon2B_Par-M-125_TuneCP5_13p6TeV_powheg-pythia8_sgiappic-RunIII2024Summer24NanoAODv15_ReNano-00000000000000000000000000000000",
        ],
    },
    "2025": {
        "ggH": [
            "GluGluH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_TuneCP5_13p6TeV_powheg-pythia8_RunIII2025Summer24NanoAODv15-150X",
        ],
        "qqH": [
            "VBFH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_TuneCP5_13p6TeV_powheg-pythia8_RunIII2025Summer24NanoAODv15-150X",
        ],
        "VH": [
            "WminusH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_TuneCP5_13p6TeV_powhegMINNLO-pythia8_sgiappic-RunIII2025Summer24NanoAODv15_ReNano-00000000000000000000000000000000",
            "WplusH-Hto2TauUncorrelatedDecay_Fil-TauFilter_Par-M-125_TuneCP5_13p6TeV_powhegMINNLO-pythia8_RunIII2025Summer24NanoAODv15-150X",
        ],
        "ttH": [
            "TTH-HtoNon2B_Par-M-125_TuneCP5_13p6TeV_powheg-pythia8_sgiappic-RunIII2025Summer24NanoAODv15_ReNano-00000000000000000000000000000000",
        ],
    },
}
