"""
Summary of the GoF p-values of datacards/run_gof.py over variables, one row per variable and a column per channel
(as smhtt_ul's gof/plot_gof_summary.py). Cells below --alpha are marked.
"""
import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np

from datacards.run_gof import gof_pvalue
from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gof-dir", required=True, help="<FITDIR>/output/gof, holding <era>_<channel>_<variable>/gof_<algo>.json")
    parser.add_argument("--era", required=True)
    parser.add_argument("--channels", required=True, type=lambda s: s.split(","))
    parser.add_argument("--variables", required=True, type=lambda s: s.split(","))
    parser.add_argument("--algo", default="saturated")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--output", required=True, help="Output file without extension, written as .png and .pdf")
    return parser.parse_args()


def main(args):
    p = np.full((len(args.variables), len(args.channels)), np.nan)
    for i, variable in enumerate(args.variables):
        for j, channel in enumerate(args.channels):
            path = Path(args.gof_dir) / f"{args.era}_{channel}_{variable}" / f"gof_{args.algo}.json"
            if path.is_file():
                p[i, j] = gof_pvalue(path)[2]
            else:
                logger.warning(f"Missing {path}")
    fig, ax = plt.subplots(figsize=(1.6 + 1.3 * len(args.channels), 0.9 + 0.32 * len(args.variables)))
    colours = ListedColormap(["lightgrey", "#a6d96a", "#f46d43"])  # missing, ok, below alpha
    ax.imshow(np.where(np.isnan(p), 0, np.where(p < args.alpha, 2, 1)), cmap=colours, vmin=0, vmax=2, aspect="auto")
    for (i, j), value in np.ndenumerate(p):
        ax.text(j, i, "missing" if np.isnan(value) else f"{value:.2f}", ha="center", va="center", fontsize=9)
    ax.set_xticks(range(len(args.channels)), args.channels)
    ax.set_yticks(range(len(args.variables)), args.variables)
    ax.set_title(f"GoF ({args.algo}) p-values, {args.era}, red: p < {args.alpha}", fontsize=11)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(f"{args.output}.{ext}", dpi=130)
    logger.info(f"{np.sum(p < args.alpha)} of {np.sum(~np.isnan(p))} tests below p = {args.alpha}, written to {args.output}")


if __name__ == "__main__":
    main(parse_arguments())
