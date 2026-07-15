"""
Canonical tauES shift-point convention -- single source of truth.

Phase 2a (see STATUS.md) established, by direct inspection of a real 2018
``TauEmbedding-MuTauFinalState`` validation ntuple's ``pt_2__EMBtauESshift_<x>``
friend branches, that the real shift-point convention is:

    -12.0% to +8.0% in 0.2% steps, 100 points, 0.0% (nominal) excluded

and fixed two call sites to use it (``shapes/produce_shapes.py``'s
``_es_shifts``, ``shapes/do_estimations.py``'s ``tauESvariations``) -- but
left the corrected list as two independent, near-identical inline list
comprehensions rather than a shared definition. This module is that shared
definition, added as part of Phase 6b's tau_es extraction.

**Real bug found and fixed while wiring this up (Phase 6b):**
``shapes/convert_to_synced_shapes.py`` -- the flat-histogram -> synced-file
bridge that sits *between* shape production and datacard construction, and
is a required step for the tauES measurement chain this package
(``tau_es/``) builds datacards from -- still had its own, third, independent
hardcoded ``tau_es_map`` dict spanning only **-4.0% to +4.0% in 0.1% steps**
(81 entries), i.e. the range/step Phase 2a explicitly found and corrected
*elsewhere*, left unfixed here. Since ``shapes/produce_shapes.py`` only ever
produces shift points on the corrected -12.0/+8.0/0.2 grid, essentially all
of the 0.1-step entries in the old ``tau_es_map`` never correspond to a real
produced histogram, and every shift point outside +-4.0% (which is most of
the 100-point grid, including the two most extreme points the measurement
needs for a wide taues lever arm) has no entry at all -- a
``KeyError`` in ``convert_to_synced_shapes.py`` the first time any of those
shift points is actually processed with ``--special TauES``. Fixed by
generating that map from this module's canonical list instead of a fourth
independent hardcoded copy (see ``shapes/convert_to_synced_shapes.py``'s
``tau_es_map = _build_tau_es_map()`` call).

Naming convention (shared across all three consumers): a shift value
``x`` (e.g. ``-12.0``, ``4.0``) is encoded as a process-name suffix via
``str(round(x, 2)).replace("-", "minus").replace(".", "p")``, then prefixed
with ``"emb"`` -> e.g. ``-12.0`` -> ``"embminus12p0"``, ``4.0`` -> ``"emb4p0"``.
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
