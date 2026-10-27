"""Stage-1.2 NN signal classes as they enter the training: per class the raw rows, sum of weights and sum of weight*class_weight
in the SR of the feather folds (fold0 + fold1 = all events, all eras), one plot per channel."""
import argparse
import ast
from pathlib import Path

import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
import pyarrow.feather as feather
import pyarrow.ipc as ipc
import yaml
from matplotlib.patches import Patch

from analyses.smhtt.plotting.plot_stxs import SIGNAL_COLORS
from trainings.stxs_classes import CLASSES_FILE, PROCESS

PANELS = (("raw", "Raw MC events"), ("weighted", r"$\sum w$ (expected events)"), ("train", r"$\sum w \cdot w_{\mathrm{class}}$ (training)"))


def count(folds_dir):
    """{class label: {raw, weighted, train, sumw2}} summed over the full folds."""
    counts = {}
    for path in sorted(Path(folds_dir).glob("fold[0-9].feather")):
        names = ipc.open_file(path).schema.names  # the MultiIndex columns are stored as stringified tuples
        labels = [n for n in names if "_htautau_bin" in n]
        key = {k: next(n for n in names if n.startswith(f"('Nominal', '{k}',")) for k in ("weight", "cut", "class_weight")}
        t = feather.read_table(path, columns=labels + list(key.values()))
        w, cut, cw = (t[key[k]].to_numpy() for k in ("weight", "cut", "class_weight"))
        for n in labels:
            m = (t[n].to_numpy() == 1) & (cut == 1)
            c = counts.setdefault(ast.literal_eval(n)[1], dict(raw=0, weighted=0.0, train=0.0, sumw2=0.0))
            c["raw"] += int(m.sum()); c["weighted"] += w[m].sum(); c["train"] += (w[m] * cw[m]).sum(); c["sumw2"] += (w[m] ** 2).sum()
    return counts


def plot(ch, classes, counts, output_dir, title):
    names = [" + ".join(dict.fromkeys("VH_" + n.split("_", 1)[1] if c["mode"] == "vh" else n for n in c["names"])) for c in classes]
    colors = [SIGNAL_COLORS[PROCESS[c["mode"]]] for c in classes]
    y = np.arange(len(classes))[::-1]
    fig, axes = plt.subplots(1, 3, figsize=(20, 0.32 * len(classes) + 2.5), sharey=True, gridspec_kw={"wspace": 0.05})
    for ax, (key, xlabel) in zip(axes, PANELS):
        vals = np.array([counts[c["label"]][key] for c in classes])
        ax.barh(y, vals, color=colors, height=0.75)
        for yi, v in zip(y, vals):
            ax.text(v * 1.08, yi, f"{v:,.0f}" if key == "raw" else f"{v:.3g}", va="center", fontsize=9)
        ax.set_xscale("log")
        ax.set_xlim(vals.min() / 3, vals.max() * 6)
        ax.set_xlabel(xlabel, fontsize=14)
        ax.grid(axis="x", which="major", alpha=0.3)
    axes[0].set_yticks(y, names, fontsize=9)
    axes[0].tick_params(axis="y", which="minor", left=False)
    axes[-1].legend(handles=[Patch(color=SIGNAL_COLORS[p], label=p.removesuffix("_htt125")) for p in PROCESS.values()],
                    loc="lower right", fontsize=11, framealpha=0.9)
    axes[0].text(0.0, 1.01, f"{ch}  {title}", transform=axes[0].transAxes, ha="left", va="bottom", fontsize=14)
    axes[-1].text(1.0, 1.01, "2022-2025, SR, fold0+fold1", transform=axes[-1].transAxes, ha="right", va="bottom", fontsize=14)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(Path(output_dir) / f"stxs_classes_{ch}.{ext}", bbox_inches="tight", dpi=150)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-dir", required=True, help="training/datasets/<stage> with <ch>/folds/foldN.feather")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--channels", default="et,mt,tt")
    args = p.parse_args()

    table = yaml.safe_load(CLASSES_FILE.read_text())
    for ch in args.channels.split(","):
        counts = count(Path(args.dataset_dir) / ch / "folds")
        classes = [c for c in table[ch] if c["label"] in counts]
        for c in classes:
            n = counts[c["label"]]
            print(f"{ch} {c['label']:<38} {n['raw']:>9} raw {n['weighted']:>9.2f} weighted {n['weighted'] ** 2 / n['sumw2']:>9.0f} eff. {n['train']:>9.1f} train")
        plot(ch, classes, counts, args.output_dir, Path(args.dataset_dir).resolve().parents[2].name)


if __name__ == "__main__":
    main()
