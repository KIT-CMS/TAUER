"""
Central analysis configuration for TauKITFlow SM H→ττ analysis.

All data lives in three YAML files next to this module:
  config/samples.yaml    — background process/sample lists and signal sample names
  config/variables.yaml  — output_features (TFF branch list) and flags (process/era)
  config/cuts.yaml       — per-channel preselection event_selection cuts

This module reads those files and provides a Python API used by:
  config/shapes/tff_adapter.py  (backward-compat shim)
  shapes/selection/process_selection.py (reads get_luminosity())
  shapes/produce_shapes.py
  shapes/preselect.py
  trainings/create_training_dataset.py
  common/lcg_env.py (get_output_features(), via python -c under the LCG view -- used by run.py PRESEL mode)
  config/generate_tff_configs.py

TauFakeFactors and uncertainty-aware-training are NOT modified.

shapes/selection/process_selection.py and shapes/selection/variations.py stay as Python
modules, not YAML: they encode executable, era/channel-conditional weight- and
cut-string construction (chainable Selection composition, STXS stitching-weight
calculation, dataclasses) that would lose correctness and readability if flattened
to static data. That is a deliberate design choice, not an unfinished migration.
What *is* centralised here: every literal data table that used to live duplicated
inside those files — signal sample names (SIGNAL_SAMPLES, ex-signal_files.py),
per-era luminosity (get_luminosity(), ex-hardcoded in process_selection.lumi_weight),
mc_weights, preselection cuts, variables/binning — all single-sourced from the YAMLs
next to this module. process_selection.py/variations.py consume that data; they do
not redefine it.
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
    "2026",
)

# Run2 UL eras. Only relevant to plotting (era-correct CMS labels, see
# get_center_of_mass() below and the "luminosity" block in samples.yaml) —
# shape production (config/shapes/*.py, samples.yaml:backgrounds/:signals)
# does not cover Run2 in general, so these are NOT accepted by
# load_yaml()/RUN3_ERAS gated code paths.
RUN2_ERAS = (
    "2016preVFP",
    "2016postVFP",
    "2017",
    "2018",
)

# Phase 2a: of the Run2 eras above, only 2018 (mt/mm channels) has real
# shape-production support, scoped to the validation dataset available at
# rework time (jvoss's SFs_EMB_Run2_v15nanoAOD_29_06_26 CROWN production).
# 2016/2017 are plotting-label-only (see RUN2_ERAS) — no production support,
# no validation data.
RUN2_PRODUCTION_ERAS = ("2018",)

SUPPORTED_ERAS = RUN3_ERAS + RUN2_PRODUCTION_ERAS

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
    if era not in SUPPORTED_ERAS:
        raise ValueError(f"Era '{era}' not in supported eras: {SUPPORTED_ERAS}")
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


# ── CROWN selection masks ─────────────────────────────────────────────────────

def get_region_mask_names(era: str, channel: str) -> list[str]:
    """
    Names of the CROWN-precomputed boolean selection-mask branches available
    for the given era/channel, read from config/variables.yaml's
    `selection_masks:` block.

    Returns `common` (presel_mask, sel_os, sel_ss -- every scope) followed by
    the channel's fake-factor region masks (et/mt: QCD/Wjets/ttbar/fractions
    + DR_SR/AR_SR correction regions; tt: leading + subleading QCD; em: none).

    Deliberately NOT part of get_output_features(): those are analysis
    variables (they feed get_training_variables() and the control-plot
    variable set), these are pure bookkeeping branches. Callers that need the
    branches *kept on disk* -- shapes/preselect.py's Snapshot column list and
    config/generate_tff_configs.py's generated TFF `output_features:` block --
    concatenate the two lists explicitly.

    `era` is accepted (and validated) because the mask *content* is
    era-dependent (see the plan's era groups: tt trigger/pt, mt/et QCD lep_iso,
    Wjets mt_1, ttbar nbtag all change between 2022-23 and 2024+) even though
    the mask *names* are era-independent by design -- so downstream code never
    has to special-case an era, and this signature does not have to change if a
    future era ever gains or loses a region.
    """
    if era not in SUPPORTED_ERAS:
        raise ValueError(f"Era '{era}' not in supported eras: {SUPPORTED_ERAS}")
    cfg = _load_variables().get("selection_masks", {})
    names = list(cfg.get("common", []))
    names += list(cfg.get(channel, []) or [])
    # Preserve order, drop accidental duplicates (a channel block repeating a
    # common name would otherwise produce a duplicated Snapshot column).
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


# The one branch whose presence decides "these ntuples were produced with
# CROWN's selection.py". Every scope gets it (em included), so a single name
# is enough for the per-file detection below.
PRESELECTION_MASK_BRANCH = "presel_mask"


def masks_available(file_or_dir: str | Path, tree: str = "ntuple") -> bool:
    """
    True if the given ROOT input carries the `presel_mask` branch, i.e. was
    produced by a CROWN version that books the selection masks.

    `file_or_dir` may be a single .root file or a directory -- in the latter
    case the first .root file found (recursively, sorted for reproducibility)
    is inspected. Returns False, never raises, when nothing can be opened or
    read: this is a *capability probe* driving an automatic fallback to the
    legacy cut strings, so an unreachable/odd input must degrade to "no masks"
    rather than kill the job.

    Uses uproot (already a dependency here -- common/helper_collection.py,
    datasets/samplemanager/calculate_genweights.py) rather than PyROOT, so
    that it stays importable/cheap from the plain `taukitflow` conda env and
    from run.py's driver process, which never imports ROOT itself.
    """
    path = str(file_or_dir)
    if not path:
        return False

    candidate = path
    local = Path(path)
    # Only treat it as a directory to search when it's a local, non-remote path;
    # xrootd/remote URLs are always passed straight through to uproot.
    if "://" not in path and local.is_dir():
        found = sorted(local.rglob("*.root"))
        if not found:
            logger.warning(f"masks_available: no .root file under {path} — assuming no masks")
            return False
        candidate = str(found[0])

    try:
        import uproot
    except ImportError:  # pragma: no cover - uproot is a declared dependency
        logger.warning("masks_available: uproot not importable — assuming no masks")
        return False

    try:
        with uproot.open(candidate) as fh:
            obj = fh.get(tree, None)
            if obj is None:
                logger.warning(
                    f"masks_available: no '{tree}' tree in {candidate} — assuming no masks"
                )
                return False
            have = PRESELECTION_MASK_BRANCH in obj.keys()
    except Exception as exc:  # noqa: BLE001 -- probe must never be fatal
        logger.warning(f"masks_available: could not read {candidate} ({exc}) — assuming no masks")
        return False

    logger.info(
        f"masks_available: {candidate} "
        f"{'HAS' if have else 'does NOT have'} '{PRESELECTION_MASK_BRANCH}'"
    )
    return have


# ── Signal sample access ──────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _signal_samples() -> dict[str, dict[str, list[str]]]:
    return _load_samples()["signals"]


# Module-level alias; consumed directly by shapes/preselect.py
# (`from config.analysis import SIGNAL_SAMPLES as signal_files`).
SIGNAL_SAMPLES: dict[str, dict[str, list[str]]] = {}

def _lazy_init_signals():
    global SIGNAL_SAMPLES
    if not SIGNAL_SAMPLES:
        SIGNAL_SAMPLES.update(_signal_samples())

_lazy_init_signals()


# ── Background sample access ──────────────────────────────────────────────────

def get_background_processes(era: str) -> dict[str, dict]:
    """
    Raw per-TFF-process background info from config/samples.yaml for the
    given era: {tff_process: {"samples": [...], "tau_gen_modes": [...], ...}}.

    Unlike get_background_samples(), this preserves the original TFF process
    names (e.g. "DYjets") and each process's tau_gen_modes list -- needed by
    shapes/preselect.py's central background preselection and by
    build_presel_files_dict() to know how each process is split.
    """
    return _load_samples()["backgrounds"].get(era, {})


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
        if tff_proc in ("data", "EMB"):
            # Both are channel-dependent sample lists (per-run-period data,
            # per-final-state embedding), keyed the same way in samples.yaml.
            ch_samples = info.get("by_channel", {}).get(channel, [])
            result.setdefault(ds_key, []).extend(ch_samples)
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


# ── Channel access ──────────────────────────────────────────────────────────

def get_channels() -> list[str]:
    """
    All channels known to the central config, sourced from config/cuts.yaml's
    top-level `preselection:` keys (et, mt, tt, em, ...).

    Single source of truth for "which channels exist" — callers (e.g. the
    condor/ submission tooling) must use this instead of hardcoding a parallel
    channel list.
    """
    return list(_load_cuts()["preselection"].keys())


def vs_ele_wp_for(channel: str, override: str | None = None) -> str:
    """
    Default tau-vs-electron discriminator WP for the given channel, matching
    TauFakeFactors/configs/smhtt_ul's Run3 preselection configs: "Tight" for
    et (electron leg needs the tighter cut against electron fakes), "VVLoose"
    for every other channel (mt, tt, ...).

    Single source of truth -- callers (run.py, shapes/produce_shapes.py,
    condor/submit_shapes.py) must use this instead of hardcoding a parallel
    per-channel default. `override`, if given, always wins.
    """
    if override:
        return override
    return "Tight" if channel == "et" else "VVLoose"


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


def get_channel_selection_cuts(channel: str, era: str | None = None) -> dict[str, str]:
    """
    Return the shape-production-only channel_selection cuts (applied on top of
    the preselection cuts above -- extraelec_veto/extramuon_veto/dilepton_veto/
    os, plus per-channel tau_iso/mt_cut/ele_iso/muon_iso) for the given channel,
    read from config/cuts.yaml's `channel_selection:` block.

    Phase 5.2 note: this getter didn't exist before -- shapes/selection/
    channel_selection.py had these exact same cut strings hardcoded as Python
    literals, verbatim-duplicating (and never actually reading)
    config/cuts.yaml's `channel_selection:` block, which was consequently 100%
    dead YAML (confirmed by grep: nothing read the `channel_selection` top-level
    key before this). Single-sourced here; channel_selection.py now reads
    through this function instead of hardcoding the values a second time. See
    STATUS.md's Phase 5.2 section for the full duplication audit.

    Merges `common` (applies to every channel) with the channel-specific
    sub-block (channel-specific keys win on conflict). The `tau_iso` value
    contains a literal `{vs_jet_wp}` placeholder -- callers must
    `.format(vs_jet_wp=...)` it themselves (the WP is a shape-production
    runtime choice, not something this config layer knows about).
    Supports an optional per-channel `era_overrides` sub-block, mirroring
    get_preselection_cuts()'s pattern, for forward-compatibility -- none is
    defined in config/cuts.yaml today.
    """
    cs_cfg = _load_cuts()["channel_selection"]
    result: dict[str, str] = dict(cs_cfg.get("common", {}))
    ch_cfg = cs_cfg.get(channel, {})
    era_overrides = ch_cfg.get("era_overrides", {})
    result.update({k: v for k, v in ch_cfg.items() if k != "era_overrides"})
    if era is not None and era in era_overrides:
        result.update(era_overrides[era])
    return result


# ── MC ntuple production-era override ────────────────────────────────────────

# For 2026, no dedicated MC campaign exists yet -- the same 2025 Summer24 MC
# campaign is reused as-is (see samples.yaml:backgrounds.2026/signals.2026,
# whose MC sample names are identical to 2025's). Those physical CROWN
# ntuples/friends were never copied into a "2026" subdirectory on disk --
# they only exist under "2025". This map tells shape production which
# *directory* era to actually read MC ntuples/friends from, while DATA (the
# real 2026 datasets) is still read from its own "2026" directory. Update
# this (and nowhere else) if/when 2026 gets its own dedicated MC campaign.
MC_NTUPLE_ERA_OVERRIDE = {
    "2026": "2025",
}


def get_mc_ntuple_era(era: str) -> str:
    """
    Physical CROWN-production era directory to read MC ntuples/friends from
    for the given (analysis) era -- see MC_NTUPLE_ERA_OVERRIDE. Returns `era`
    unchanged for every era not explicitly overridden. Never applies to data
    (or embedding) -- those always read from their own real era's directory.
    """
    return MC_NTUPLE_ERA_OVERRIDE.get(era, era)


# ── Luminosity ───────────────────────────────────────────────────────────────

def get_luminosity(era: str) -> float:
    """Integrated luminosity for the given era, in fb^-1 (from config/samples.yaml)."""
    lumi = _load_samples()["luminosity"].get(era)
    if lumi is None:
        raise ValueError(f"Given era {era!r} not defined in config/samples.yaml:luminosity.")
    return float(lumi)


def get_center_of_mass(era: str) -> float:
    """
    LHC center-of-mass energy in TeV for the given era.

    13.0 TeV for Run2 (era in RUN2_ERAS), 13.6 TeV for Run3 (era in
    RUN3_ERAS) — matches smhtt_ul's Dumbledraw DrawLumi() era branch.
    Used by plotting/plot_shapes_control.py for the CMS label.
    """
    if era in RUN2_ERAS:
        return 13.0
    if era in RUN3_ERAS:
        return 13.6
    raise ValueError(f"Given era {era!r} is not a known Run2 or Run3 era.")


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
    Files dict for preselected ntuples produced by shapes/preselect.py
    (central background preselection) / TauFakeFactors' preselection.py.

    After preselection there is exactly ONE physical file per
    (process, tau_gen_mode) -- all original per-sample physical files (and,
    for "data", all per-run-period files) have already been concatenated by
    the preselection step, matching TauFakeFactors'
    helper.functions.get_output_name() naming convention: the "all" mode
    suffix is dropped (bare "<process>.root"), every other mode is
    "<process>_<mode>.root". So both the ntuple_processor.booking sample-key
    AND its one-element file_names list must be that same generated name --
    NOT the pre-preselection list of original physical sample names (that
    would make booking glob for a per-original-sample directory that no
    longer exists after concatenation).

        {presel_dir}/{era}/{key}/{channel}/{key}.root   where
        key = tff_process if tau_gen_mode == "all" else f"{tff_process}_{tau_gen_mode}"
    """
    result: dict = {era: {}}
    bg_raw = get_background_processes(era)
    for channel in channels:
        ch_dict: dict = {}
        for tff_proc, info in bg_raw.items():
            for mode in info.get("tau_gen_modes", ["all"]):
                key = tff_proc if mode == "all" else f"{tff_proc}_{mode}"
                ch_dict[key] = [key]
        for sig_key, sig_samples in _signal_samples().get(era, {}).items():
            ch_dict[sig_key] = list(sig_samples)
        result[era][channel] = ch_dict
    return result

