from ntuple_processor.systematics import ReplaceVariable

from analyses.smhtt.common import stxs_tools


def signal_systematics(stage: str) -> dict:
    """unit -> CROWN's LHEScaleWeight shifts of `weight` for the systematics its `<PROCESS>_<STXS_BIN>` models are in."""
    return {
        unit: [ReplaceVariable(f"{np_name}{shift}", f"{np_name}{shift}") for np_name in stxs_tools.lhe_scale_systematics(info["members"]) for shift in ("Up", "Down")]
        for unit, info in stxs_tools.signal_units(stage).items()
    }
