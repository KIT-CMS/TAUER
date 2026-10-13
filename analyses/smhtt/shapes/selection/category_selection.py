import numpy as np
try:
    from ntuple_processor import Histogram
    from ntuple_processor.utils import Selection
    _ntuple_processor_available = True
except ImportError:
    _ntuple_processor_available = False


def build_xxh_cutstring(channel, ggh_index=None, qqh_index=None):
    # Builds the 2D signal category from the ggh and qqh category, to recover signal
    # events with a large ggh+qqh score.
    if ggh_index is None:
        ggh_index = category_mapping[channel]["ggh"]["index"]
    if qqh_index is None:
        qqh_index = category_mapping[channel]["qqh"]["index"]
    ggh_branch = f"nn_output_vector[{ggh_index}]"
    qqh_branch = f"nn_output_vector[{qqh_index}]"
    ggh_binning = [0.0, 0.2, 0.3, 0.4, 0.5, 0.65, 0.8, 1.0]
    qqh_binning = [
        0.0,
        0.35,
        0.5,
        0.6,
        0.7,
        0.8,
        0.85,
        0.9,
        0.92,
        0.94,
        0.96,
        0.98,
        1.0,
    ]
    cutstring = "("
    bincounter = 0.0
    for i, qqh_bin in enumerate(qqh_binning[:-1]):
        # outer binning is the qqh score
        cutstring += (
            f"({qqh_branch} >= {qqh_bin} && {qqh_branch} < {qqh_binning[i+1]}) * ("
        )
        for j, ggh_bin in enumerate(ggh_binning[:-1]):
            # inner binning is the ggh score, only if the sum of the two scores is below 1
            if qqh_bin + ggh_bin < 1.0:
                cutstring += f"{bincounter} * ({ggh_branch} >= {ggh_bin} && {ggh_branch} < {ggh_binning[j+1]}) + "
                bincounter += 1.0
        # remove the last " + "
        cutstring = cutstring[:-3] + ") + "
    # remove the last " + " and close the parenthesis
    cutstring = cutstring[:-3] + ")"
    return cutstring, bincounter


fine_binning = np.linspace(0.0, 1.0, 51)

# 7-class mt/et scheme
_seven_class_scheme = {
    "ggh": {"index": 0, "binning": fine_binning},
    "qqh": {"index": 1, "binning": fine_binning},
    "ztt": {"index": 2, "binning": fine_binning},
    "ff": {"index": 3, "binning": fine_binning},
    "zll": {"index": 4, "binning": fine_binning},
    "tt": {"index": 5, "binning": fine_binning},
    "misc": {"index": 6, "binning": fine_binning},
}

category_mapping = {
    "mt": dict(_seven_class_scheme),
    "et": dict(_seven_class_scheme),
    # 5-class tt scheme 
    "tt": {
        "ggh": {"index": 0, "binning": fine_binning},
        "qqh": {"index": 1, "binning": fine_binning},
        "ztt": {"index": 2, "binning": fine_binning},
        "ff": {"index": 3, "binning": fine_binning},
        "misc": {"index": 4, "binning": fine_binning},
    },
}
SIGNAL_CLASSES = {"ggh", "qqh"}  # ggH + qqH/VBF

DNN_CLASS_MAPPING = {
    channel: {
        name: {"index": info["index"], "is_signal": name in SIGNAL_CLASSES}
        for name, info in classes.items()
    }
    for channel, classes in category_mapping.items()
}


categorization = {}
for channel in ([] if not _ntuple_processor_available else list(category_mapping.keys())):
    categorization[channel] = []
    for category in category_mapping[channel].keys():
        selection = (
            Selection(
                name=category,
                cuts=[
                    (
                        f"nn_predicted_class == {category_mapping[channel][category]['index']}",
                        "category selection",
                    )
                ],
            ),
            [
                Histogram(
                    f"{channel}_score",
                    "nn_predicted_max_value",
                    category_mapping[channel][category]["binning"],
                )
            ],
        )
        categorization[channel].append(selection)
    # add the xxh category
    cutstring, nbins = build_xxh_cutstring(channel)
    selection = (
        Selection(
            name="xxh",
            cuts=[
                (
                    f"((nn_predicted_class == {category_mapping[channel]['qqh']['index']}) || (nn_predicted_class == {category_mapping[channel]['ggh']['index']}))",
                    "category selection",
                )
            ],
        ),
        [
            Histogram(
                f"{channel}_score",
                cutstring,
                np.arange(nbins + 1),
            )
        ],
    )
    categorization[channel].append(selection)
