import numpy as np
from ntuple_processor import Histogram
from ntuple_processor.utils import Selection


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
categorization = {}
for channel in ["mt"]:
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
