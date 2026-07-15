"""
Fetch config.analysis.get_output_features() under the CVMFS LCG Python view
(utils/setup_root.sh).

Phase 6d note (STATUS.md "## Phase 6d"): run.sh's bash version sourced
utils/setup_root.sh unconditionally, up front, for every mode, purely to run
`nice -n 19 python -c "from config.analysis import get_output_features; ..."`
under the LCG view's Python (which has pyyaml available) rather than the
`taukiktflow` conda env's -- the *only* consumer of the result,
OUTPUT_FEATURES, is PRESEL mode's `--columns` flag. This module makes that
lazy (only called by run.py's PRESEL mode) instead of unconditional, which
changes nothing observable about any mode's output but avoids paying the LCG
env-sourcing cost for modes that never use it (XSEC, SHAPES, PLOT, ...).
`utils/setup_root.sh` itself is left as bash (real CVMFS `source
.../setup.sh` environment mutation -- the same class of exception as
`utils/setup_cmssw.sh`); this module is the one place that shells out to it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_ROOT = REPO_ROOT / "utils" / "setup_root.sh"


def get_output_features() -> List[str]:
    cmd = (
        f"source {SETUP_ROOT} >/dev/null 2>&1 && "
        'python -c "from config.analysis import get_output_features; '
        'print(chr(10).join(get_output_features()))"'
    )
    result = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch OUTPUT_FEATURES via {SETUP_ROOT}:\n{result.stderr}")
    return [line for line in result.stdout.splitlines() if line]
