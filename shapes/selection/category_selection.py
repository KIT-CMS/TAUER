import numpy as np

# ntuple_processor is only needed for shape *production* (the `categorization`
# Selection/Histogram objects at the bottom of this module), which runs in the
# `taukiktflow` conda env. It is NOT available in the CMSSW/cmsenv session used
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


def build_xxh_cutstring(channel):
    # this function is used to build up the 2D signal category
    # from the ggh and the qqh category. This way,
    # we can rover signal events, that have a large ggh+qqh score
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
            f"({channel}_qqh >= {qqh_bin} && {channel}_qqh < {qqh_binning[i+1]}) * ("
        )
        for j, ggh_bin in enumerate(ggh_binning[:-1]):
            # inner binning is the ggh score, only if the sum of the two scores is below 1
            if qqh_bin + ggh_bin < 1.0:
                cutstring += f"{bincounter} * ({channel}_ggh >= {ggh_bin} && {channel}_ggh < {ggh_binning[j+1]}) + "
                bincounter += 1.0
        # remove the last " + "
        cutstring = cutstring[:-3] + ") + "
    # remove the last " + " and close the parenthesis
    cutstring = cutstring[:-3] + ")"
    # print(cutstring)
    # print("Number of bins: {}".format(bincounter))
    return cutstring, bincounter


fine_binning = np.linspace(0.0, 1.0, 51)
category_mapping = {
    "mt": {
        "ggh": {
            "index": 0,
            "binning": fine_binning,
        },
        "qqh": {
            "index": 1,
            "binning": fine_binning,
        },
        "ztt": {
            "index": 2,
            "binning": fine_binning,
        },
        "ff": {
            "index": 3,
            "binning": fine_binning,
        },
        "zll": {
            "index": 4,
            "binning": fine_binning,
        },
        "tt": {
            "index": 5,
            "binning": fine_binning,
        },
        "misc": {
            "index": 6,
            "binning": fine_binning,
        },
    }
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
# Naming reconciliation note (same spirit as Phase 2d's systematics.py): the
# task's stated rule is to follow TauKITFlow's own naming/index scheme where it
# already exists and is correct (`category_mapping`, mt only) and pull only the
# is_signal *semantics* from legacy -- which is what is done here. smhtt_ul also
# defines et (7-class, same scheme as its mt) and tt (5-class: ggh/vbf/dyjets_tt/
# jetFakes/bkg_rest) DNN mappings, but under legacy's own class names
# (dyjets_tt/dyjets_ll/jetFakes/ttbar/diboson), which do NOT match TauKITFlow's
# category_mapping names, and TauKITFlow's category_mapping deliberately defines
# only mt. Adding et/tt here would mean mixing two naming schemes across channels
# (TauKITFlow names for mt, legacy names for et/tt) with no TauKITFlow-side
# category_mapping to reconcile against -- so they are intentionally left out
# until category_mapping itself grows those channels. mt is also the only channel
# validated end-to-end so far (STATUS.md Phase 1-4). See STATUS.md Phase 4/Blocker #3.
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
for channel in ([] if not _ntuple_processor_available else ["mt"]):
    categorization[channel] = []
    for category in category_mapping[channel].keys():
        selection = (
            Selection(
                name=category,
                cuts=[
                    (
                        f"{channel}_max_index == {category_mapping[channel][category]['index']}",
                        "category selection",
                    )
                ],
            ),
            [
                Histogram(
                    f"{channel}_score",
                    f"{channel}_max_score",
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
                    f"(({channel}_max_index == {category_mapping[channel]['qqh']['index']}) || ({channel}_max_index == {category_mapping[channel]['ggh']['index']}))",
                    "category selection",
                )
            ],
        ),
        [
            Histogram(
                "mt_score",
                cutstring,
                np.arange(nbins + 1),
            )
        ],
    )
    categorization[channel].append(selection)
