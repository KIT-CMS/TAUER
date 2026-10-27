"""Stage-1.2 NN signal classes: HTXS_stage1_2_cat bins (the datacard processes) merged bottom-up along the STXS tree until each
class has enough MC events. Reads the bin table of analyses/<analysis>/plotting/plot_stxs.py, writes the class table read by
run.py TRAIN-DATASET and the run3-fine training configs (copies of run3-coarse with these classes)."""
import argparse
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
UAT_DATASETS = REPO_ROOT / "trainings/uncertainty-aware-training/datasets/smhtt"
CLASSES_FILE = REPO_ROOT / "common/training_stxs_classes.yaml"

# HTXS Stage1_2 bins (SimDataFormats/HTXS HiggsTemplateCrossSections.h) and the Stage1_2_Fine bins they contain, FWDH left out
_vh = lambda b, p: {b + 1: (f"{p}_PTV_0_75", [b + 1, b + 6, b + 11]), b + 2: (f"{p}_PTV_75_150", [b + 2, b + 7, b + 12]),
                    b + 3: (f"{p}_PTV_150_250_0J", [b + 3]), b + 4: (f"{p}_PTV_150_250_GE1J", [b + 8, b + 13]),
                    b + 5: (f"{p}_PTV_GT250", [b + 4, b + 5, b + 9, b + 10, b + 14, b + 15])}
BINS = {
    101: ("GG2H_PTH_200_300", [101, 105]), 102: ("GG2H_PTH_300_450", [102, 106]), 103: ("GG2H_PTH_450_650", [103, 107]),
    104: ("GG2H_PTH_GT650", [104, 108]), 105: ("GG2H_0J_PTH_0_10", [109]), 106: ("GG2H_0J_PTH_GT10", [110]),
    107: ("GG2H_1J_PTH_0_60", [111]), 108: ("GG2H_1J_PTH_60_120", [112]), 109: ("GG2H_1J_PTH_120_200", [113]),
    110: ("GG2H_GE2J_MJJ_0_350_PTH_0_60", [114, 117]), 111: ("GG2H_GE2J_MJJ_0_350_PTH_60_120", [115, 118]),
    112: ("GG2H_GE2J_MJJ_0_350_PTH_120_200", [116, 119]), 113: ("GG2H_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25", [120]),
    114: ("GG2H_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25", [121]), 115: ("GG2H_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25", [122, 124, 126]),
    116: ("GG2H_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25", [123, 125, 127]),
    201: ("QQ2HQQ_0J", [201]), 202: ("QQ2HQQ_1J", [202]), 203: ("QQ2HQQ_GE2J_MJJ_0_60", [203, 206]),
    204: ("QQ2HQQ_GE2J_MJJ_60_120", [204, 207]), 205: ("QQ2HQQ_GE2J_MJJ_120_350", [205, 208]),
    206: ("QQ2HQQ_GE2J_MJJ_GT350_PTH_GT200", list(range(217, 225))), 207: ("QQ2HQQ_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25", [209]),
    208: ("QQ2HQQ_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25", [210]), 209: ("QQ2HQQ_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25", [211, 213, 215]),
    210: ("QQ2HQQ_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25", [212, 214, 216]),
    **_vh(300, "QQ2HLNU"), **_vh(400, "QQ2HLL"), **_vh(500, "GG2HLL"),
    601: ("TTH_PTH_0_60", [601]), 602: ("TTH_PTH_60_120", [602]), 603: ("TTH_PTH_120_200", [603]),
    604: ("TTH_PTH_200_300", [604]), 605: ("TTH_PTH_GT300", [605, 606]),
}

# merge order: the bins of a node merge first among themselves, the leftovers then with the neighbouring nodes; a tuple is
# always one class: the bins of the different processes of one stage-0 unit (WH, ZH, ggZH -> ll) stay together
TREE = {
    "ggh": [[105, 106], [107, 108, 109], [110, 111, 112], [101, 102, 103, 104], [[113, 114], [115, 116]]],
    "qqh": [[201, 202], [203, 204, 205], [[207, 208], [209, 210]], [206]],
    "vh": [[(300 + i, 400 + i, 500 + i) for i in range(1, 6)]],
    "tth": [[601, 602, 603, 604, 605]],
}
PROCESS = {"ggh": "ggH_htt125", "qqh": "qqH_htt125", "vh": "VH_htt125", "tth": "ttH_htt125"}  # plot_stxs.py's signal processes


def merge(node, events, threshold):
    """Classes (lists of bins) of a tree node: the children's classes, the smallest merged with its smaller neighbour until all pass."""
    if isinstance(node, (int, tuple)):
        return [list(node) if isinstance(node, tuple) else [node]]
    classes = [c for child in node for c in merge(child, events, threshold)]
    while len(classes) > 1:
        counts = [sum(events.get(b, 0) for b in c) for c in classes]
        i = min(range(len(classes)), key=counts.__getitem__)
        if counts[i] >= threshold:
            break
        j = i - 1 if i == len(classes) - 1 or (i > 0 and counts[i - 1] <= counts[i + 1]) else i + 1
        lo, hi = sorted((i, j))
        classes[lo:hi + 1] = [classes[lo] + classes[hi]]
    return classes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--counts", required=True, help="inclusive_eras_counts_HTXS_stage1_2_fine_cat_pTjet30GeV.json of plot_stxs.py")
    p.add_argument("--threshold", type=float, default=2000, help="Minimum effective MC events per class and channel.")
    p.add_argument("--channels", default="et,mt,tt")
    args = p.parse_args()

    counts = json.loads(Path(args.counts).read_text())
    table = {}
    for ch in args.channels.split(","):
        table[ch] = []
        for mode, tree in TREE.items():
            # plot_stxs.py counts per fine bin, summed into the stage-1.2 bins
            fine = {key: {int(b): n for b, n in counts[ch][PROCESS[mode]][key].items()} for key in ("events", "scaled")}
            events, yields = ({b: sum(fine[key].get(f, 0) for f in BINS[b][1]) for b in BINS} for key in ("events", "scaled"))
            for bins in merge(tree, events, args.threshold):
                table[ch].append({"label": f"is_{mode}_htautau_bin{'_'.join(map(str, bins))}", "mode": mode, "bins": bins,
                                  "names": [BINS[b][0] for b in bins], "events": round(sum(events[b] for b in bins)),
                                  "yield": round(sum(yields[b] for b in bins), 2)})
        for c in table[ch]:
            print(f"{ch} {c['label']:<45} {c['events']:>9} events {c['yield']:>10} expected" + ("  BELOW THRESHOLD" if c["events"] < args.threshold else ""))

    CLASSES_FILE.write_text(f"# generated by trainings/stxs_classes.py --threshold {args.threshold:g} from {args.counts}\n"
                            + yaml.safe_dump(table, sort_keys=False))
    for ch, classes in table.items():
        config = yaml.safe_load((UAT_DATASETS / f"run3-coarse/smhtt_{ch}.yaml").read_text())
        signal = [c["label"] for c in classes]
        config.update(classes=signal + config["background_classes"], signal_classes=signal,
                      signal_class_names=[c["label"].removeprefix("is_").replace("_htautau", "") for c in classes])
        out = UAT_DATASETS / f"run3-fine/smhtt_{ch}.yaml"
        out.parent.mkdir(exist_ok=True)
        out.write_text("# generated by trainings/stxs_classes.py: run3-coarse with the stage-1.2 signal classes\n"
                       + yaml.safe_dump(config, sort_keys=False))
    print(f"written {CLASSES_FILE} and {UAT_DATASETS}/run3-fine/")


if __name__ == "__main__":
    main()
