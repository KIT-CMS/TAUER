"""
TauFakeFactors preselection-YAML reader for channel_selection.py.

Phase 5.2 cleanup note (see STATUS.md): this module used to claim, in its own
docstring, to be a pure "backward-compatibility shim ... all functionality has
moved to config/analysis.py" — but it actually *redefined* every one of
``get_background_sample_names`` / ``get_tff_event_selection`` /
``get_tff_mc_weights`` / ``get_combined_files`` / ``build_files_dict`` /
``build_presel_files_dict`` locally, below the aliased imports of the same
names from ``config.analysis``, so the local defs silently shadowed the
imports. A repo-wide grep confirmed only ``get_tff_event_selection`` is
actually imported from this module anywhere (``shapes/selection/channel_selection.py``);
the other five shadowed re-implementations were dead code (and would have
raised ``NameError`` on ``logger`` if ever called — this module never imported
`logger` — further confirming they were never exercised). Removed here; use
``config.analysis.get_background_samples`` / ``get_mc_weights`` /
``get_samples`` / ``build_files_dict`` / ``build_presel_files_dict`` directly
for those.

What's left, ``get_tff_event_selection``, is *not* a re-export of
``config.analysis.get_preselection_cuts`` — that would be the wrong single
source for this particular call site. It deliberately reads the *actual*
TauFakeFactors ``preselection_{channel}.yaml`` submodule file directly, not
``config/cuts.yaml``. Rationale: ``config/cuts.yaml`` is regenerated into
TFF's preselection YAMLs by ``config/generate_tff_configs.py`` (a
build/sync step, not automatic), so the two can transiently disagree between
a ``cuts.yaml`` edit and the next regeneration run. Reading the TFF YAML here
guarantees ``channel_selection()``'s tau-ID/vsMu/trigger cuts always match
whatever TauFakeFactors will actually use for the fake-factor measurement
selection (the whole point of routing shape production's non-orthogonal cuts
through this adapter in the first place), rather than momentarily reading a
value ``cuts.yaml`` may have already moved past. This is intentional, not a
missed reconciliation -- config/cuts.yaml stays the one editable source of
truth for these cut *values*; this function just reads their already-generated
downstream copy for this one call site, on purpose.
"""

import yaml
from config.analysis import SUPPORTED_ERAS, TFF_CONFIG_ROOT, TFF_ROOT

__all__ = ["get_tff_event_selection"]


def _load_tff_yaml(era: str, channel: str) -> dict:
    """Load TauFakeFactors preselection YAML for the given era and channel."""
    if era not in SUPPORTED_ERAS:
        raise ValueError(f"Era '{era}' is not a supported era. Supported: {SUPPORTED_ERAS}")
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


def get_tff_event_selection(era: str, channel: str) -> dict[str, str]:
    """
    Return the event_selection dict from the TFF preselection YAML.
    Keys are cut names, values are cut string expressions.

    See module docstring for why this reads the TFF YAML directly instead of
    delegating to config.analysis.get_preselection_cuts().
    """
    cfg = _load_tff_yaml(era, channel)
    return dict(cfg.get("event_selection", {}))
