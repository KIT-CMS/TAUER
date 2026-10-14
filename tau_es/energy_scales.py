"""
Canonical tauES shift-point convention -- single source of truth for
shapes/produce_shapes.py and
shapes/do_estimations.py, which each to keep their own
independent (and, in one case, wrong-range) hardcoded copy.

Real convention, confirmed by direct inspection of a real 2018
TauEmbedding-MuTauFinalState validation ntuple's pt_2__EMBtauESshift_<x> friend branches:

    -12.0% to +8.0% in 0.2% steps, 100 points, 0.0% (nominal) excluded

Naming convention (shared across all consumers): a shift value x (e.g. -12.0, 4.0) is
encoded as a process-name suffix via
``str(round(x, 2)).replace("-", "minus").replace(".", "p")``, prefixed with "emb" --
e.g. -12.0 -> "embminus12p0", 4.0 -> "emb4p0".
"""
from __future__ import annotations

SHIFT_MIN = -12.0
SHIFT_MAX = 8.0
SHIFT_STEP = 0.2


def shift_values() -> list[float]:
    """The 100 real tauES shift points (percent), 0.0 (nominal) excluded."""
    n_steps = round((SHIFT_MAX - SHIFT_MIN) / SHIFT_STEP)
    values = [round(SHIFT_MIN + SHIFT_STEP * i, 1) for i in range(n_steps + 1)]
    return [v for v in values if v != 0.0]


def shift_to_procname(shift: float) -> str:
    """e.g. -12.0 -> 'embminus12p0', 4.0 -> 'emb4p0' (matches
    shapes/produce_shapes.py / shapes/do_estimations.py's existing
    per-shift embedded dataset naming)."""
    name = str(round(shift, 2)).replace("-", "minus").replace(".", "p")
    return f"emb{name}"


def procname_to_shift_string(procname: str) -> str:
    """Inverse of shift_to_procname, returning the shift as the decimal
    string CombineHarvester's ``$MASS``/morphing-point token expects
    (e.g. 'embminus12p0' -> '-12.0', 'emb4p0' -> '4.0'). Raises ValueError
    on an unrecognized name rather than silently returning something wrong."""
    if not procname.startswith("emb"):
        raise ValueError(f"Not a tauES shift process name: {procname!r}")
    body = procname[len("emb"):]
    sign = "-" if body.startswith("minus") else ""
    if sign:
        body = body[len("minus"):]
    if "p" not in body:
        raise ValueError(f"Not a tauES shift process name: {procname!r}")
    whole, frac = body.split("p", 1)
    return f"{sign}{whole}.{frac}"


def build_tau_es_map() -> dict[str, str]:
    """{'embminus12p0': '-12.0', ..., 'emb8p0': '8.0'} -- the full 100-entry
    map, generated from the canonical shift list rather than hand-copied."""
    return {shift_to_procname(v): procname_to_shift_string(shift_to_procname(v)) for v in shift_values()}


SHIFT_VALUES = shift_values()
PROCNAMES = [shift_to_procname(v) for v in SHIFT_VALUES]
