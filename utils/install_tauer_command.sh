#!/bin/bash
# One-time: run with the tauer conda env active, makes `tauer` available there.
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -n "${CONDA_PREFIX:-}" ] || { echo "Activate the tauer conda env first: conda activate tauer" >&2; exit 1; }
chmod +x "${REPO_ROOT}/workflow/tauer"
ln -sfn "${REPO_ROOT}/workflow/tauer" "${CONDA_PREFIX}/bin/tauer"
echo "Installed ${CONDA_PREFIX}/bin/tauer -> ${REPO_ROOT}/workflow/tauer"
