"""
Categorization for njets-binned data/MC control plots ("NjetsControl"), all
channels. Modeled on shapes/special/ttbar_dy_weight_categories.py (structurally
identical -- lives under shapes/special/ instead since, unlike that module,
it has no config-side consumer other than produce_shapes.py itself): three
named sub-categories rather than a joint 2D histogram, since ntuple_processor's
Histogram only ever books a 1D Histo1D.

Each region books the same variable list used by produce_shapes.py's
--no-dnn-categorization control plots (config/variables.yaml's output_features,
filtered to what config/shapes/control_binning.py has binning for) -- so the
resulting shapes are the normal control-plot variable set, just additionally
split by njets, and read by the same downstream plotting as any other shape
(jetFakes/FF, embedding etc. come along automatically via produce_shapes.py's
process-level booking, independent of which categorization is passed in).
"""
import os

import yaml

from config.shapes.categorization import build_categorization
from config.shapes.control_binning import control_binning

_channels = list(control_binning.keys())

_yaml_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "variables.yaml"
)
with open(_yaml_path) as _f:
    _output_features = yaml.safe_load(_f).get("output_features", [])

_regions = {
    "njets0": "(njets == 0)",
    "njets1": "(njets == 1)",
    "njets2p": "(njets >= 2)",
}


def _variables_for(channel):
    available = set(control_binning[channel].keys())
    variables = [v for v in _output_features if v in available]
    if not variables:
        raise ValueError(
            f"No variables from config/variables.yaml are available in control_binning "
            f"for channel {channel!r}. Available: {available}. From YAML: {_output_features}"
        )
    return variables


categorization = build_categorization(
    {channel: {region: (cut, [control_binning[channel][variable] for variable in _variables_for(channel)]) for region, cut in _regions.items()} for channel in _channels}
)
