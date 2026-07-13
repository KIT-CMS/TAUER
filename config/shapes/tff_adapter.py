"""
Backward-compatibility shim.

All functionality has moved to config/analysis.py.
Existing imports of the form::

    from config.shapes.tff_adapter import build_files_dict, ...

continue to work unchanged.
"""

import yaml 
from config.analysis import (
    TFF_ROOT,
    TFF_CONFIG_ROOT,
    RUN3_ERAS,
    _TFF_TO_DATASET,
    load_yaml as _load_tff_yaml,
    get_background_samples as get_background_sample_names,
    get_preselection_cuts as get_tff_event_selection,
    get_mc_weights as get_tff_mc_weights,
    get_samples as get_combined_files,
    build_files_dict,
    build_presel_files_dict,
)

__all__ = [
    "TFF_ROOT",
    "TFF_CONFIG_ROOT",
    "RUN3_ERAS",
    "_TFF_TO_DATASET",
    "_load_tff_yaml",
    "get_background_sample_names",
    "get_tff_event_selection",
    "get_tff_mc_weights",
    "get_combined_files",
    "build_files_dict",
    "build_presel_files_dict",
]


def _load_tff_yaml(era: str, channel: str) -> dict:
    """Load TauFakeFactors preselection YAML for the given era and channel."""
    if era not in RUN3_ERAS:
        raise ValueError(f"Era '{era}' is not a supported Run3 era. Supported: {RUN3_ERAS}")
    path = TFF_CONFIG_ROOT / era / f"preselection_{channel}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"TFF preselection config not found: {path}\n"
            f"Check that the TauFakeFactors submodule is initialised:\n"
            f"  git submodule update --init TauFakeFactors\n"
            f"Expected root: {TFF_ROOT}"
        )
    with open(path) as f:
        return yaml.safe_load(f)


def get_background_sample_names(era: str, channel: str) -> dict[str, list[str]]:
    """
    Return a dict mapping dataset key → list of sample name strings,
    for background processes only, sourced from TFF preselection config.

    Keys returned: 'DY', 'TT', 'VV', 'W', 'data'
    """
    cfg = _load_tff_yaml(era, channel)
    result: dict[str, list[str]] = {}
    for tff_proc, info in cfg.get("processes", {}).items():
        ds_key = _TFF_TO_DATASET.get(tff_proc)
        if ds_key is None:
            logger.debug(f"Skipping unknown TFF process '{tff_proc}'")
            continue
        samples = info.get("samples", [])
        if ds_key not in result:
            result[ds_key] = []
        result[ds_key].extend(samples)
    logger.debug(f"[{era}/{channel}] background samples: { {k: len(v) for k, v in result.items()} }")
    return result


def get_tff_event_selection(era: str, channel: str) -> dict[str, str]:
    """
    Return the event_selection dict from the TFF preselection YAML.
    Keys are cut names, values are cut string expressions.
    """
    cfg = _load_tff_yaml(era, channel)
    return dict(cfg.get("event_selection", {}))


def get_tff_mc_weights(era: str, channel: str) -> dict[str, str]:
    """
    Return the mc_weights dict from the TFF preselection YAML.
    """
    cfg = _load_tff_yaml(era, channel)
    return dict(cfg.get("mc_weights", {}))


def get_combined_files(era: str, channel: str) -> dict[str, list[str]]:
    """
    Return the full files dict (backgrounds + signals) for use in
    shapes/utils.py::get_nominal_datasets.

    Signal samples are added from config/shapes/signal_files.py.
    """
    from config.shapes.signal_files import signal_files

    bg = get_background_sample_names(era, channel)
    sig = signal_files.get(era, {})

    result = dict(bg)
    for key, samples in sig.items():
        result[key] = list(samples)

    logger.info(
        f"[{era}/{channel}] loaded {sum(len(v) for v in result.values())} sample entries "
        f"({len(bg)} background groups + {len(sig)} signal groups)"
    )
    return result


def build_files_dict(channels: list[str], era: str) -> dict:
    """
    Build the nested files dict expected by shapes/utils.py::get_nominal_datasets:
        files[era][channel] = {dataset_key: [sample_names]}
    """
    result = {era: {}}
    for channel in channels:
        result[era][channel] = get_combined_files(era, channel)
    return result


def build_presel_files_dict(channels: list[str], era: str) -> dict:
    """
    Build the files dict for use with preselected output from shapes/preselect.py.

    Sample names are expanded with their tau_gen_mode suffix so that
    ntuple_processor can locate the CROWN-compatible preselected directories:

        {presel_dir}/{era}/{sample}_{gen_mode}/{channel}/ntuple.root

    Samples with tau_gen_modes: [all] (W, data, signals) get no suffix.
    All gen-mode variants for a process are merged into one dataset key
    (e.g. "DY" contains DY_T + DY_J + DY_L samples).  The existing
    gen_match cuts in process_selection.py still select the correct subset.

    Returns the same nested structure as build_files_dict:
        {era: {channel: {dataset_key: [sample_names]}}}
    """
    from config.shapes.signal_files import signal_files

    result = {era: {}}
    for channel in channels:
        cfg = _load_tff_yaml(era, channel)
        result[era][channel] = {}

        for tff_proc, info in cfg.get("processes", {}).items():
            ds_key = _TFF_TO_DATASET.get(tff_proc)
            if ds_key is None:
                logger.debug(f"Skipping unknown TFF process '{tff_proc}'")
                continue
            gen_names: list[str] = []
            # TFF merges all samples per process into one output file named
            # after the process (e.g. "DYjets_J.root"), so we use the TFF
            # process name — not the individual CROWN sample names — so that
            # ntuple_processor finds the symlinked CROWN-compatible directories
            # created by shapes/preselect.py.
            for mode in info.get("tau_gen_modes", ["all"]):
                suffix = "" if mode == "all" else f"_{mode}"
                gen_names.append(f"{tff_proc}{suffix}")

            if ds_key not in result[era][channel]:
                result[era][channel][ds_key] = []
            result[era][channel][ds_key].extend(gen_names)

        # Signals — no gen_mode splitting
        for sig_key, sig_samples in signal_files.get(era, {}).items():
            result[era][channel][sig_key] = list(sig_samples)

        logger.debug(
            f"[presel/{era}/{channel}] dataset sizes: "
            f"{ {k: len(v) for k, v in result[era][channel].items()} }"
        )

    return result
