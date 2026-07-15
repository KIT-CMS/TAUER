#!/bin/bash
# Phase 4: run a real Combine Impacts (nuisance-ranking) workflow end-to-end.
#
# Usage:
#   ./datacards/run_impacts.sh ERA CHANNEL VARIABLE [PARALLEL] [NTUPLE_TAG]
#
# Expects the datacard/workspace to already exist at
#   ${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/${CHANNEL}/${ERA}/ws.root
# (i.e. run datacards/run_gof.sh -- or at minimum
# produce_gof_datacard.sh + produce_gof_workspace.sh -- first; this script
# does not rebuild the workspace, only reuses it, since Impacts and GoF are
# almost always run back-to-back against the same card).
#
# Standard combineTool.py -M Impacts pipeline (adapted from
# smhtt_ul/fitting/impacts.sh, house-ruled to TauKITFlow's default single-r
# workspace -- no --redefineSignalPOIs needed since there's exactly one POI):
#   1. --doInitialFit   (best-fit r + its uncertainty)
#   2. --doFits         (one fit per nuisance parameter, --parallel-wide)
#   3. -o impacts.json  (collect)
#   4. plotImpacts.py   (ranked tornado plot)

set -e
ulimit -s unlimited
source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 ]] || { echo "Usage: $0 ERA CHANNEL VARIABLE [PARALLEL] [NTUPLE_TAG]"; exit 1; }

ERA=$1
CHANNEL=$2
VARIABLE=$3
PARALLEL=${4:-10}
MASS=125
ID="${ERA}_${CHANNEL}_${VARIABLE}"

WORKSPACE="${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/${CHANNEL}/${ERA}/ws.root"
[[ -f "$WORKSPACE" ]] || { echo "ERROR: workspace not found: $WORKSPACE. Run produce_gof_datacard.sh + produce_gof_workspace.sh (or run_gof.sh) first."; exit 1; }

IMPACTS_DIR="${FITDIR}/output/impacts/${ID}"
mkdir -p "${IMPACTS_DIR}"
pushd "${IMPACTS_DIR}" >/dev/null

echo "[run_impacts] === step 1/4: doInitialFit ==="
time combineTool.py -M Impacts -d "${WORKSPACE}" -m ${MASS} \
    --X-rtd MINIMIZER_analytic --cminDefaultMinimizerStrategy 0 \
    --doInitialFit --robustFit 1 \
    --parallel "${PARALLEL}"

echo "[run_impacts] === step 2/4: doFits (per-nuisance) ==="
time combineTool.py -M Impacts -d "${WORKSPACE}" -m ${MASS} \
    --X-rtd MINIMIZER_analytic --cminDefaultMinimizerStrategy 0 \
    --robustFit 1 --doFits \
    --parallel "${PARALLEL}"

echo "[run_impacts] === step 3/4: collect -> impacts.json ==="
combineTool.py -M Impacts -d "${WORKSPACE}" -m ${MASS} -o "impacts_${ID}.json"

echo "[run_impacts] === step 4/4: plotImpacts ==="
plotImpacts.py -i "impacts_${ID}.json" -o "impacts_${ID}"

echo "[run_impacts] === summary: top-ranked nuisances ==="
python3 - "impacts_${ID}.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
poi = d["POIs"][0]["name"]
rows = []
for p in d["params"]:
    imp = p.get("impact_" + poi, p.get("impact"))
    rows.append((abs(imp), imp, p["name"]))
rows.sort(reverse=True)
print(f"POI: {poi}")
print(f"{'rank':<5}{'impact':>10}   nuisance")
for i, (absimp, imp, name) in enumerate(rows[:15], 1):
    print(f"{i:<5}{imp:>10.4f}   {name}")
print(f"... {len(rows)} nuisances total")
PY

popd >/dev/null
echo "[run_impacts] done. Outputs under ${IMPACTS_DIR}"
