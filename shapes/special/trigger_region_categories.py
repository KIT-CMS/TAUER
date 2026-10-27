"""
Categorization for trigger-region data/MC control plots ("TriggerRegions"), et/mt/tt, Run 3 only. Same
structure and variable set as shapes/special/njets_control_categories.py, but split by the offline pt
thresholds of KingMaker/CROWN/analysis_configurations/tau/tau_triggersetup.py on top of SR_mask:

- trg_cross:  only the cross trigger can fire (et/mt: lepton below the single-lepton threshold; tt: one tau
              below the ditau threshold, i.e. only DiTau+Jet)
- trg_single: the single-lepton (et/mt) or plain ditau (tt) trigger region, cross trigger may overlap

Era dependent (tt thresholds change in 2024), so `categorization(era)` is a function, unlike njets.
"""
from common.analysis import RUN3_ERAS
from common.binning import build_categorization
from common.binning import control_binning
from shapes.special.njets_control_categories import _variables_for

_HPS_ERAS = ("2022preEE", "2022postEE", "2023preBPix", "2023postBPix")


def _regions(era):
    ditau, ditaujet = (40, 35) if era in _HPS_ERAS else (35, 30)
    return {
        "mt": {
            "trg_cross": "(pt_1 >= 20 && pt_1 < 26 && pt_2 >= 32)",
            "trg_single": "(pt_1 >= 26)",
        },
        "et": {
            "trg_cross": "(pt_1 >= 25 && pt_1 < 32 && pt_2 >= 35)",
            "trg_single": "(pt_1 >= 32)",
        },
        "tt": {
            "trg_cross": f"(pt_1 >= {ditaujet} && pt_2 >= {ditaujet} && (pt_1 < {ditau} || pt_2 < {ditau}) && jpt_1 >= 65)",
            "trg_single": f"(pt_1 >= {ditau} && pt_2 >= {ditau})",
        },
    }


def categorization(era):
    if era not in RUN3_ERAS:
        raise ValueError(f"TriggerRegions is only implemented for Run 3 eras {RUN3_ERAS}; got era={era!r}.")
    return build_categorization(
        {channel: {region: (cut, [control_binning[channel][variable] for variable in _variables_for(channel)]) for region, cut in regions.items()} for channel, regions in _regions(era).items()}
    )
