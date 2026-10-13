from shapes.selection.process_selection import HTT_process_selection

from analyses.smhtt.common import stxs_tools


def signal_selection(stage: str, unit: str):
    """Process selection of one signal unit of `stxs_tools.signal_units(stage)`, named after its histogram process."""
    info = stxs_tools.signal_units(stage)[unit]

    def selection(**kwargs):
        return HTT_process_selection(info["selection"], info["cut"])

    selection.__name__ = f"{stage}_{unit}_process_selection"
    return selection
