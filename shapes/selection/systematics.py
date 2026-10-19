import logging

from common.analysis import AR_MASK_BRANCH, SR_MASK_SS_BRANCH
from CustomLogging import setup_logging
from ntuple_processor.utils import Cut, Weight
from ntuple_processor.systematics import (
    ReplaceCut,
    ReplaceCutAndAddWeight,
    ReplaceVariable,
    ReplaceVariableReplaceCutAndAddWeight,
)

logger = setup_logging(logger=logging.getLogger(__name__))

SHIFT_DIRECTIONS = ("Up", "Down")

# CROWN's fake factor weight of the anti-isolated region (fake_factor_2 for et/mt, the failing tau's for tt); its shifts are
# ff_weight__<systematic>Up/Down
FF_WEIGHT = "ff_weight"


# Same-sign QCD control region: the signal region mask swapped for its same-sign variant.
same_sign = ReplaceCut("same_sign", "SR_mask", Cut(f"({SR_MASK_SS_BRANCH} > 0.5)", "SR_mask_ss"))


# The anti-isolated application region of the fake factors: the signal region mask swapped for CROWN's AR_mask (of the
# shifted friend tree for `suffix` = __<shift>).
def _anti_iso(suffix=""):
    return Cut(f"({AR_MASK_BRANCH}{suffix} > 0.5)", "AR_mask")


anti_iso = ReplaceCutAndAddWeight("anti_iso", "SR_mask", _anti_iso(), Weight(FF_WEIGHT, "fake_factor"))


def shape_systematics(syst):
    """Up/Down systematics of a common.systematics.Systematic in the signal region."""
    return [ReplaceVariable(f"{syst.name}{d}", f"{syst.name}{d}") for d in SHIFT_DIRECTIONS]


def anti_iso_systematics(syst):
    """Up/Down systematics of a common.systematics.Systematic in the anti-isolated region, named anti_iso_<shift> as
    shapes/do_estimations.py expects: a shift of the fake factor weight, or a CROWN shift that also moves the anti-iso
    mask and the fake factor weight of the shifted friend trees."""
    if syst.source == "ff":
        return [
            ReplaceCutAndAddWeight(f"anti_iso_{syst.name}{d}", "SR_mask", _anti_iso(), Weight(f"{FF_WEIGHT}__{syst.name}{d}", "fake_factor"))
            for d in SHIFT_DIRECTIONS
        ]
    return [
        ReplaceVariableReplaceCutAndAddWeight(
            f"anti_iso_{syst.name}{d}", f"{syst.name}{d}", "SR_mask", _anti_iso(f"__{syst.name}{d}"), Weight(f"{FF_WEIGHT}__{syst.name}{d}", "fake_factor")
        )
        for d in SHIFT_DIRECTIONS
    ]


# Embedding (Run 2 only), legacy names: vsJet ID SF, its MC-correlated copy and the electron energy scale.
_EMB_TAU_ID_EFF_LT_DMS = ["1prong0pizero", "1prong1pizero", "3prong0pizero", "3prong1pizero"]

emb_tau_id_eff_lt = [
    ReplaceVariable(f"CMS_eff_t_emb_{dm}_{pt}{shift}", f"vsJetTau{dm}{pt}{shift}")
    for dm in _EMB_TAU_ID_EFF_LT_DMS
    for pt in ["20to40", "40toInf"]
    for shift in SHIFT_DIRECTIONS
]

emb_tau_id_eff_lt_corr = [
    ReplaceVariable(f"CMS_eff_t_{dm}_{pt}{shift}", f"vsJetTau{dm}{pt}{shift}")
    for dm in _EMB_TAU_ID_EFF_LT_DMS
    for pt in ["20to40", "40toInf"]
    for shift in SHIFT_DIRECTIONS
]

emb_e_es = [  # TODO Embedding electron scale, check if right
    ReplaceVariable(name, systematic)
    for shift in SHIFT_DIRECTIONS
    for name, systematic in [
        (f"CMS_scale_e_barrel_emb{shift}", f"eleEsBarrel{shift}"),
        (f"CMS_scale_e_endcap_emb{shift}", f"eleEsEndcap{shift}"),
    ]
]
