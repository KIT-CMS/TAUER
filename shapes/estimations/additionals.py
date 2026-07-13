import logging
import ROOT
from .defaults import _name_string, _process_map, _dataset_map


logger = logging.getLogger("")

def qqH_merge_estimation(rootfile, channel, selection, variable, variation="Nominal"):
    procs_to_add = ["qqH125", "ZH125", "WH125"]
    logger.debug(
        "Trying to get object {}".format(
            _name_string.format(
                dataset=_dataset_map[procs_to_add[0]],
                channel=channel,
                process="-" + _process_map[procs_to_add[0]],
                selection="-" + selection if selection != "" else "",
                variation=variation,
                variable=variable,
            )
        )
    )
    base_hist = (
        rootfile.Get(
            _name_string.format(
                dataset=_dataset_map[procs_to_add[0]],
                channel=channel,
                process="-" + _process_map[procs_to_add[0]],
                selection="-" + selection if selection != "" else "",
                variation=variation,
                variable=variable,
            )
        )
    ).Clone()
    for proc in procs_to_add[1:]:
        logger.debug(
            "Trying to get object {}".format(
                _name_string.format(
                    dataset=_dataset_map[proc],
                    channel=channel,
                    process="-" + _process_map[proc],
                    selection="-" + selection if selection != "" else "",
                    variation=variation,
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
                    selection="-" + selection if selection != "" else "",
                    variation=variation,
                    variable=variable,
                )
            )
        )
    proc_name = "qqHComb125"
    variation_name = base_hist.GetName().replace(
        _process_map[procs_to_add[0]], proc_name
    )
    base_hist.SetName(variation_name)
    base_hist.SetTitle(variation_name)
    return base_hist