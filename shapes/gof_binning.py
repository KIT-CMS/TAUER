"""
Equipopulated GoF binning from the selected data events of one era and channel (port of smhtt_ul's gof/build_binning.py).

Takes produce_shapes.py's arguments: --control-plot-set are the variables, --output-file the binning yaml, which
produce_shapes.py --gof-inputs --gof-binning reads. 1D: deciles, integer-like variables get merged unit bins. 2D (each
variable pair, for --do-2d-gofs): slices of the integer-like (else the first) variable, each split equipopulated in the
other one, unrolled to about N_2D_BINS bins. Values outside the edges (e.g. -10 defaults) fall out of the histograms.
"""
import itertools
import logging

import numpy as np
import ROOT
import yaml

import shapes.utils as shape_utils
from common.analysis import build_files_dict
from shapes.produce_shapes import get_friend_directories, parse_arguments
from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

N_1D_BINS, N_2D_SLICES, N_2D_BINS = 10, 5, 25
MIN_FRACTION = 0.15  # minimal population of a merged integer bin, as fraction of the even share


def is_quantized(x):
    unique = np.unique(x)
    return len(unique) < 30 and np.all(np.mod(unique, 1) == 0)


def edges_for(x, n_bins):
    """Equipopulated edges of x with at most n_bins bins, integer-like x merged at unit steps."""
    if is_quantized(x):
        values, counts = np.unique(x, return_counts=True)
        edges, filled = [values[0] - 0.5], 0
        for value, count in zip(values, counts):
            if filled >= MIN_FRACTION * len(x) / n_bins and filled + count / 2 > len(x) / n_bins:
                edges.append(value - 0.5)
                filled = 0
            filled += count
        if filled < MIN_FRACTION * len(x) / n_bins and len(edges) > 1:
            edges.pop()  # merge an underpopulated last bin
        return [float(e) for e in edges] + [float(values[-1] + 0.5)]
    edges = np.unique(np.percentile(x, np.linspace(0, 100, n_bins + 1)))
    return [float(edges[0] - 1e-4 * max(abs(edges[0]), 1))] + [float(e) for e in edges[1:-1]] + [float(edges[-1] + 1e-4 * max(abs(edges[-1]), 1))]


def in_bin(var, lo, hi):
    return f"(({var} >= {lo}) && ({var} < {hi}))"


def unrolled(v1, v2, columns):
    """bins/expression of the 2D unrolled binning of v1 and v2, bin index 1..N (0 outside)."""
    valid = (columns[v1] != -10) & (columns[v2] != -10)
    slice_var, inner_var = (v2, v1) if is_quantized(columns[v2][valid]) and not is_quantized(columns[v1][valid]) else (v1, v2)
    outer, inner = columns[slice_var][valid], columns[inner_var][valid]
    terms, offset = [], 0
    slices = edges_for(outer, N_2D_SLICES)
    for lo, hi in zip(slices, slices[1:]):
        x = inner[(outer >= lo) & (outer < hi)]
        if len(x) == 0:
            continue
        sub = edges_for(x, max(1, round(len(x) / (len(outer) / N_2D_BINS))))
        index = " + ".join(f"{j} * {in_bin(inner_var, a, b)}" for j, (a, b) in enumerate(zip(sub, sub[1:])))
        terms.append(f"({offset + 1} + {index}) * {in_bin(slice_var, lo, hi)} * ({v1} != -10) * ({v2} != -10)")
        offset += len(sub) - 1
    return {"bins": [i + 0.5 for i in range(offset + 1)], "expression": " + ".join(terms)}


def main(args):
    channel = args.channels[0]
    files = build_files_dict(channels=[channel], era=args.era)
    datasets = shape_utils.get_nominal_datasets(
        era=args.era, channel=channel, friend_directories=get_friend_directories(args),
        files={args.era: {channel: {"data": files[args.era][channel]["data"]}}}, directory=args.directory,
        xrootd=args.xrootd, validation_tag=args.validation_tag, validation_db_root=args.validation_db_root,
    )
    ntuples = datasets["data"].ntuples
    n_friends = max(len(n.friends or []) for n in ntuples)
    ntuples = [n for n in ntuples if len(n.friends or []) == n_friends]  # an empty file loses its friends, chains must stay aligned
    chain = ROOT.TChain("ntuple")
    friends = [ROOT.TChain("ntuple") for _ in range(n_friends)]
    for ntuple in ntuples:
        chain.Add(ntuple.path)
        for friend_chain, friend in zip(friends, ntuple.friends or []):
            friend_chain.Add(friend.path)
    for friend_chain in friends:
        chain.AddFriend(friend_chain)
    variables = args.control_plot_set
    columns = ROOT.RDataFrame(chain).Filter("SR_mask > 0.5").AsNumpy(variables)
    logger.info(f"{len(columns[variables[0]])} selected data events in {len(ntuples)} files")

    binning = {}
    for var in variables:
        x = columns[var][columns[var] != -10]
        binning[var] = {"bins": edges_for(x, N_1D_BINS), "expression": var}
    for v1, v2 in itertools.combinations(variables, 2):
        binning[f"{v1}_{v2}"] = unrolled(v1, v2, columns)
    with open(args.output_file, "w") as f:
        yaml.safe_dump(binning, f, default_flow_style=None, sort_keys=False)
    logger.info(f"Wrote the binning of {len(variables)} variables and their pairs to {args.output_file}")


if __name__ == "__main__":
    main(parse_arguments())
