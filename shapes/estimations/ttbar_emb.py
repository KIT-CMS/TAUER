import logging
import ROOT
from .defaults import _name_string, _process_map, _dataset_map

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def emb_ttbar_contamination_estimation(
    rootfile, channel, category, variable, sub_scale=0.1, embname="EMB"
):
    procs_to_subtract = ["TTT"]
    if embname == "EMB":
        logger.debug(
            "Trying to get object {}".format(
                _name_string.format(
                    dataset=_dataset_map[embname],
                    channel=channel,
                    process="-" + _process_map[embname],
                    selection=category,
                    variation="Nominal",
                    variable=variable,
                )
            )
        )
        base_hist = rootfile.Get(
            _name_string.format(
                dataset=_dataset_map[embname],
                channel=channel,
                process="-" + _process_map[embname],
                selection="-" + category if category != "" else "",
                variation="Nominal",
                variable=variable,
            )
        ).Clone()
    else:
        logger.debug(
            "Trying to get object {}".format(
                _name_string.format(
                    dataset=embname,
                    channel=channel,
                    process="-Embedded",
                    selection=category,
                    variation="Nominal",
                    variable=variable,
                )
            )
        )
        base_hist = rootfile.Get(
            _name_string.format(
                dataset=embname,
                channel=channel,
                process="-Embedded",
                selection="-" + category if category != "" else "",
                variation="Nominal",
                variable=variable,
            )
        ).Clone()
    for proc in procs_to_subtract:
        logger.debug(
            "Trying to fetch root histogram {}".format(
                _name_string.format(
                    dataset=_dataset_map[proc],
                    channel=channel,
                    process="-" + _process_map[proc],
                    selection=category,
                    variation="Nominal",
                    variable=variable,
                )
            )
        )
        base_hist.Add(
            rootfile.Get(
                _name_string.format(
                    dataset=_dataset_map[proc],
                    channel=channel,
                    process="-" + _process_map[proc],
                    selection="-" + category if category != "" else "",
                    variation="Nominal",
                    variable=variable,
                )
            ),
            -sub_scale,
        )
        if sub_scale > 0:
            variation_name = base_hist.GetName().replace(
                "Nominal", "CMS_htt_emb_ttbar_EraDown"
            )
        else:
            variation_name = base_hist.GetName().replace(
                "Nominal", "CMS_htt_emb_ttbar_EraUp"
            )
        base_hist.SetName(variation_name)
        base_hist.SetTitle(variation_name)
    return base_hist
