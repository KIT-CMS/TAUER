from ntuple_processor.systematics import AddWeight
from ntuple_processor.utils import Weight

from analyses.smhtt.common import stxs_tools

# TEMPORARY: W+-H (stxs_family 3, 4) friends carry LHEScaleWeight unnormalised to its central entry, they keep the nominal weight
_LHE_SHIFT = "(stxs_family == 3 || stxs_family == 4 || weight == 0) ? 1.0 : weight__{0} / weight"


def signal_systematics(stage: str) -> dict:
    """unit -> CROWN's LHEScaleWeight shifts of `weight` for the systematics its `<PROCESS>_<STXS_BIN>` models are in, and the
    parton shower shifts ps_{isr,fsr}_<dataset> of each sample it is made of."""
    return {
        unit: [AddWeight(f"{np_name}{shift}", Weight(_LHE_SHIFT.format(f"{np_name}{shift}"), "lhe_scale")) for np_name in stxs_tools.lhe_scale_systematics(info["members"]) for shift in ("Up", "Down")]
        + [AddWeight(f"{np_name}{shift}", Weight(f"ps_weight__{np_name}{shift}", "parton_shower")) for np_name in stxs_tools.parton_shower_systematics(info["datasets"]) for shift in ("Up", "Down")]
        for unit, info in stxs_tools.signal_units(stage).items()
    }
