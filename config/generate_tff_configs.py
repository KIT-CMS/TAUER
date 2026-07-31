#!/usr/bin/env python3
"""
Regenerate TauFakeFactors per-channel preselection_{ch}.yaml from unified
config YAML files.

The authoritative sources are:
  config/samples.yaml    — background/data/signal sample lists (read directly here)
  config/variables.yaml  — output_features (read directly here)
  config/cuts.yaml       — per-channel event_selection cuts (via config.analysis.get_preselection_cuts)
  config/weights.yaml    — mc_weights per channel (via config.analysis.get_mc_weights)

This script regenerates all sections, for each (era, channel) pair:
  TauFakeFactors/configs/smhtt_ul/{era}/preselection_{ch}.yaml

Sections updated from the unified config:
  processes       — sample lists and tau_gen_modes (from samples.yaml)
  event_selection — cut expressions          (config.analysis.get_preselection_cuts)
  mc_weights      — weighting expressions    (config.analysis.get_mc_weights)
  output_features — branch list              (from variables.yaml output_features)

Phase 6e note: event_selection/mc_weights used to be built by two local helpers
here (_build_event_selection/_build_mc_weights) that re-implemented the exact
same common+per-channel+era_overrides merge config/analysis.py already does
for shapes/selection/channel_selection.py's own consumption of the same YAMLs
— i.e. this script had its own private copy of that merge logic. Removed;
this script now calls config.analysis.get_preselection_cuts()/get_mc_weights()
directly, so there is exactly one implementation of "resolve era/channel cuts
and weights from the central YAMLs" in the whole repo. See STATUS.md's
Phase 6e section. This is also what btag_efficiencies/generate_configs.py
(new in this phase) uses for the same reason.

Usage:
  python config/generate_tff_configs.py --era 2022postEE --channels et,mt,tt
  python config/generate_tff_configs.py --era all --channels all

  or from run.py:
  python3 run.py GEN-TFF-CONFIGS --era 2022postEE --channels mt,et
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CFG_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))

from config.logging_setup_configs import setup_logging
from config.analysis import get_preselection_cuts, get_mc_weights

logger = setup_logging(logger=logging.getLogger(__name__))

TFF_CONFIG_ROOT = _REPO_ROOT / "TauFakeFactors" / "configs" / "smhtt_ul"

_SAMPLES_YAML   = _CFG_DIR / "samples.yaml"
_VARIABLES_YAML = _CFG_DIR / "variables.yaml"

RUN3_ERAS = [
    "2022preEE",
    "2022postEE",
    "2023preBPix",
    "2023postBPix",
    "2024",
    "2025",
    "2026",
]
CHANNELS = ["et", "mt", "tt"]

# Canonical process order to match original TFF YAML layout
_PROCESS_ORDER = ["DYjets", "ST", "Wjets", "data", "diboson", "ttbar"]


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _build_processes_block(
    era: str, channel: str, bg_era: dict
) -> dict:
    """Build the ``processes:`` block for a given era/channel."""
    processes: dict = {}
    for proc in _PROCESS_ORDER:
        info = bg_era.get(proc)
        if info is None:
            continue
        if proc == "data":
            ch_samples = info.get("by_channel", {}).get(channel, [])
            processes["data"] = {
                "samples": ch_samples,
                "tau_gen_modes": info.get("tau_gen_modes", ["all"]),
            }
        else:
            processes[proc] = {
                "samples": info.get("samples", []),
                "tau_gen_modes": info.get("tau_gen_modes", ["all"]),
            }
    return processes


def regenerate_config(
    era: str,
    channel: str,
    samples: dict,
    variables: dict,
    dry_run: bool = False,
) -> None:
    tff_yaml_path = TFF_CONFIG_ROOT / era / f"preselection_{channel}.yaml"
    if not tff_yaml_path.exists():
        logger.error(f"TFF config not found: {tff_yaml_path} — skipping")
        return

    bg_era = samples.get("backgrounds", {}).get(era, {})
    processes = _build_processes_block(era, channel, bg_era)
    # Single-sourced: both getters live in config/analysis.py and are also what
    # shapes/selection/channel_selection.py and process_selection.py read for
    # the exact same era/channel — this script no longer re-parses cuts.yaml/
    # weights.yaml itself (Phase 6e; previously duplicated the era_overrides
    # merge logic that config.analysis already implements).
    event_selection = get_preselection_cuts(era, channel)
    mc_weights = get_mc_weights(era, channel)
    output_features = list(variables.get("output_features", []))

    new_cfg: dict = {
        "channel": channel,
        "processes": processes,
        "event_selection": event_selection,
        "mc_weights": mc_weights,
        "output_features": output_features,
    }

    out_text = yaml.dump(new_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if dry_run:
        logger.info(f"[dry-run] would write {tff_yaml_path}")
        print(out_text)
        return

    tff_yaml_path.write_text(out_text)
    logger.info(f"updated {tff_yaml_path.relative_to(_REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate TFF per-channel preselection YAMLs from unified config."
    )
    parser.add_argument(
        "--era",
        default="all",
        help="Era to regenerate, or 'all' for all eras (default: all)",
    )
    parser.add_argument(
        "--channels",
        default="all",
        help="Comma-separated channels, or 'all' (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing files",
    )
    args = parser.parse_args()

    eras = RUN3_ERAS if args.era == "all" else [e.strip() for e in args.era.split(",")]
    channels = CHANNELS if args.channels == "all" else [c.strip() for c in args.channels.split(",")]

    invalid_eras = [e for e in eras if e not in RUN3_ERAS]
    if invalid_eras:
        parser.error(f"Unknown era(s): {invalid_eras}. Valid: {RUN3_ERAS}")
    invalid_channels = [c for c in channels if c not in CHANNELS]
    if invalid_channels:
        parser.error(f"Unknown channel(s): {invalid_channels}. Valid: {CHANNELS}")

    samples   = _load_yaml(_SAMPLES_YAML)
    variables = _load_yaml(_VARIABLES_YAML)

    for era in eras:
        for channel in channels:
            regenerate_config(era, channel, samples, variables, dry_run=args.dry_run)

    if not args.dry_run:
        logger.info(
            f"Done — regenerated {len(eras) * len(channels)} TFF config(s) "
            f"for eras={eras} channels={channels}"
        )


if __name__ == "__main__":
    main()
