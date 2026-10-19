#!/bin/bash
# Set up the `tauer` conda env + PYTHONPATH for running shapes/*.py,
# etc. directly (run.py's SHAPES/... modes do this for you via
# utils/environment.py's pythonpath_with_tff() -- this mirrors that for
# by-hand invocation, e.g.:
#   source utils/setup_tauer.sh
#   python3 shapes/special/calculate_ttbar_dy_weights.py --ntupletag ... --eras ...

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "${REPO_ROOT}/../MiniForge/etc/profile.d/conda.sh"
conda activate tauer

export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/fake_factors:${PYTHONPATH:-}"
