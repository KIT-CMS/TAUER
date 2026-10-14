#!/usr/bin/env python
"""
Quantitative comparator between two ROOT shape/histogram files for the same
channel/era/variable (e.g. a new production against a reference/legacy one).

Each side is a single ROOT file containing histograms named

    {dataset}#{channel}{process_suffix}#{selection}#{variable}

(see shapes/estimations/defaults.py:_name_string; also how
plotting/plot_shapes_control.py looks histograms up).

Agreement criterion: per-bin difference relative to the combined statistical
uncertainty of both histograms,

    n_sigma = |content_new - content_legacy| / sqrt(error_new^2 + error_legacy^2)

A histogram passes if every bin's n_sigma is <= --max-n-sigma (default 3.0).
A relative-difference threshold (--max-rel-diff) can additionally be
required — useful for high-stat bins where the statistical uncertainty is
tiny and an n-sigma-only check would be overly strict for what is actually a
negligible physical difference.

Exit code: 0 if every compared histogram passes, 1 otherwise. Always prints
the actual achieved max n-sigma / max relative difference per histogram (not
just pass/fail), plus a summary.

Usage:
    python plotting/compare_control_shapes.py \\
        --new-file    output/2022preEE-mt-shapes.root \\
        --legacy-file /path/to/reference/control_shapes-2022preEE-mt.root \\
        --channels mt --variables m_vis,pt_1,pt_2 --selection Nominal \\
        --max-n-sigma 3.0
"""
import argparse
import logging
import sys
from dataclasses import dataclass

import ROOT

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Compare two shape ROOT files, bin-by-bin."
    )
    parser.add_argument("--new-file", required=True, type=str, help="New shapes ROOT file.")
    parser.add_argument("--legacy-file", required=True, type=str, help="Reference/legacy control_shapes-*.root file to compare against.")
    parser.add_argument("--channels", dest="channel", required=True, type=str, help="Channel, e.g. mt/et/tt/em.")
    parser.add_argument(
        "--variables", default=None, type=str,
        help="Comma-separated variable names to compare. Default: every variable present in --legacy-file for this channel/selection.",
    )
    parser.add_argument(
        "--processes", default=None, type=str,
        help="Comma-separated process key infixes (e.g. ZTT,TTL,data) to restrict the comparison to. Default: every process present in --legacy-file for this channel/selection.",
    )
    parser.add_argument("--selection", default="Nominal", type=str, help="Selection/systematic string, e.g. Nominal or same_sign.")
    parser.add_argument("--max-n-sigma", default=3.0, type=float, help="Per-bin agreement tolerance in combined statistical sigma.")
    parser.add_argument(
        "--max-rel-diff", default=None, type=float,
        help="Optional additional per-bin relative-difference tolerance (0-1). A bin must pass BOTH criteria if this is given.",
    )
    parser.add_argument(
        "--strict-missing", action="store_true",
        help="Fail (exit 1) if a histogram present in --legacy-file is missing from --new-file, instead of just warning.",
    )
    return parser.parse_args()


@dataclass
class HistComparison:
    key: str
    n_bins: int
    max_n_sigma: float
    max_rel_diff: float
    worst_bin: int
    passed: bool
    legacy_integral: float
    new_integral: float


def _list_keys(rootfile, channel, selection, variables=None, processes=None):
    """
    Enumerate histogram keys of the form {dataset}#{channel}{proc_suffix}#{selection}#{variable}
    matching the given channel/selection (and optionally variables/processes).
    """
    matched = {}
    for key in rootfile.GetListOfKeys():
        name = key.GetName()
        parts = name.split("#")
        if len(parts) != 4:
            continue
        dataset, sel_string, systematic, variable = parts
        if systematic != selection:
            continue
        if not sel_string.startswith(channel):
            continue
        proc_suffix = sel_string[len(channel):].lstrip("-")
        if variables is not None and variable not in variables:
            continue
        if processes is not None and proc_suffix not in processes and dataset not in processes:
            continue
        matched[name] = (dataset, proc_suffix, variable)
    return matched


def _compare_histograms(h_new, h_legacy, key, max_n_sigma, max_rel_diff):
    n_bins = h_legacy.GetNbinsX()
    if h_new.GetNbinsX() != n_bins:
        logger.error(f"[{key}] bin-count mismatch: new={h_new.GetNbinsX()} legacy={n_bins}")
        return HistComparison(key, n_bins, float("inf"), float("inf"), -1, False,
                               h_legacy.Integral(), h_new.Integral())

    worst_n_sigma, worst_rel_diff, worst_bin = 0.0, 0.0, -1
    all_pass = True
    for i in range(1, n_bins + 1):
        c_new, c_leg = h_new.GetBinContent(i), h_legacy.GetBinContent(i)
        e_new, e_leg = h_new.GetBinError(i), h_legacy.GetBinError(i)

        diff = abs(c_new - c_leg)
        combined_sigma = (e_new ** 2 + e_leg ** 2) ** 0.5
        n_sigma = 0.0 if diff == 0.0 else (diff / combined_sigma if combined_sigma > 0 else float("inf"))

        denom = max(abs(c_new), abs(c_leg), 1e-12)
        rel_diff = diff / denom

        bin_pass = n_sigma <= max_n_sigma
        if max_rel_diff is not None:
            bin_pass = bin_pass and rel_diff <= max_rel_diff

        if not bin_pass:
            all_pass = False
        if n_sigma >= worst_n_sigma:
            worst_n_sigma, worst_bin = n_sigma, i
        worst_rel_diff = max(worst_rel_diff, rel_diff)

    return HistComparison(
        key=key, n_bins=n_bins,
        max_n_sigma=worst_n_sigma, max_rel_diff=worst_rel_diff,
        worst_bin=worst_bin, passed=all_pass,
        legacy_integral=h_legacy.Integral(), new_integral=h_new.Integral(),
    )


def compare_files(new_path, legacy_path, channel, selection, variables, processes, max_n_sigma, max_rel_diff, strict_missing):
    f_new = ROOT.TFile.Open(new_path, "read")
    f_legacy = ROOT.TFile.Open(legacy_path, "read")
    if not f_new or f_new.IsZombie():
        raise RuntimeError(f"Cannot open --new-file {new_path}")
    if not f_legacy or f_legacy.IsZombie():
        raise RuntimeError(f"Cannot open --legacy-file {legacy_path}")

    legacy_keys = _list_keys(f_legacy, channel, selection, variables, processes)
    if not legacy_keys:
        raise RuntimeError(
            f"No histograms found in {legacy_path} for channel={channel!r} selection={selection!r} "
            f"variables={variables} processes={processes}."
        )

    results: list[HistComparison] = []
    missing: list[str] = []

    for key in sorted(legacy_keys):
        h_legacy = f_legacy.Get(key)
        h_new = f_new.Get(key)
        if not h_new:
            missing.append(key)
            logger.warning(f"[MISSING in --new-file] {key}")
            continue
        cmp = _compare_histograms(h_new, h_legacy, key, max_n_sigma, max_rel_diff)
        results.append(cmp)
        status = "PASS" if cmp.passed else "FAIL"
        logger.info(
            f"[{status}] {key}: max_n_sigma={cmp.max_n_sigma:.3f} (bin {cmp.worst_bin}/{cmp.n_bins}) "
            f"max_rel_diff={cmp.max_rel_diff:.4%} "
            f"integrals: new={cmp.new_integral:.4f} legacy={cmp.legacy_integral:.4f}"
        )

    f_new.Close()
    f_legacy.Close()
    return results, missing


def main():
    args = parse_arguments()
    variables = args.variables.split(",") if args.variables else None
    processes = args.processes.split(",") if args.processes else None

    results, missing = compare_files(
        args.new_file, args.legacy_file, args.channel, args.selection,
        variables, processes, args.max_n_sigma, args.max_rel_diff, args.strict_missing,
    )

    n_total = len(results)
    n_passed = sum(1 for r in results if r.passed)
    overall_max_n_sigma = max((r.max_n_sigma for r in results), default=0.0)
    overall_max_rel_diff = max((r.max_rel_diff for r in results), default=0.0)

    logger.info("=" * 88)
    logger.info(
        f"SUMMARY: {n_passed}/{n_total} histograms within {args.max_n_sigma} sigma"
        + (f" and {args.max_rel_diff:.2%} relative difference" if args.max_rel_diff is not None else "")
        + f". Achieved max n_sigma={overall_max_n_sigma:.3f}, max rel_diff={overall_max_rel_diff:.4%} "
        f"across {n_total} histograms. {len(missing)} histograms missing from --new-file."
    )

    ok = (n_total > 0) and (n_passed == n_total) and (not missing or not args.strict_missing)
    if not ok:
        logger.error("Comparator FAILED.")
        sys.exit(1)
    logger.info("Comparator PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
