import logging
from .defaults import _name_string, _process_map, _dataset_map

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def emb_ttbar_contamination_estimation(
    rootfile, channel, category, variable, era_tag, sub_scale=0.1, embname="EMB"
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
                    systematic="Nominal",
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
                systematic="Nominal",
                variable=variable,
            )
        ).Clone()
    else:
        logger.debug(
            "Trying to get object {}".format(
                _name_string.format(
                    dataset=embname,
                    channel=channel,
                    process="-EMB",
                    selection=category,
                    systematic="Nominal",
                    variable=variable,
                )
            )
        )
        base_hist = rootfile.Get(
            _name_string.format(
                dataset=embname,
                channel=channel,
                process="-EMB",
                selection="-" + category if category != "" else "",
                systematic="Nominal",
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
                    systematic="Nominal",
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
                    systematic="Nominal",
                    variable=variable,
                )
            ),
            -sub_scale,
        )
        if sub_scale > 0:
            systematic_name = base_hist.GetName().replace(
                "Nominal", f"CMS_htt_emb_ttbar_{era_tag}Down"
            )
        else:
            systematic_name = base_hist.GetName().replace(
                "Nominal", f"CMS_htt_emb_ttbar_{era_tag}Up"
            )
        base_hist.SetName(systematic_name)
        base_hist.SetTitle(systematic_name)
    return base_hist
