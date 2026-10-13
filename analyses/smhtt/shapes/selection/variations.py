from ntuple_processor.variations import ReplaceVariable

from analyses.smhtt.common import stxs_tools


def signal_variations(stage: str) -> dict:
    """unit -> CROWN's LHEScaleWeight shifts of `weight` for the nuisances its `<PROCESS>_<STXS_BIN>` models are in."""
    return {
        unit: [ReplaceVariable(f"{np_name}{shift}", f"{np_name}{shift}") for np_name in stxs_tools.lhe_scale_nuisances(info["members"]) for shift in ("Up", "Down")]
        for unit, info in stxs_tools.signal_units(stage).items()
    }
