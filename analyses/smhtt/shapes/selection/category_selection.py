from pathlib import Path

import numpy as np
import yaml
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

# 9-class mt/et scheme, the output order of the trainings' run3-coarse configs
_nine_class_scheme = {
    "ggh": {"index": 0, "binning": fine_binning},
    "qqh": {"index": 1, "binning": fine_binning},
    "vh": {"index": 2, "binning": fine_binning},
    "tth": {"index": 3, "binning": fine_binning},
    "ztt": {"index": 4, "binning": fine_binning},
    "ff": {"index": 5, "binning": fine_binning},
    "zll": {"index": 6, "binning": fine_binning},
    "tt": {"index": 7, "binning": fine_binning},
    "misc": {"index": 8, "binning": fine_binning},
}

category_mapping = {
    "mt": dict(_nine_class_scheme),
    "et": dict(_nine_class_scheme),
    # 7-class tt scheme
    "tt": {
        "ggh": {"index": 0, "binning": fine_binning},
        "qqh": {"index": 1, "binning": fine_binning},
        "vh": {"index": 2, "binning": fine_binning},
        "tth": {"index": 3, "binning": fine_binning},
        "ztt": {"index": 4, "binning": fine_binning},
        "ff": {"index": 5, "binning": fine_binning},
        "misc": {"index": 6, "binning": fine_binning},
    },
}
SIGNAL_CLASSES = {"ggh", "qqh", "vh", "tth"}  # the STXS stage-0 production modes

# stage-1.2 NN: classes of the run3-fine training configs, in their output order (signals ggh_bin105, ..., backgrounds as stage 0)
_FINE_CONFIGS = Path(__file__).resolve().parents[4] / "trainings/uncertainty-aware-training/datasets/smhtt/run3-fine"
_BACKGROUND_CLASS = {"is_dyjets_tt": "ztt", "is_jetFakes": "ff", "is_dyjets_ll": "zll", "is_ttbar": "tt", "is_diboson": "misc", "is_bkg_rest": "misc"}
category_mapping_stage1p2 = {
    channel: {_BACKGROUND_CLASS.get(label, label.removeprefix("is_").replace("_htautau", "")): {"index": i, "binning": fine_binning}
              for i, label in enumerate(yaml.safe_load((_FINE_CONFIGS / f"smhtt_{channel}.yaml").read_text())["classes"])}
    for channel in category_mapping if (_FINE_CONFIGS / f"smhtt_{channel}.yaml").exists()
}


def dnn_class_mapping(stage="stage0"):
    """{channel: {category: {index, is_signal}}} of the stage-0 or stage-1.2 NN."""
    mapping = category_mapping if stage == "stage0" else category_mapping_stage1p2
    return {channel: {name: {"index": info["index"], "is_signal": name not in _BACKGROUND_CLASS.values()} for name, info in classes.items()}
            for channel, classes in mapping.items()}


DNN_CLASS_MAPPING = dnn_class_mapping("stage0")


def build_categorization(stage="stage0"):
    """{channel: [(Selection, [Histogram])]}: one category per NN class (nn_predicted_class), plus the 2D ggh+qqh xxh one in stage 0."""
    mapping = category_mapping if stage == "stage0" else category_mapping_stage1p2
    result = {}
    for channel in mapping if _ntuple_processor_available else []:
        result[channel] = [
            (Selection(name=category, cuts=[(f"nn_predicted_class == {info['index']}", "category selection")]),
             [Histogram(f"{channel}_score", "nn_predicted_max_value", info["binning"])])
            for category, info in mapping[channel].items()
        ]
        if stage == "stage0":
            result[channel].append(_xxh_category(channel))
    return result


def _xxh_category(channel):
    cutstring, nbins = build_xxh_cutstring(channel)
    ggh, qqh = category_mapping[channel]["ggh"]["index"], category_mapping[channel]["qqh"]["index"]
    return (Selection(name="xxh", cuts=[(f"((nn_predicted_class == {qqh}) || (nn_predicted_class == {ggh}))", "category selection")]),
            [Histogram(f"{channel}_score", cutstring, np.arange(nbins + 1))])


categorization = build_categorization("stage0")
