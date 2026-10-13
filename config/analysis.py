import logging
import os
from functools import lru_cache
from pathlib import Path

import yaml

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

# ── Paths ─────────────────────────────────────────────────────────────────────
_CFG_DIR = Path(__file__).resolve().parent          # config/

_BACKGROUNDS_YAML = _CFG_DIR / "backgrounds.yaml"
_VARIABLES_YAML = _CFG_DIR / "variables.yaml"

# The active pluggable analysis. Everything else in this module (backgrounds, cuts,
# weights, era/channel/mask machinery) is generic across tau analyses.
ACTIVE_ANALYSIS = os.environ.get("TAUER_ANALYSIS", "smhtt")
_ANALYSIS_SIGNALS_YAML = _CFG_DIR.parent / "analyses" / ACTIVE_ANALYSIS / "config" / "signals.yaml"

# ── Constants ─────────────────────────────────────────────────────────────────
RUN3_ERAS = (
    "2022preEE",
    "2022postEE",
    "2023preBPix",
    "2023postBPix",
    "2024",
    "2025",
    "2026",
)

# Run2 UL eras (plotting labels only, except RUN2_PRODUCTION_ERAS below).
RUN2_ERAS = (
    "2016preVFP",
    "2016postVFP",
    "2017",
    "2018",
)

# Only 2018 (mt/mm) has real shape-production support; 2016/2017 are plotting-label-only.
RUN2_PRODUCTION_ERAS = ("2018",)

SUPPORTED_ERAS = RUN3_ERAS + RUN2_PRODUCTION_ERAS

# Fake factors are measured on the combined pre-/post-era parts (one set of
# fake_factors_*/corrections_* configs per year, under `2022`/`2023`).
_FF_CONFIG_ERA: dict[str, str] = {
    "2022preEE": "2022",
    "2022postEE": "2022",
    "2023preBPix": "2023",
    "2023postBPix": "2023",
}


def ff_config_era(era: str) -> str:
    if era not in SUPPORTED_ERAS:
        raise ValueError(f"Era '{era}' not in supported eras: {SUPPORTED_ERAS}")
    return _FF_CONFIG_ERA.get(era, era)


FF_BASE_COMPONENTS = ("StatShift", "SystBandAsym", "SystBandHigh", "SystBandLow", "SystMCShift")
FF_CORR_COMPONENTS = ("StatShift", "SystBandAsym", "SystMCShift")


# (fake factor era, channel) with machine-learned fake factors (CROWN sm_fake_factors_generic with USE_ML, --ff-type ml_*): process -> non-closure components of its classic corrections
FF_ML = {("2018", "mt"): {"QCD": FF_CORR_COMPONENTS, "Wjets": FF_CORR_COMPONENTS, "ttbar": ("StatShift", "SystBandAsym")}}
FF_ML_COMPONENTS = ("", "Stat", "Normalization")


# the CROWN fake factor shifts are named like the nuisances: fake_factor_<leg>__<nuisance>Up/Down
def ff_component_names(process: str, era: str, channel: str, dr_sr: bool = True, ml: bool = False) -> list[str]:
    ff_era = ff_config_era(era)
    name = lambda *parts: "_".join(["CMS_fake_t", process, *filter(None, parts), ff_era, channel])
    if ml and (ff_era, channel) in FF_ML:
        names = [name(c) for c in FF_ML_COMPONENTS] + [name("fraction"), name("fraction", "Stat")]
        if dr_sr:
            names += [name("DR_SR_Corr", c) for c in FF_ML_COMPONENTS]
        return names + [name(f"non_closure_Corr{c}") for c in FF_ML[(ff_era, channel)][process]]
    names = [name(c) for c in FF_BASE_COMPONENTS] + [name("fraction")]
    if dr_sr:
        names += [name(f"DR_SR_Corr{c}") for c in FF_CORR_COMPONENTS]
    return names + [name(f"non_closure_Corr{c}") for c in FF_CORR_COMPONENTS]


# TFF process name → ntuple_processor dataset key
_TFF_TO_DATASET: dict[str, str] = {
    "DYjets":  "DY",
    "ttbar":   "TT",
    "diboson": "VV",
    "ST":      "VV",   # single-top merged into VV
    "Wjets":   "W",
    "data":    "data",
    "EMB":     "EMB",  # embedded (data-derived) ZTT background
}

# ── YAML loaders (cached) ─────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_backgrounds() -> dict:
    return yaml.safe_load(_BACKGROUNDS_YAML.read_text())


@lru_cache(maxsize=1)
def _load_variables() -> dict:
    return yaml.safe_load(_VARIABLES_YAML.read_text())


# ── Column / variable access ──────────────────────────────────────────────────

def get_output_features() -> list[str]:
    return list(_load_variables()["output_features"])


def get_flags() -> list[str]:
    return list(_load_variables()["flags"])


def get_training_variables() -> list[str]:
    return get_output_features() + get_flags()


# ── CROWN selection masks ─────────────────────────────────────────────────────

# Preselection-only mask; missing for `em` (no FF regions either). Used by TauFakeFactors.
PRESELECTION_MASK_BRANCH = "presel_mask"
# Shift-aware signal-region mask (et/mt/tt/em) -- shapes/produce_shapes.py's nominal (OS) cut.
SR_MASK_BRANCH = "SR_mask"
# SR_MASK_BRANCH with OS swapped for SS -- the same-sign QCD control region.
SR_MASK_SS_BRANCH = "SR_mask_ss"
# SR_MASK_BRANCH with the tau isolation inverted (et/mt/tt) -- the application region of the fake factors.
AR_MASK_BRANCH = "AR_mask"


# ── Signal sample access ──────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _signal_samples() -> dict[str, dict[str, list[str]]]:
    return yaml.safe_load(_ANALYSIS_SIGNALS_YAML.read_text())["signals"]


# Module-level alias; consumed directly by shapes/preselect.py
# (`from config.analysis import SIGNAL_SAMPLES as signal_files`).
SIGNAL_SAMPLES: dict[str, dict[str, list[str]]] = {}

def _lazy_init_signals():
    if not SIGNAL_SAMPLES:
        SIGNAL_SAMPLES.update(_signal_samples())

_lazy_init_signals()


def get_signal_process_keys() -> set[str]:
    return {key for era_signals in _signal_samples().values() for key in era_signals}


# ── Background sample access ──────────────────────────────────────────────────

def get_background_samples(era: str, channel: str) -> dict[str, list[str]]:
    bg = _load_backgrounds()["backgrounds"].get(era, {})
    result: dict[str, list[str]] = {}
    for tff_proc, info in bg.items():
        ds_key = _TFF_TO_DATASET.get(tff_proc)
        if ds_key is None:
            logger.debug(f"Skipping unknown TFF process '{tff_proc}'")
            continue
        if tff_proc in ("data", "EMB"):
            # Both are channel-dependent sample lists (per-run-period data,
            # per-final-state embedding), keyed the same way in backgrounds.yaml.
            ch_samples = info.get("by_channel", {}).get(channel, [])
            result.setdefault(ds_key, []).extend(ch_samples)
        else:
            result.setdefault(ds_key, []).extend(info.get("samples", []))
    return result


def get_samples(
    era: str, channel: str, include_signals: bool = True
) -> dict[str, list[str]]:
    result = get_background_samples(era, channel)
    if include_signals:
        for key, samples in _signal_samples().get(era, {}).items():
            result[key] = list(samples)
    return result


# ── Channel access ──────────────────────────────────────────────────────────

def get_channels() -> list[str]:
    return ["et", "mt", "tt", "em"]


# tau vsJet WP of the signal region, same as CROWN's (the SFs of the WP are in the friend `weight`)
TAU_VS_JET_WP = "Medium"


# ── MC ntuple production-era override ────────────────────────────────────────

# 2026 has no dedicated MC campaign yet -- reuses 2025's ntuples/friends on disk.
# DATA still reads from its own "2026" directory.
MC_NTUPLE_ERA_OVERRIDE = {
    "2026": "2025",
}


def get_mc_ntuple_era(era: str) -> str:
    return MC_NTUPLE_ERA_OVERRIDE.get(era, era)


# ── Merged data eras ─────────────────────────────────────────────────────────

# Analysis era -> further data-taking eras whose DATA is merged into it. MC stays the
# analysis era's own, normalized to the summed lumi; the plot label lists every era.
DATA_ERA_MERGE = {
    "2025": ("2026",),
}

# Opt-in override to un-merge an era's data for a one-off run, without touching the
# default every other concurrent run relies on. Comma-separated eras, e.g.
# TAUER_NO_DATA_ERA_MERGE=2025.
_NO_DATA_ERA_MERGE = frozenset(
    e.strip() for e in os.environ.get("TAUER_NO_DATA_ERA_MERGE", "").split(",") if e.strip()
)


def get_data_eras(era: str) -> list[str]:
    if era in _NO_DATA_ERA_MERGE:
        return [era]
    return [era, *DATA_ERA_MERGE.get(era, ())]


# ── Luminosity ───────────────────────────────────────────────────────────────

def get_era_luminosity(era: str) -> float:
    lumi = _load_backgrounds()["luminosity"].get(era)
    if lumi is None:
        raise ValueError(f"Given era {era!r} not defined in config/backgrounds.yaml:luminosity.")
    return float(lumi)


def get_luminosity(era: str) -> float:
    return sum(get_era_luminosity(e) for e in get_data_eras(era))


def get_center_of_mass(era: str) -> float:
    if era in RUN2_ERAS:
        return 13.0
    if era in RUN3_ERAS:
        return 13.6
    raise ValueError(f"Given era {era!r} is not a known Run2 or Run3 era.")


# ── ntuple_processor files dicts ─────────────────────────────────────────────

def build_files_dict(channels: list[str], era: str) -> dict:
    result: dict = {era: {}}
    for channel in channels:
        result[era][channel] = get_samples(era, channel, include_signals=True)
        logger.info(
            f"[{era}/{channel}] loaded "
            f"{sum(len(v) for v in result[era][channel].values())} sample entries"
        )
    return result
