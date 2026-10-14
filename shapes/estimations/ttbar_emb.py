import logging

import shapes.naming as naming
from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def emb_ttbar_contamination_estimation(rootfile, channel, category, variable, era_tag, sub_scale=0.1, process="EMB"):
    """EMB with -/+ sub_scale of the genuine-tau ttbar removed, as the CMS_htt_emb_ttbar Down/Up shift of `process`."""
    base_hist = naming.get(rootfile, variable, channel, process, category).Clone()
    base_hist.Add(naming.get(rootfile, variable, channel, "TTT", category), -sub_scale)
    shift = f"CMS_htt_emb_ttbar_{era_tag}{'Down' if sub_scale > 0 else 'Up'}"
    return base_hist, naming.path(variable, channel, process, category, systematic=shift)
