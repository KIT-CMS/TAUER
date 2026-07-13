"""
Central analysis configuration for TauKITFlow SM H→ττ analysis.

All data lives in three YAML files next to this module:
  config/samples.yaml    — background process/sample lists and signal sample names
  config/variables.yaml  — output_features (TFF branch list) and flags (process/era)
  config/cuts.yaml       — per-channel preselection event_selection cuts

This module reads those files and provides a Python API used by:
  config/shapes/tff_adapter.py  (backward-compat shim)
  config/shapes/signal_files.py (backward-compat shim)
  shapes/produce_shapes.py
  shapes/preselect.py
  trainings/create_training_dataset.py
  run.sh  (via python -c)
  config/generate_tff_configs.py

TauFakeFactors and uncertainty-aware-training are NOT modified.
config/shapes/variations.py is NOT modified.
"""

import logging
from functools import lru_cache
from pathlib import Path

import yaml

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

# ── Paths ─────────────────────────────────────────────────────────────────────
_CFG_DIR = Path(__file__).resolve().parent          # config/
_REPO_ROOT = _CFG_DIR.parent                        # repo root

TFF_ROOT = _REPO_ROOT / "TauFakeFactors"
TFF_CONFIG_ROOT = TFF_ROOT / "configs" / "smhtt_ul"

_SAMPLES_YAML   = _CFG_DIR / "samples.yaml"
_VARIABLES_YAML = _CFG_DIR / "variables.yaml"
_CUTS_YAML      = _CFG_DIR / "cuts.yaml"
_WEIGHTS_YAML   = _CFG_DIR / "weights.yaml"

# ── Constants ─────────────────────────────────────────────────────────────────
RUN3_ERAS = (
    "2022preEE",
    "2022postEE",
    "2023preBPix",
    "2023postBPix",
    "2024",
    "2025",
)

# TFF process name → ntuple_processor dataset key
_TFF_TO_DATASET: dict[str, str] = {
    "DYjets":  "DY",
    "ttbar":   "TT",
    "diboson": "VV",
    "ST":      "VV",   # single-top merged into VV
    "Wjets":   "W",
    "data":    "data",
}

# ── YAML loaders (cached) ─────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_samples() -> dict:
    return yaml.safe_load(_SAMPLES_YAML.read_text())


@lru_cache(maxsize=1)
def _load_variables() -> dict:
    return yaml.safe_load(_VARIABLES_YAML.read_text())


@lru_cache(maxsize=1)
def _load_cuts() -> dict:
    return yaml.safe_load(_CUTS_YAML.read_text())


@lru_cache(maxsize=1)
def _load_weights() -> dict:
    return yaml.safe_load(_WEIGHTS_YAML.read_text())


# ── TFF YAML loader (kept for tff_adapter shim + generate_tff_configs) ────────

def load_yaml(era: str, channel: str) -> dict:
    """Load the TauFakeFactors preselection YAML for the given era and channel."""
    if era not in RUN3_ERAS:
        raise ValueError(f"Era '{era}' not in supported eras: {RUN3_ERAS}")
    path = TFF_CONFIG_ROOT / era / f"preselection_{channel}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"TFF preselection config not found: {path}\n"
            "Run: git submodule update --init TauFakeFactors"
        )
    with open(path) as fh:
        return yaml.safe_load(fh)


# ── Column / variable access ──────────────────────────────────────────────────

def get_output_features() -> list[str]:
    """Return the output_features list from config/variables.yaml (TFF branch whitelist)."""
    return list(_load_variables()["output_features"])


def get_flags() -> list[str]:
    """Return the flags list from config/variables.yaml (process/era flags for training)."""
    return list(_load_variables()["flags"])


def get_training_variables() -> list[str]:
    """Return the combined training variable list: output_features + flags."""
    return get_output_features() + get_flags()


# Backward-compat alias (run.sh uses get_columns)
def get_columns() -> list[str]:
    return get_output_features()


# Module-level constants populated at import time
OUTPUT_FEATURES: list[str] = []
FLAGS: list[str] = []
PRESEL_COLUMNS: list[str] = []        # backward-compat alias for OUTPUT_FEATURES
TRAINING_VARIABLES: list[str] = []    # combined output_features + flags

def _lazy_init():
    global OUTPUT_FEATURES, FLAGS, PRESEL_COLUMNS, TRAINING_VARIABLES
    if not OUTPUT_FEATURES:
        OUTPUT_FEATURES = get_output_features()
        FLAGS = get_flags()
        PRESEL_COLUMNS = OUTPUT_FEATURES  # backward compat
        TRAINING_VARIABLES = OUTPUT_FEATURES + FLAGS

_lazy_init()


# ── Signal sample access ──────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _signal_samples() -> dict[str, dict[str, list[str]]]:
    return _load_samples()["signals"]

# Module-level alias kept for backward compat (signal_files.py shim)
SIGNAL_SAMPLES: dict[str, dict[str, list[str]]] = {}

def _lazy_init_signals():
    global SIGNAL_SAMPLES
    if not SIGNAL_SAMPLES:
        SIGNAL_SAMPLES.update(_signal_samples())

_lazy_init_signals()


# ── Background sample access ──────────────────────────────────────────────────

def get_background_samples(era: str, channel: str) -> dict[str, list[str]]:
    """
    Background samples from config/samples.yaml, mapped to ntuple_processor keys.

    Returns: {'DY': [...], 'TT': [...], 'VV': [...], 'W': [...], 'data': [...]}
    """
    bg = _load_samples()["backgrounds"].get(era, {})
    result: dict[str, list[str]] = {}
    for tff_proc, info in bg.items():
        ds_key = _TFF_TO_DATASET.get(tff_proc)
        if ds_key is None:
            logger.debug(f"Skipping unknown TFF process '{tff_proc}'")
            continue
        if tff_proc == "data":
            ch_samples = info.get("by_channel", {}).get(channel, [])
            result.setdefault("data", []).extend(ch_samples)
        else:
            result.setdefault(ds_key, []).extend(info.get("samples", []))
    return result


def get_samples(
    era: str, channel: str, include_signals: bool = True
) -> dict[str, list[str]]:
    """All samples: backgrounds + optionally signals."""
    result = get_background_samples(era, channel)
    if include_signals:
        for key, samples in _signal_samples().get(era, {}).items():
            result[key] = list(samples)
    return result


# ── Preselection cuts access ──────────────────────────────────────────────────

def get_preselection_cuts(era: str, channel: str) -> dict[str, str]:
    """
    Return the event_selection dict for the given era and channel.

    Reads from config/cuts.yaml; applies era-specific overrides where defined
    (e.g. tt trigger pT threshold changes between 2022/23 and 2024+).
    """
    cuts_cfg = _load_cuts()["preselection"].get(channel, {})
    era_overrides = cuts_cfg.get("era_overrides", {})
    # Build fresh dict excluding the era_overrides meta-key
    result = {k: v for k, v in cuts_cfg.items() if k != "era_overrides"}
    if era in era_overrides:
        result.update(era_overrides[era])
    return result


# ── MC weights ───────────────────────────────────────────────────────────────

def get_mc_weights(era: str, channel: str) -> dict[str, str]:
    """
    Flat mc_weights dict for the given era and channel, read from config/weights.yaml.

    Merges common weights + channel-specific weights, then applies any
    era_overrides defined for the channel (e.g. tt trigger branch for 2024+).
    """
    wcfg = _load_weights()["mc_weights"]
    result: dict[str, str] = {}
    result.update(wcfg.get("common", {}))
    ch_block = wcfg.get(channel, {})
    era_overrides = ch_block.get("era_overrides", {})
    result.update({k: v for k, v in ch_block.items() if k != "era_overrides"})
    if era in era_overrides:
        result.update(era_overrides[era])
    return result


# ── ntuple_processor files dicts ─────────────────────────────────────────────

def build_files_dict(channels: list[str], era: str) -> dict:
    """
    Nested files dict for shapes/utils.py::get_nominal_datasets.

        {era: {channel: {dataset_key: [sample_names]}}}
    """
    result: dict = {era: {}}
    for channel in channels:
        result[era][channel] = get_samples(era, channel, include_signals=True)
        logger.info(
            f"[{era}/{channel}] loaded "
            f"{sum(len(v) for v in result[era][channel].values())} sample entries"
        )
    return result


def build_presel_files_dict(channels: list[str], era: str) -> dict:
    """
    Files dict for preselected ntuples produced by shapes/preselect.py.

    Background sample names are expanded with tau_gen_mode suffix so
    ntuple_processor can locate the CROWN-compatible preselected directories.

        {presel_dir}/{era}/{tff_process}_{gen_mode}/{channel}/ntuple.root
    """
    result: dict = {era: {}}
    bg_raw = _load_samples()["backgrounds"].get(era, {})
    for channel in channels:
        ch_dict: dict = {}
        for tff_proc, info in bg_raw.items():
            if tff_proc == "data":
                ch_dict["data"] = info.get("by_channel", {}).get(channel, [])
                continue
            for mode in info.get("tau_gen_modes", ["all"]):
                key = f"{tff_proc}_{mode}"
                ch_dict[key] = info.get("samples", [])
        for sig_key, sig_samples in _signal_samples().get(era, {}).items():
            ch_dict[sig_key] = list(sig_samples)
        result[era][channel] = ch_dict
    return result


# ── Combined samples (used by old tff_adapter shim) ──────────────────────────

def get_combined_files(era: str, channel: str) -> dict[str, list[str]]:
    """Alias for get_samples() kept for backward compat."""
    return get_samples(era, channel, include_signals=True)

