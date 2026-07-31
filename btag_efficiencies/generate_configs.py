#!/usr/bin/env python3
"""
Regenerate btag_efficiencies/configs/{era}/preselection_{ch}.yaml's
``event_selection:`` block from TauKITFlow's central config, the same way
config/generate_tff_configs.py does for TauFakeFactors' own FF-measurement
preselection.

Background (Phase 6e): the btag-efficiency preselection config used to live
at TauFakeFactors/configs/btag_efficiency/{era}/preselection_{ch}.yaml with
its ``event_selection:`` block hand-typed as a literal, verbatim copy of most
of config/cuts.yaml's ``preselection:``/``channel_selection:`` entries (e.g.
``had_tau_decay_mode``, ``had_tau_id_vs_ele``, ``jet_veto``, the extra-lepton
vetoes, the opposite-sign requirement) -- a real, unreconciled duplicate of
the exact kind Phase 5.2 already fixed for TFF's smhtt_ul preselection and
shapes/selection/channel_selection.py. This script closes that gap for the
btag-efficiency config too.

Not everything in that block is a duplicate, though -- the b-tag efficiency
measurement deliberately uses a *wider* control region than the FF/shape
selection for some cuts (confirmed by diffing the old file against
config/cuts.yaml's channel_selection block): a looser transverse-mass cut
(``mt_1 < 50`` here vs. the central ``mt_cut: (mt_1 < 70)``) to keep more
statistics for the efficiency measurement. That's a genuine, intentional
difference, not undiscovered drift -- so it's kept as an explicit local
override (`_BTAG_CR_MT_CUT` below) rather than silently pulled from the
central getter, which would have made a future change to the central mt_cut
silently retune the btag efficiency measurement's control region too.

Everything else in event_selection (the preselection: cuts, the tau-vs-jet
WP cut, opposite-sign, lepton isolation, and extra-lepton vetoes) *is* a
straight duplicate of central config and is now single-sourced via
config.analysis.get_preselection_cuts()/get_channel_selection_cuts().

The ``em`` channel is deliberately left untouched: config/cuts.yaml's
preselection/channel_selection blocks don't cover ``em`` at all (same gap
noted in shapes/selection/channel_selection.py, Phase 5.2) so there is no
central source to regenerate it from; its preselection_em.yaml keeps its
existing hand-written event_selection.

Usage:
  python btag_efficiencies/generate_configs.py --era 2024 --channels et,mt,tt
  python btag_efficiencies/generate_configs.py --era all --channels all
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from config.logging_setup_configs import setup_logging
from config.analysis import get_preselection_cuts, get_channel_selection_cuts

logger = setup_logging(logger=logging.getLogger(__name__))

CONFIG_ROOT = Path(__file__).resolve().parent / "configs"

RUN3_ERAS = [
    "2022preEE",
    "2022postEE",
    "2023preBPix",
    "2023postBPix",
    "2024",
    "2025",
    "2026",
]
CHANNELS = ["et", "mt", "tt"]  # "em" is intentionally excluded -- see module docstring

# Tau-vsJet working point used for the btag efficiency measurement's own
# tau-ID cut -- matches common_settings.yaml's `tau_vs_jet_wgt_wps: [Medium]`
# in every existing era config.
_BTAG_CR_VS_JET_WP = "Medium"

# Intentionally looser than the central shape-production `mt_cut` (mt_1 < 70)
# -- see module docstring. Not sourced from config/cuts.yaml on purpose.
_BTAG_CR_MT_CUT = "(mt_1 < 50)"


def _build_event_selection(era: str, channel: str) -> dict:
    """
    event_selection = central preselection cuts (single-sourced) + the extra
    region-defining cuts the btag efficiency measurement needs on top (some
    single-sourced from channel_selection, one -- the mt cut -- intentionally
    not, see module docstring).
    """
    result = dict(get_preselection_cuts(era, channel))
    cs_cuts = get_channel_selection_cuts(channel, era)

    no_extra_lep = " && ".join(
        cs_cuts[k] for k in ("extraelec_veto", "extramuon_veto", "dilepton_veto")
    )

    if channel == "tt":
        result["had_tau_id_vs_jet_1"] = f"id_tau_vsJet_{_BTAG_CR_VS_JET_WP}_1 > 0.5"
        result["had_tau_id_vs_jet_2"] = f"id_tau_vsJet_{_BTAG_CR_VS_JET_WP}_2 > 0.5"
        result["tau_pair_sign"] = "(q_1*q_2) < 0"
        result["no_extra_lep"] = no_extra_lep
    else:
        iso_key = "ele_iso" if channel == "et" else "muon_iso"
        result["had_tau_id_vs_jet"] = (
            f"(id_tau_vsJet_{_BTAG_CR_VS_JET_WP}_2 > 0.5)"
        )
        result["lep_mt"] = _BTAG_CR_MT_CUT
        result["tau_pair_sign"] = cs_cuts["os"]
        result["lep_iso"] = cs_cuts[iso_key]
        result["no_extra_lep"] = no_extra_lep

    return result


def regenerate_config(era: str, channel: str, dry_run: bool = False) -> None:
    yaml_path = CONFIG_ROOT / era / f"preselection_{channel}.yaml"
    if not yaml_path.exists():
        logger.error(f"btag_efficiencies config not found: {yaml_path} — skipping")
        return

    existing = yaml.safe_load(yaml_path.read_text())
    existing["event_selection"] = _build_event_selection(era, channel)

    out_text = yaml.dump(existing, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if dry_run:
        logger.info(f"[dry-run] would write {yaml_path}")
        print(out_text)
        return

    yaml_path.write_text(out_text)
    logger.info(f"updated {yaml_path.relative_to(_REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate btag_efficiencies per-channel preselection "
        "event_selection blocks from central config."
    )
    parser.add_argument("--era", default="all", help="Era, or 'all' (default: all)")
    parser.add_argument(
        "--channels", default="all", help="Comma-separated channels, or 'all' "
        "(default: all -- note: 'em' is never regenerated, see module docstring)"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    eras = RUN3_ERAS if args.era == "all" else [e.strip() for e in args.era.split(",")]
    channels = CHANNELS if args.channels == "all" else [c.strip() for c in args.channels.split(",")]

    invalid_eras = [e for e in eras if e not in RUN3_ERAS]
    if invalid_eras:
        parser.error(f"Unknown era(s): {invalid_eras}. Valid: {RUN3_ERAS}")
    invalid_channels = [c for c in channels if c not in CHANNELS]
    if invalid_channels:
        parser.error(f"Unknown channel(s): {invalid_channels}. Valid: {CHANNELS} (+ 'em', never regenerated)")

    for era in eras:
        for channel in channels:
            regenerate_config(era, channel, dry_run=args.dry_run)

    if not args.dry_run:
        logger.info(
            f"Done — regenerated {len(eras) * len(channels)} btag_efficiencies "
            f"config(s) for eras={eras} channels={channels}"
        )


if __name__ == "__main__":
    main()
