"""
Channel selection: CROWN's friend `SR_mask` (triggers, tau ID, isolation, vetoes, OS) for et/mt/tt/em, or
`SR_mask_ss` for the same-sign QCD control region. The anti-isolated region is `AR_mask` of the friend, swapped in by
the systematics of shapes/selection/systematics.py.
"""
import logging

from ntuple_processor.utils import Selection, WarnDict
from config.logging_setup_configs import setup_logging
from config.analysis import SR_MASK_BRANCH, SUPPORTED_ERAS

logger = setup_logging(logger=logging.getLogger(__name__))


def channel_selection(channel: str, era: str, special=None, **kwargs) -> Selection:
    if era not in SUPPORTED_ERAS:
        raise ValueError(f"Era '{era}' is not a supported era. Supported: {SUPPORTED_ERAS}")
    if special not in (None, "TauES"):
        raise NotImplementedError(f"special={special!r} not implemented for channel_selection.")
    if channel not in ("mt", "et", "tt", "em"):
        raise ValueError(f"Channel '{channel}' is not supported (et, mt, tt, em).")
    return Selection(name=channel, cuts=WarnDict({"SR_mask": f"({SR_MASK_BRANCH} > 0.5)"}))
