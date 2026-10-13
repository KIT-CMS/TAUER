import logging

from shapes.estimations.defaults import _name_string, _process_map, _dataset_map


logger = logging.getLogger("")

_qqh_dataset_map = {**_dataset_map, "qqH_htt125": "qqH", "VH_as_qqH125": "VH"}
_qqh_process_map = {**_process_map, "qqH_htt125": "qqH_htt125", "VH_as_qqH125": "qqH_htt125"}


def _get_qqh_component_hist(rootfile, proc, channel, selection, variable, variation):
    name = _name_string.format(
        dataset=_qqh_dataset_map[proc],
        channel=channel,
        process="-" + _qqh_process_map[proc],
        selection="-" + selection if selection != "" else "",
        variation=variation,
        variable=variable,
    )
    hist = rootfile.Get(name)
    if hist:
        return hist
    if variation != "Nominal":
        logger.debug(
            "No %s for %s, falling back to Nominal for the qqH merge", variation, name
        )
        return _get_qqh_component_hist(
            rootfile, proc, channel, selection, variable, "Nominal"
        )
    raise KeyError(f"Missing Nominal histogram {name} needed for the qqH merge")


def qqh_merge_estimation(rootfile, channel, selection, variable, variation="Nominal"):
    procs_to_add = ["qqH_htt125", "VH_as_qqH125"]
    base_hist = _get_qqh_component_hist(
        rootfile, procs_to_add[0], channel, selection, variable, variation
    ).Clone()
    for proc in procs_to_add[1:]:
        base_hist.Add(
            _get_qqh_component_hist(
                rootfile, proc, channel, selection, variable, variation
            )
        )
    return base_hist


def parse_histograms_for_qqh(inputfile):
    from shapes.do_estimations import add_input_to_inputdict

    qqh_procs = {}
    for key in inputfile.GetListOfKeys():
        dataset, selection, variation, variable = key.GetName().split("#")
        if dataset in ["qqH", "VH"]:
            sel_split = selection.split("-", maxsplit=1)
            category = ""
            if "data" in dataset:
                channel = sel_split[0]
                if len(sel_split) > 1:
                    category = sel_split[1]
                process = "data"
            else:
                channel = sel_split[0]
                process, _, category = sel_split[1].partition("-")
            if category == "":
                continue
            if process != "qqH_htt125":
                continue
            add_input_to_inputdict(
                qqh_procs, channel, category, variable, variation, process
            )
    return qqh_procs
