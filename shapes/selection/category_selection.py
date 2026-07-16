import numpy as np

# ntuple_processor is only needed for shape *production* (the `categorization`
# Selection/Histogram objects at the bottom of this module), which runs in the
# `taukitflow` conda env. It is NOT available in the CMSSW/cmsenv session used
# for datacard construction (utils/setup_cmssw.sh) -- and that session needs to
# import DNN_CLASS_MAPPING from this module (combine_datacards/categories.py's
# stxs_stage0_run3 path). So the import is guarded: DNN_CLASS_MAPPING /
# category_mapping / SIGNAL_CLASSES stay importable without ntuple_processor,
# and only the production-side `categorization` object is skipped when it's
# absent (mirrors smhtt_ul's own config/shapes/category_selection.py).
try:
    from ntuple_processor import Histogram
    from ntuple_processor.utils import Selection
    _ntuple_processor_available = True
except ImportError:
    _ntuple_processor_available = False


def build_xxh_cutstring(channel, ggh_index=None, qqh_index=None):
    # this function is used to build up the 2D signal category
    # from the ggh and the qqh category. This way,
    # we can rover signal events, that have a large ggh+qqh score
    #
    # Branch-naming note (Phase 8): the real DNN friend trees
    # (CROWNMultiFriends/nn_output_260703, verified against a real file for
    # et/mt/tt -- see STATUS.md Phase 8) do NOT expose per-class scalar score
    # branches named "{channel}_ggh"/"{channel}_qqh". They expose exactly
    # three (unprefixed) branches: nn_predicted_class (int),
    # nn_predicted_max_value (float), and nn_output_vector (a fixed-length
    # array of per-class scores in category_mapping index order: 7 entries
    # for mt/et, 5 for tt). So the per-class ggh/qqh score used here has to be
    # read out of that vector at the class's index -- nn_output_vector[idx] --
    # rather than from a dedicated branch. ggh_index/qqh_index default to the
    # channel's own category_mapping entries when not given explicitly.
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
    # print(cutstring)
    # print("Number of bins: {}".format(bincounter))
    return cutstring, bincounter


fine_binning = np.linspace(0.0, 1.0, 51)

# 7-class mt/et scheme (mt validated Phase 4b; et added Phase 8 -- see
# STATUS.md Phase 8 for the reconciliation). Ground truth for class semantics
# (which physical process each index maps to) is smhtt_ul branch 77af7d0
# ("nn, combine") config/shapes/category_selection.py:DNN_CLASS_MAPPING, which
# defines an *identical* index order for both its "mt" and "et" entries:
#   0 ggh, 1 vbf, 2 dyjets_tt, 3 dyjets_ll, 4 jetFakes, 5 ttbar, 6 diboson
# TauKITFlow's own names (already settled for mt in Phase 4b) are kept:
#   qqh==vbf, ztt==dyjets_tt, zll==dyjets_ll, ff==jetFakes, tt==ttbar, misc==diboson
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
    # 5-class tt scheme. Ground truth is the same smhtt_ul 77af7d0 config,
    # whose "tt" entry is: 0 ggh, 1 vbf, 2 dyjets_tt, 3 jetFakes, 4 bkg_rest
    # (no separate DY->ll or ttbar/diboson classes -- tt channel merges them
    # into one "remaining backgrounds" class). Category name "tt" (used in
    # mt/et for the ttbar class) is not needed here, so there is no collision
    # with the tt *channel* name. "misc" is reused for the catch-all class to
    # match the mt/et naming convention for "everything else".
    "tt": {
        "ggh": {"index": 0, "binning": fine_binning},
        "qqh": {"index": 1, "binning": fine_binning},
        "ztt": {"index": 2, "binning": fine_binning},
        "ff": {"index": 3, "binning": fine_binning},
        "misc": {"index": 4, "binning": fine_binning},
    },
}
# ---------------------------------------------------------------------------
# DNN class mapping for the stxs_stage0_run3 (Run3 DNN-score) datacard path.
#
# combine_datacards/categories.py's stxs_stage0_run3 path imports this dict in
# the exact shape {channel: {category_name: {"index": int, "is_signal": bool}}}.
# Each DNN output class becomes one datacard bin (mt_ggh, mt_qqh, ...); signal
# classes go first, background/control classes after.
#
# Single-sourced off `category_mapping` above (TauKITFlow's own, validated
# per-channel names + DNN output-class indices -- see STATUS.md Phase 2d/3/4),
# so names/indices are never duplicated. The only field added here is
# `is_signal`, whose ground truth is smhtt_ul's own DNN categorization config
# `config/shapes/category_selection.py:DNN_CLASS_MAPPING` (branch 77af7d0
# "nn, combine"): there the Higgs production-mode classes ggh (index 0) and vbf
# (index 1) carry is_signal=True and every remaining class (DY tautau, DY ll,
# jet fakes, ttbar, diboson) is is_signal=False. TauKITFlow's `category_mapping`
# names the VBF/qqH class "qqh" (== legacy "vbf"), so the two signal classes
# here are {"ggh", "qqh"}; ztt/ff/zll/tt/misc are all background/control regions.
#
# Naming reconciliation note (Phase 8, closing the Phase 4b gap): et and tt
# are now reconciled the same way mt was in Phase 4b -- class *semantics*
# (which physical process each index maps to) come from smhtt_ul 77af7d0,
# names/indices are single-sourced off `category_mapping` above (which now
# has real et/tt entries, not just mt). et reuses the mt naming 1:1 (same
# 7-class scheme, same index order). tt gets its own 5-class scheme
# (ggh/qqh/ztt/ff/misc == legacy ggh/vbf/dyjets_tt/jetFakes/bkg_rest).
# See STATUS.md Phase 8 for the full reconciliation record.
SIGNAL_CLASSES = {"ggh", "qqh"}  # ggH + qqH/VBF; legacy ground truth (see above)

DNN_CLASS_MAPPING = {
    channel: {
        name: {"index": info["index"], "is_signal": name in SIGNAL_CLASSES}
        for name, info in classes.items()
    }
    for channel, classes in category_mapping.items()
}


categorization = {}
# Skip the production-side Selection/Histogram build when ntuple_processor is
# unavailable (e.g. the CMSSW datacard session) -- DNN_CLASS_MAPPING above is
# all that path needs from this module.
#
# Branch-naming reconciliation (Phase 8): the real DNN friend trees
# (CROWNMultiFriends/nn_output_260703, verified for et/mt/tt against a real
# 2024 file -- see STATUS.md Phase 8) expose exactly three branches, none of
# them channel-prefixed: nn_predicted_class (int, the argmax class index),
# nn_predicted_max_value (float, the max score), and nn_output_vector (array
# of per-class scores in category_mapping index order). TauKITFlow's
# pre-Phase-8 code assumed "{channel}_max_index"/"{channel}_max_score" branch
# names -- those do not exist in the real production friends, so the cuts/
# histograms below were changed to use the real, unprefixed branch names
# instead (this is safe because each channel's RDataFrame only ever has its
# own channel's nn friend attached -- ntuples are already split per-channel
# upstream, so there is no cross-channel collision from dropping the prefix).
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
