#!/usr/bin/env python
"""
Quantitative comparator between a TAUER Combine datacard and a legacy
SMRun2Legacy datacard produced for the same era/channel/category from the same
shape input.

Companion to plotting/compare_control_shapes.py (which does the *control-shape*
bin-by-bin comparison). This one operates one level downstream, on the Combine
*datacard* itself, and answers two questions with actual numbers rather than an
eyeball:

  1. YIELDS: for every (bin, process) in the datacard's rate block, is the
     legacy rate equal to the new rate?  Reported as a relative difference
       rel_diff = |rate_new - rate_legacy| / max(|rate_new|, |rate_legacy|, eps)
     Because TAUER's datacards/make_datacards.py is the *relocated*
     SMRun2Legacy scripts/make_datacards.py fed the identical shapes ROOT file,
     the process yields are expected to agree to ~float precision; any
     non-trivial rel_diff is a real regression in the relocation and is flagged.

  2. NUISANCES: the set of nuisance-parameter names on each side, split into
     shared / new-only / legacy-only. A difference is *expected and intentional* --
     systematics naming was deliberately reconciled to shapes/selection/systematics.py
     (JEC 27-source split vs. the legacy regional grouping, tau-ID/ES pT- vs.
     decay-mode splitting, etc.). The comparator therefore does not fail on
     nuisance-set differences by default; it lists them for auditing. Pass
     --strict-nuisances to additionally require identical nuisance sets.

Exit 0 if every (bin, process) yield agrees within --max-rel-diff (and, with
--strict-nuisances, the nuisance sets match); 1 otherwise.

Usage:
    python datacards/compare_datacards.py \\
        --new-card    output_cards_new/mt/2024/mt_m_vis.txt \\
        --legacy-card output_cards_legacy/mt/2024/mt_m_vis.txt \\
        --max-rel-diff 1e-4
"""
import argparse
import logging
import sys
from dataclasses import dataclass

from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


@dataclass
class Card:
    # (bin, process) -> rate
    rates: dict
    # nuisance name -> type (lnN/shape/...)
    nuisances: dict
    observations: dict  # bin -> observed


def parse_datacard(path):
    """Minimal Combine datacard text parser: rate block + nuisance rows.

    A datacard's shape/rate block is four aligned rows introduced by the
    keywords ``bin`` / ``process`` / ``process`` / ``rate``. The second
    ``process`` row is the integer process-id row; we key yields on
    (bin, process_name).
    """
    with open(path) as f:
        lines = f.readlines()

    bin_row = None
    proc_name_row = None
    rate_row = None
    observations = {}
    nuisances = {}

    # Locate the rate block. The 'bin' line that immediately precedes the
    # 'process' lines is the per-column bin row (there is an earlier one-token
    # 'bin' line for observations we handle separately).
    i = 0
    seen_process = False
    while i < len(lines):
        toks = lines[i].split()
        if not toks:
            i += 1
            continue
        key = toks[0]
        if key == "bin" and i + 1 < len(lines) and lines[i + 1].split()[:1] == ["observation"]:
            obs_bins = toks[1:]
            obs_vals = lines[i + 1].split()[1:]
            observations = {b: float(v) for b, v in zip(obs_bins, obs_vals)}
            i += 2
            continue
        if key == "bin" and i + 2 < len(lines) and lines[i + 1].split()[:1] == ["process"]:
            bin_row = toks[1:]
            proc_name_row = lines[i + 1].split()[1:]
            # lines[i+2] is the integer process row, lines[i+3] is rate
            rate_row = lines[i + 3].split()[1:]
            i += 4
            seen_process = True
            continue
        if seen_process and len(toks) >= 2 and toks[1] in ("lnN", "shape", "shapeN", "gmN", "lnU"):
            nuisances[toks[0]] = toks[1]
        i += 1

    rates = {}
    if bin_row and proc_name_row and rate_row:
        for b, p, r in zip(bin_row, proc_name_row, rate_row):
            try:
                rates[(b, p)] = float(r)
            except ValueError:
                pass
    return Card(rates=rates, nuisances=nuisances, observations=observations)


def main():
    ap = argparse.ArgumentParser(description="Compare two Combine datacards (yields + nuisances).")
    ap.add_argument("--new-card", required=True, help="TAUER datacards datacard .txt")
    ap.add_argument("--legacy-card", required=True, help="Legacy SMRun2Legacy datacard .txt")
    ap.add_argument("--max-rel-diff", default=1e-4, type=float, help="Per-(bin,process) yield tolerance.")
    ap.add_argument("--strict-nuisances", action="store_true", help="Also require identical nuisance-name sets.")
    args = ap.parse_args()

    new = parse_datacard(args.new_card)
    legacy = parse_datacard(args.legacy_card)

    logger.info(f"new-card    {args.new_card}: {len(new.rates)} (bin,process) rates, {len(new.nuisances)} nuisances")
    logger.info(f"legacy-card {args.legacy_card}: {len(legacy.rates)} (bin,process) rates, {len(legacy.nuisances)} nuisances")

    # --- yields ---
    all_keys = sorted(set(new.rates) | set(legacy.rates))
    worst = 0.0
    n_pass = 0
    n_total = 0
    yields_ok = True
    for key in all_keys:
        rn = new.rates.get(key)
        rl = legacy.rates.get(key)
        if rn is None or rl is None:
            logger.warning(f"[YIELD MISSING] {key}: new={rn} legacy={rl}")
            yields_ok = False
            continue
        n_total += 1
        rel = abs(rn - rl) / max(abs(rn), abs(rl), 1e-12)
        worst = max(worst, rel)
        status = "PASS" if rel <= args.max_rel_diff else "FAIL"
        if rel > args.max_rel_diff:
            yields_ok = False
        else:
            n_pass += 1
        logger.info(f"[{status}] rate {key}: new={rn:.6g} legacy={rl:.6g} rel_diff={rel:.3e}")

    # --- observations ---
    for b in sorted(set(new.observations) | set(legacy.observations)):
        on = new.observations.get(b)
        ol = legacy.observations.get(b)
        rel = abs((on or 0) - (ol or 0)) / max(abs(on or 0), abs(ol or 0), 1e-12)
        logger.info(f"[obs] bin={b}: new={on} legacy={ol} rel_diff={rel:.3e}")

    # --- nuisances ---
    shared = sorted(set(new.nuisances) & set(legacy.nuisances))
    new_only = sorted(set(new.nuisances) - set(legacy.nuisances))
    legacy_only = sorted(set(legacy.nuisances) - set(new.nuisances))
    logger.info("=" * 88)
    logger.info(f"NUISANCES: {len(shared)} shared, {len(new_only)} new-only, {len(legacy_only)} legacy-only")
    if new_only:
        logger.info(f"  new-only    ({len(new_only)}): {new_only}")
    if legacy_only:
        logger.info(f"  legacy-only ({len(legacy_only)}): {legacy_only}")
    # type mismatches on shared names
    type_mismatch = [n for n in shared if new.nuisances[n] != legacy.nuisances[n]]
    if type_mismatch:
        logger.warning(f"  type mismatches on shared nuisances: "
                       f"{[(n, new.nuisances[n], legacy.nuisances[n]) for n in type_mismatch]}")

    logger.info("=" * 88)
    logger.info(
        f"SUMMARY: yields {n_pass}/{n_total} within rel_diff {args.max_rel_diff:.1e} "
        f"(worst achieved {worst:.3e}); nuisances shared={len(shared)} "
        f"new_only={len(new_only)} legacy_only={len(legacy_only)}."
    )

    ok = yields_ok and (n_total > 0)
    if args.strict_nuisances:
        ok = ok and not new_only and not legacy_only and not type_mismatch
    if not ok:
        logger.error("Datacard comparator FAILED.")
        sys.exit(1)
    logger.info("Datacard comparator PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
