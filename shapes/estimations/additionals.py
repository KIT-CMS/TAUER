import logging
from .defaults import _name_string, _process_map, _dataset_map


logger = logging.getLogger("")

def _get_qqh_component_hist(rootfile, proc, channel, selection, variable, variation):
    # qqH125 (pure VBF, "_qqH"-postfixed nuisances) and VH_as_qqH125 (hadronic-decay
    # WminusH/WplusH/ZH, "_VH"-postfixed nuisances) are uncorrelated theory
    # nuisances by construction (see shapes/selection/variations.py), so most
    # variation names only exist on one side -- e.g. "LHE_scale_muR_norm_qqHUp"
    # never has a "VH_as_qqH125" counterpart. Falling back to that component's
    # Nominal histogram in that case is the correct treatment: the missing
    # nuisance simply doesn't shift that component.
    name = _name_string.format(
        dataset=_dataset_map[proc],
        channel=channel,
        process="-" + _process_map[proc],
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


def qqH_merge_estimation(rootfile, channel, selection, variable, variation="Nominal"):
    procs_to_add = ["qqH125", "VH_as_qqH125"]
    base_hist = _get_qqh_component_hist(
        rootfile, procs_to_add[0], channel, selection, variable, variation
    ).Clone()
    for proc in procs_to_add[1:]:
        base_hist.Add(
            _get_qqh_component_hist(
                rootfile, proc, channel, selection, variable, variation
            )
        )
    # Keep the original qqH125/"qqH" dataset name so the merged, complete
    # histogram overwrites (rather than duplicates) the incomplete VBF-only
    # one -- combine_datacards/plotting look for process "qqH125", not a
    # separate "qqHComb125" name.
    return base_hist
