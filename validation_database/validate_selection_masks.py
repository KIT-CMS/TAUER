#!/usr/bin/env python3
"""
Event-by-event validation of CROWN's precomputed selection masks against the
cut strings they are meant to replace.

Every mask branch CROWN's ``selection.py`` writes (feature/selection-masks) is
supposed to be *exactly* the AND of the cuts that TauFakeFactors' YAMLs (and,
for ``presel_mask``, this repo's ``config/cuts.yaml``) define for the same
region. This script proves that on a real ntuple, per region:

    rdf.Filter(f"(({mask} > 0.5) != ({cutstring}))").Count() == 0

i.e. not a single event where the mask and the reconstructed cut string
disagree in either direction. A count of 0 is the only passing result; any
non-zero count is a real, event-level discrepancy.

It additionally reports the **nbtag accounting**, which is a *known, intended*
difference and not a failure: TauFakeFactors' ``helper/ff_functions.py::
apply_region_filters`` silently skips every ``nbtag``/``bb_selection`` cut key
(``if cut not in ["nbtag", "bb_selection"]``), so the regions TFF actually
selects today are LOOSER than what its own YAMLs say. The masks encode the
YAMLs faithfully (user decision #4 of the plan). For each region this script
therefore evaluates the cut string twice — "yaml-faithful" (must match the mask
exactly) and "current-TFF-behavior" (nbtag keys dropped, as TFF runs today) —
and prints the event-count delta between them, which is exactly the population
that will move when TFF switches to filtering on the masks.

Region reconstruction implements TauFakeFactors' merge semantics locally
(``helper/functions.py::modify_config``) rather than importing them, so this
script runs without the TauFakeFactors package importable and, more
importantly, so a bug in that merge cannot hide itself by being used on both
sides of the comparison. The TauFakeFactors YAMLs are only ever READ.

Sources per mask family
-----------------------
``presel_mask``
    config/cuts.yaml ``preselection:`` block for (era, channel), via
    config.analysis.get_preselection_cuts() — i.e. the very same getter
    shapes/preselect.py and generate_tff_configs.py use.
``ff_<proc>_{SR,AR,SRlike,ARlike}``
    TauFakeFactors/configs/smhtt_ul/{era}/fake_factors_{ch}.yaml,
    ``target_processes.<Proc>.{SR,AR,SRlike,ARlike}_cuts``.
``ff_fraction[_sub]_{SR,AR}``
    same file, ``process_fractions[_subleading].{SR,AR}_cuts``.
``ff_<proc>_{SRlike,ARlike}_ss``
    the in-code same-sign QCD-estimation variants FF_calculation/FF_Wjets.py
    and FF_calculation/FF_ttbar.py build by overwriting the region's
    ``tau_pair_sign`` cut with ``(q_1*q_2) > 0``.
``ff_<proc>_{DR_SR,AR_SR}_{SRlike,ARlike}``
    base region from fake_factors_{ch}.yaml with
    corrections_{ch}.yaml ``target_processes.<Proc>.DR_SR`` overrides merged on
    top: ``SRlike_cuts``/``ARlike_cuts`` override their own variant per key,
    and (AR_SR only) ``AR_SR_cuts`` overrides BOTH variants per key.

Usage
-----
    python validation_database/validate_selection_masks.py \\
        --input /ceph/.../mt/DYto2L.root --era 2022preEE --channel mt

    python validation_database/validate_selection_masks.py \\
        --input /ceph/.../preselection/2024/tt --era 2024 --channel tt \\
        --regions 'ff_qcd_*' --fail-fast

Not run as part of any pipeline: it needs a mask-bearing ntuple, which only
exists once CROWN's feature/selection-masks production has been made.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import logging
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from config.analysis import (  # noqa: E402
    PRESELECTION_MASK_BRANCH,
    SUPPORTED_ERAS,
    TFF_CONFIG_ROOT,
    get_preselection_cuts,
    get_region_mask_names,
)

logger = logging.getLogger("validate_selection_masks")

# Cut keys TauFakeFactors' apply_region_filters() skips outright
# (helper/ff_functions.py: `if cut not in ["nbtag", "bb_selection"]`). Dropping
# these is what "current-TFF-behavior" means below.
TFF_SKIPPED_CUT_KEYS = ("nbtag", "bb_selection")

# The same-sign expression FF_Wjets.py / FF_ttbar.py write into the region's
# tau_pair_sign key for their in-code QCD estimation, verbatim.
SAME_SIGN_EXPR = "(q_1*q_2) > 0"

# Keys inside a *_cuts block that are metadata, not cut expressions, and must
# never end up in a cut string. The `region_mask` family is this feature's own
# addition on the TauFakeFactors side (step 7-9 of the plan): the mask branch a
# region should filter on, stored next to the cut dict that stays as the
# fallback. `region_mask_SRlike`/`region_mask_ARlike` appear in the corrections
# YAML's DR_SR block so modify_config can override the two variants
# independently. Stripped here — and used below as a free cross-check that the
# name TauFakeFactors will filter on is the name this repo declares.
_META_KEY_PREFIX = "region_mask"


def _is_meta_key(key: str) -> bool:
    return key == _META_KEY_PREFIX or key.startswith(_META_KEY_PREFIX + "_")


def _strip_meta(cuts: dict) -> tuple[dict, str | None]:
    """Split a *_cuts block into (real cut expressions, declared mask name)."""
    declared = cuts.get(_META_KEY_PREFIX)
    return {k: v for k, v in cuts.items() if not _is_meta_key(k)}, declared


# ── YAML access (read-only) ───────────────────────────────────────────────────

def _load_tff_yaml(era: str, channel: str, kind: str) -> dict:
    """Read TauFakeFactors/configs/smhtt_ul/{era}/{kind}_{channel}.yaml."""
    path = TFF_CONFIG_ROOT / era / f"{kind}_{channel}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found.\nRun: git submodule update --init TauFakeFactors"
        )
    with open(path) as fh:
        return yaml.safe_load(fh)


# ── Region reconstruction ─────────────────────────────────────────────────────

def _apply_modify_config(
    srlike: dict, arlike: dict, corr_block: dict, to_AR_SR: bool
) -> tuple[dict, dict]:
    """Local re-implementation of TauFakeFactors' helper.functions.modify_config.

    Per-key override (NOT a wholesale replacement of the cut dict):
      * ``SRlike_cuts`` from the correction block overrides the SRlike variant,
      * ``ARlike_cuts`` overrides the ARlike variant,
      * ``AR_SR_cuts`` (only when ``to_AR_SR``) overrides BOTH, applied last so
        it wins over the two above — matching modify_config's statement order.
    """
    srlike, arlike = copy.deepcopy(srlike), copy.deepcopy(arlike)
    for key, expr in (corr_block.get("SRlike_cuts") or {}).items():
        srlike[key] = expr
    for key, expr in (corr_block.get("ARlike_cuts") or {}).items():
        arlike[key] = expr
    if to_AR_SR:
        for key, expr in (corr_block.get("AR_SR_cuts") or {}).items():
            srlike[key] = expr
            arlike[key] = expr
    return srlike, arlike


def _same_sign(cuts: dict) -> dict:
    """The in-code SS-flipped variant (FF_Wjets.py:85 / FF_ttbar.py:239)."""
    if "tau_pair_sign" not in cuts:
        raise KeyError(
            "region has no `tau_pair_sign` cut — the SS QCD estimation cannot "
            "be built from it (FF_Wjets.py/FF_ttbar.py raise the same way)"
        )
    flipped = copy.deepcopy(cuts)
    flipped["tau_pair_sign"] = SAME_SIGN_EXPR
    return flipped


# Mask-name prefix per TauFakeFactors target_processes key, per channel.
_PROC_PREFIX = {
    "mt": {"QCD": "ff_qcd", "Wjets": "ff_wjets", "ttbar": "ff_ttbar"},
    "et": {"QCD": "ff_qcd", "Wjets": "ff_wjets", "ttbar": "ff_ttbar"},
    "tt": {"QCD": "ff_qcd", "QCD_subleading": "ff_qcd_sub"},
}

# Which of the four cut blocks each target process defines, and which of them
# additionally get an in-code same-sign variant.
_SS_VARIANT_BLOCKS = {"SRlike_cuts", "ARlike_cuts"}
_SS_PROCESSES = {"Wjets", "ttbar"}


def build_regions(era: str, channel: str) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Reconstruct every mask of (era, channel) from the YAMLs.

    Returns ``(regions, declared)`` where ``regions`` maps mask name ->
    {cut_key: expr} (metadata keys stripped) and ``declared`` maps mask name ->
    the ``region_mask`` name the TauFakeFactors YAML itself declares for that
    block, where present. Comparing the two catches naming drift between this
    repo's config/variables.yaml, CROWN's selection.py and the TFF YAMLs
    without needing a single event.

    Ordering is stable (definition order below) so the report reads the same
    way across runs.
    """
    regions: dict[str, dict[str, str]] = {}
    declared: dict[str, str] = {}

    # presel_mask — from THIS repo's cuts.yaml, not from TFF (the TFF
    # preselection_{ch}.yaml is a generated mirror of it; reading the source
    # avoids validating a copy against a copy).
    regions[PRESELECTION_MASK_BRANCH] = dict(get_preselection_cuts(era, channel))

    if channel not in _PROC_PREFIX:
        logger.info(f"channel {channel}: no fake-factor regions defined (masks: presel/sign only)")
        return regions, declared

    ff_cfg = _load_tff_yaml(era, channel, "fake_factors")
    corr_cfg = _load_tff_yaml(era, channel, "corrections")

    targets = ff_cfg.get("target_processes", {}) or {}
    for proc, prefix in _PROC_PREFIX[channel].items():
        proc_cfg = targets.get(proc)
        if proc_cfg is None:
            logger.warning(f"fake_factors_{channel}.yaml has no target_processes.{proc} — skipped")
            continue
        for block, suffix in (
            ("SR_cuts", "SR"), ("AR_cuts", "AR"),
            ("SRlike_cuts", "SRlike"), ("ARlike_cuts", "ARlike"),
        ):
            if block not in proc_cfg:
                continue
            cuts, decl = _strip_meta(proc_cfg[block])
            name = f"{prefix}_{suffix}"
            regions[name] = cuts
            if decl:
                declared[name] = decl
            if proc in _SS_PROCESSES and block in _SS_VARIANT_BLOCKS:
                # The SS variant's mask is the `_ss`-suffixed sibling; the YAML
                # only declares the OS one (the flip happens in TFF's code).
                regions[f"{name}_ss"] = _same_sign(cuts)

    # process_fractions (+ tt's subleading twin)
    for key, prefix in (
        ("process_fractions", "ff_fraction"),
        ("process_fractions_subleading", "ff_fraction_sub"),
    ):
        frac = ff_cfg.get(key)
        if frac is None:
            continue
        for block, suffix in (("SR_cuts", "SR"), ("AR_cuts", "AR")):
            if block in frac:
                cuts, decl = _strip_meta(frac[block])
                regions[f"{prefix}_{suffix}"] = cuts
                if decl:
                    declared[f"{prefix}_{suffix}"] = decl

    # Correction regions: base SRlike/ARlike + corrections_{ch}.yaml DR_SR
    # overrides (modify_config), in both the DR_SR and the AR_SR flavour.
    corr_targets = corr_cfg.get("target_processes", {}) or {}
    for proc, prefix in _PROC_PREFIX[channel].items():
        corr_block = (corr_targets.get(proc) or {}).get("DR_SR")
        base = targets.get(proc)
        if corr_block is None or base is None:
            continue
        if "SRlike_cuts" not in base or "ARlike_cuts" not in base:
            logger.warning(
                f"{proc}: corrections define DR_SR but fake_factors has no "
                f"SRlike_cuts/ARlike_cuts to merge onto — skipped"
            )
            continue
        for to_AR_SR, tag in ((False, "DR_SR"), (True, "AR_SR")):
            merged = _apply_modify_config(
                base["SRlike_cuts"], base["ARlike_cuts"], corr_block, to_AR_SR
            )
            for variant, block in zip(("SRlike", "ARlike"), merged):
                name = f"{prefix}_{tag}_{variant}"
                cuts, decl = _strip_meta(block)
                regions[name] = cuts
                # The corrections YAML declares the two variants separately
                # (region_mask_SRlike/region_mask_ARlike) so modify_config can
                # override them independently; fall back to the plain key.
                decl = block.get(f"{_META_KEY_PREFIX}_{variant}", decl)
                if decl:
                    declared[name] = decl

    return regions, declared


def cut_string(cuts: dict[str, str], skip_tff_skipped_keys: bool = False) -> str:
    """AND of a region's cut expressions, each parenthesised.

    `skip_tff_skipped_keys` reproduces what TauFakeFactors' apply_region_filters
    actually applies today (nbtag/bb_selection dropped) — the "current-TFF-
    behavior" column of the report.
    """
    items = [
        (k, v) for k, v in cuts.items()
        if not (skip_tff_skipped_keys and k in TFF_SKIPPED_CUT_KEYS)
    ]
    if not items:
        return "true"
    return " && ".join(f"({v})" for _, v in items)


# ── Input handling ────────────────────────────────────────────────────────────

def resolve_inputs(path: str) -> list[str]:
    """One .root file, or every .root file under a directory (sorted)."""
    p = Path(path)
    if "://" in path or p.is_file():
        return [path]
    if p.is_dir():
        files = sorted(str(f) for f in p.rglob("*.root"))
        if not files:
            raise SystemExit(f"No .root files under {path}")
        return files
    raise SystemExit(f"Input not found: {path}")


def resolve_tree(files: list[str], channel: str, explicit: str | None) -> str:
    """Tree name: the flat skim writes `ntuple`, raw CROWN `{channel}_nominal`."""
    if explicit:
        return explicit
    import ROOT

    for candidate in ("ntuple", f"{channel}_nominal"):
        fh = ROOT.TFile.Open(files[0])
        if not fh or fh.IsZombie():
            raise SystemExit(f"Cannot open {files[0]}")
        found = fh.Get(candidate) is not None and bool(fh.GetListOfKeys().Contains(candidate))
        fh.Close()
        if found:
            return candidate
    raise SystemExit(
        f"Neither 'ntuple' nor '{channel}_nominal' found in {files[0]} — pass --tree explicitly"
    )


# ── Report ────────────────────────────────────────────────────────────────────

_HEADER = (
    f"{'region / mask branch':<28} {'N(mask)':>12} {'N(cuts)':>12} "
    f"{'mismatch':>10} {'+presel':>10} {'status':>8} "
    f"{'N(no-nbtag)':>13} {'delta':>10}"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True,
                        help="Mask-bearing ntuple: a .root file, an xrootd URL, or a "
                             "directory (every .root under it is chained).")
    parser.add_argument("--era", required=True, choices=list(SUPPORTED_ERAS))
    parser.add_argument("--channel", required=True, choices=["et", "mt", "tt", "em"])
    parser.add_argument("--tree", default=None,
                        help="Tree name (default: auto — 'ntuple' for the flat skim, "
                             "'{channel}_nominal' for raw CROWN output).")
    parser.add_argument("--regions", default="*",
                        help="Comma-separated glob(s) selecting which mask names to check "
                             "(default: all). Example: 'ff_qcd_*,presel_mask'.")
    parser.add_argument("--nthreads", type=int, default=4,
                        help="ROOT implicit-MT threads (0 disables; default 4).")
    parser.add_argument("--fail-fast", action="store_true",
                        help="Stop at the first region that mismatches.")
    parser.add_argument("--print-cuts", action="store_true",
                        help="Print each region's reconstructed cut string before checking it.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    import ROOT
    ROOT.gROOT.SetBatch(True)
    if args.nthreads > 0:
        ROOT.EnableImplicitMT(args.nthreads)

    files = resolve_inputs(args.input)
    tree = resolve_tree(files, args.channel, args.tree)
    logger.info(f"Reading {len(files)} file(s), tree '{tree}'")

    rdf = ROOT.RDataFrame(tree, files)
    available = {str(c) for c in rdf.GetColumnNames()}
    if PRESELECTION_MASK_BRANCH not in available:
        raise SystemExit(
            f"'{PRESELECTION_MASK_BRANCH}' not in {args.input} — this is not a mask-bearing "
            f"ntuple, there is nothing to validate."
        )

    regions, declared_masks = build_regions(args.era, args.channel)

    # Free, event-independent cross-check: the `region_mask` key the
    # TauFakeFactors YAML declares for a block must be the name this script
    # (and config/variables.yaml, and CROWN) call that region. A mismatch means
    # TauFakeFactors would filter on a different branch than the one being
    # validated here, which no event-level check could ever catch.
    for name, decl in sorted(declared_masks.items()):
        if decl != name:
            logger.warning(
                f"naming drift: reconstructed region '{name}' but the TFF yaml declares "
                f"region_mask: '{decl}' for the same block"
            )

    # Cross-check the reconstruction against the declared mask inventory: a
    # name in one list and not the other means config/variables.yaml and the
    # TFF YAMLs have drifted apart, which is exactly the class of bug this
    # whole feature exists to prevent.
    declared = set(get_region_mask_names(args.era, args.channel))
    declared.discard("sel_os")   # trivial sign masks, no yaml region behind them
    declared.discard("sel_ss")
    only_declared = sorted(declared - set(regions))
    only_built = sorted(set(regions) - declared)
    if only_declared:
        logger.warning(
            f"declared in config/variables.yaml but NOT reconstructible from the TFF yamls: "
            f"{only_declared}"
        )
    if only_built:
        logger.warning(
            f"reconstructed from the TFF yamls but NOT declared in config/variables.yaml: "
            f"{only_built}"
        )

    patterns = [p.strip() for p in args.regions.split(",") if p.strip()]
    selected = [
        name for name in regions
        if any(fnmatch.fnmatch(name, pat) for pat in patterns)
    ]
    if not selected:
        raise SystemExit(f"No region matches --regions {args.regions!r}. Known: {sorted(regions)}")

    presel_expr = f"({PRESELECTION_MASK_BRANCH} > 0.5)"

    # Book everything lazily, then let RDataFrame run it all in ONE pass over
    # the input instead of one pass per region (a full mt region set is ~25
    # regions x 4 counts).
    booked = {}
    skipped = {}
    for name in selected:
        if name not in available:
            skipped[name] = "mask branch absent from these ntuples"
            continue
        cuts = regions[name]
        expr = cut_string(cuts)
        expr_no_nbtag = cut_string(cuts, skip_tff_skipped_keys=True)
        if args.print_cuts:
            print(f"\n[{name}]\n  {expr}")
        mask_expr = f"({name} > 0.5)"
        booked[name] = dict(
            n_mask=rdf.Filter(mask_expr).Count(),
            n_cuts=rdf.Filter(f"({expr})").Count(),
            n_cuts_no_nbtag=rdf.Filter(f"({expr_no_nbtag})").Count(),
            mismatch=rdf.Filter(f"(({mask_expr}) != ({expr}))").Count(),
            # Same comparison with the preselection ANDed into the cut string:
            # the FF region definitions are written to be applied on top of the
            # preselection (that is what TauFakeFactors feeds them), so on a
            # raw, unskimmed ntuple the mask may legitimately follow either
            # convention depending on how CROWN composes it. Reporting both
            # tells you which one the production actually uses instead of
            # guessing — and a region is only accepted if one of them is 0.
            mismatch_presel=rdf.Filter(f"(({mask_expr}) != (({expr}) && {presel_expr}))").Count(),
        )

    if hasattr(ROOT.RDF, "RunGraphs") and booked:
        ROOT.RDF.RunGraphs([r for entry in booked.values() for r in entry.values()])

    print()
    print(f"Selection-mask validation — era={args.era} channel={args.channel}")
    print(f"input: {args.input}  ({len(files)} file(s), tree '{tree}')")
    print()
    print(_HEADER)
    print("-" * len(_HEADER))

    n_fail = 0
    for name in selected:
        if name in skipped:
            print(f"{name:<28} {'—':>12} {'—':>12} {'—':>10} {'—':>10} {'SKIP':>8} "
                  f"{'—':>13} {'—':>10}   ({skipped[name]})")
            continue
        r = booked[name]
        n_mask = r["n_mask"].GetValue()
        n_cuts = r["n_cuts"].GetValue()
        n_nob = r["n_cuts_no_nbtag"].GetValue()
        mis = r["mismatch"].GetValue()
        mis_p = r["mismatch_presel"].GetValue()
        # CROWN composes the ff_* masks as the region cut set ONLY -- the
        # preselection is a separate branch (presel_mask) that downstream
        # applies on its own, and split_categories (njets) stay downstream too.
        # So the region-only comparison is the one that must hold; the
        # +presel column is kept as diagnostics for reading a failure.
        ok = mis == 0
        status = "OK" if ok else "FAIL"
        if not ok:
            n_fail += 1
        print(f"{name:<28} {n_mask:>12d} {n_cuts:>12d} {mis:>10d} {mis_p:>10d} "
              f"{status:>8} {n_nob:>13d} {n_nob - n_mask:>+10d}")
        if not ok and args.fail_fast:
            print("\n--fail-fast: stopping at the first mismatching region.")
            break

    print()
    print("Columns")
    print("  N(mask)      events with <mask> > 0.5")
    print("  N(cuts)      events passing the yaml-faithful reconstructed cut string")
    print("  mismatch     events where mask and cut string disagree            -> must be 0")
    print("  +presel      same, with presel_mask ANDed into the cut string (diagnostic only)")
    print("               CROWN composes ff_* masks as the region cut set ONLY, so 'mismatch'")
    print("               is the column that decides PASS/FAIL. If mismatch != 0 but +presel")
    print("               == 0, someone folded the preselection into the mask upstream.")
    print("  N(no-nbtag)  cut string with nbtag/bb_selection dropped, i.e. what")
    print("               TauFakeFactors' apply_region_filters() selects TODAY")
    print("  delta        N(no-nbtag) - N(mask): the KNOWN, INTENDED difference. Expected")
    print("               non-zero wherever the yaml sets a real nbtag cut (Wjets nbtag==0")
    print("               everywhere; ttbar nbtag>=1 mt / >=2 et for 2022-23), and 0 where")
    print("               the yaml cut is vacuous (nbtag>=0). Not a failure.")
    print()

    if n_fail:
        print(f"RESULT: FAIL — {n_fail} of {len(booked)} checked region(s) mismatch.")
        return 1
    print(f"RESULT: PASS — all {len(booked)} checked region(s) match their cut strings "
          f"event-by-event.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
