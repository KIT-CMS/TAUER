#!/usr/bin/env python3
"""
Regenerate btag_efficiencies/configs/{era}/preselection_{ch}.yaml's ``event_selection:`` block
from CROWN's ``SR_mask`` friend-tree branch and its weight from CROWN's ``weight_no_btag``
(the b-tag SF itself is derived from these efficiencies; see common_settings.yaml's
``friends: ["selection"]`` and fake_factors/preselection.py's friend-tree handling).
mm/ee are not regenerated: their friend weight is a constant 1 and the former mc_weights are no longer supported.
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

CONFIG_ROOT = Path(__file__).resolve().parent / "configs"

ERAS = ["2022preEE", "2022postEE", "2023preBPix", "2023postBPix", "2024", "2025"]
CHANNELS = ["et", "mt", "tt", "em"]


def regenerate_config(era: str, channel: str, dry_run: bool = False) -> None:
    yaml_path = CONFIG_ROOT / era / f"preselection_{channel}.yaml"
    if not yaml_path.exists():
        logger.error(f"btag_efficiencies config not found: {yaml_path} — skipping")
        return

    existing = yaml.safe_load(yaml_path.read_text())
    existing["event_selection"] = {"SR_mask": "(SR_mask > 0.5)"}
    existing.pop("mc_weights", None)
    existing["friend_weight"] = "weight_no_btag"

    out_text = yaml.dump(existing, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if dry_run:
        logger.info(f"[dry-run] would write {yaml_path}")
        print(out_text)
        return

    yaml_path.write_text(out_text)
    logger.info(f"updated {yaml_path.relative_to(_REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate the btag_efficiencies per-channel preselection selection and weight from the CROWN friend columns.")
    parser.add_argument("--era", default="all", help="Comma-separated eras, or 'all' (default: all)")
    parser.add_argument("--channels", default="all", help="Comma-separated channels, or 'all' (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    eras = ERAS if args.era == "all" else [e.strip() for e in args.era.split(",")]
    channels = CHANNELS if args.channels == "all" else [c.strip() for c in args.channels.split(",")]

    invalid_eras = [e for e in eras if e not in ERAS]
    if invalid_eras:
        parser.error(f"Unknown era(s): {invalid_eras}. Valid: {ERAS}")
    invalid_channels = [c for c in channels if c not in CHANNELS]
    if invalid_channels:
        parser.error(f"Unknown channel(s): {invalid_channels}. Valid: {CHANNELS}")

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
