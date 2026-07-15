#!/bin/bash
# Phase 4: run a real Combine Goodness-of-Fit (GoF) test end-to-end.
#
# Usage:
#   ./datacards/run_gof.sh ERA CHANNEL VARIABLE SYNCED_FILE \
#                          [ALGO] [NTOYS] [NTUPLE_TAG] [USE_ASIMOV] [PARALLEL]
#
# Ties together the existing datacard/workspace scripts and drives the standard
# GoF workflow (adapted from smhtt_ul/gof_tests.sh's GOF mode, house-ruled to
# TauKITFlow's combine_datacards/ layout -- no MorphingSMRun2Legacy binary):
#
#   1. place SYNCED_FILE (a shapes/convert_to_synced_shapes.py --gof output,
#      containing a "${CHANNEL}_${VARIABLE}" TDirectory) where make_datacards
#      expects it;
#   2. produce_gof_datacard.sh  -> Combine datacard;
#   3. produce_gof_workspace.sh -> default single-r workspace (ws.root);
#   4. combine -M GoodnessOfFit on real data (observed test statistic);
#   5. the same, throwing NTOYS toys (PARALLEL seeds), b-only (r=0);
#   6. combineTool.py -M CollectGoodnessOfFit -> gof.json;
#   7. print the observed statistic and the toy-based p-value; plotGof.py for
#      the KS/AD algos.
#
# ALGO: saturated (default) | KS | AD.  NTOYS: total toys (default 300).
# Requires a valid grid environment only if the datacard has to be rebuilt;
# the GoF fits themselves are local (CMSSW/Combine, no xrootd).

set -e
ulimit -s unlimited
source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 && ! -z $4 ]] || {
    echo "Usage: $0 ERA CHANNEL VARIABLE SYNCED_FILE [ALGO] [NTOYS] [NTUPLE_TAG] [USE_ASIMOV] [PARALLEL]"; exit 1; }

ERA=$1
CHANNEL=$2
VARIABLE=$3
SYNCED_FILE=$4
ALGO=${5:-saturated}
NTOYS=${6:-300}
NTUPLE_TAG=${7:-htt_260602_2024-25_v5}
USE_ASIMOV=${8:-0}
PARALLEL=${9:-10}
MASS=125
ID="${ERA}_${CHANNEL}_${VARIABLE}"

[[ -f "$SYNCED_FILE" ]] || { echo "ERROR: synced shape file not found: $SYNCED_FILE"; exit 1; }

SHAPES_DIR="${FITDIR}/output/shapes"
mkdir -p "${SHAPES_DIR}"
DEST="${SHAPES_DIR}/${ERA}-${CHANNEL}-${NTUPLE_TAG}-${VARIABLE}.root"
echo "[run_gof] placing synced file: ${SYNCED_FILE} -> ${DEST}"
cp -f "${SYNCED_FILE}" "${DEST}"

# --- Build datacard + workspace ---
bash datacards/produce_gof_datacard.sh  "${ERA}" "${CHANNEL}" "${VARIABLE}" "${NTUPLE_TAG}" "${USE_ASIMOV}"
bash datacards/produce_gof_workspace.sh "${ERA}" "${CHANNEL}" "${VARIABLE}"

WORKSPACE="${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/${CHANNEL}/${ERA}/ws.root"
[[ -f "$WORKSPACE" ]] || { echo "ERROR: workspace not built: $WORKSPACE"; exit 1; }

# --- Run GoF in a dedicated working directory (combine litters cwd) ---
GOF_DIR="${FITDIR}/output/gof/${ID}"
mkdir -p "${GOF_DIR}"
pushd "${GOF_DIR}" >/dev/null

echo "[run_gof] === observed GoF (${ALGO}) on real data ==="
if [[ "$ALGO" == "saturated" ]]; then
    combine -M GoodnessOfFit -n ".${ID}" --algo=${ALGO} -m ${MASS} -d "${WORKSPACE}" --fixedSignalStrength=0 -v1
else
    combine -M GoodnessOfFit -n ".${ID}" --algo=${ALGO} -m ${MASS} -d "${WORKSPACE}" --fixedSignalStrength=0 --plots -v1
fi

echo "[run_gof] === throwing ${NTOYS} toys over ${PARALLEL} seeds ==="
TOYSOPT=""
[[ "$ALGO" == "saturated" ]] && TOYSOPT="--toysFreq"
PER=$(( (NTOYS + PARALLEL - 1) / PARALLEL ))
TOYFILES=()
for i in $(seq 0 $((PARALLEL-1))); do
    SEED=$((1230 + i))
    combine -M GoodnessOfFit -n ".${ID}" --algo=${ALGO} -m ${MASS} -d "${WORKSPACE}" \
        -s ${SEED} -t ${PER} ${TOYSOPT} --fixedSignalStrength=0 >"toys_${SEED}.log" 2>&1 &
    TOYFILES+=("higgsCombine.${ID}.GoodnessOfFit.mH${MASS}.${SEED}.root")
done
wait

echo "[run_gof] === collect ==="
OBSFILE="higgsCombine.${ID}.GoodnessOfFit.mH${MASS}.root"
combineTool.py -M CollectGoodnessOfFit \
    --input ${OBSFILE} ${TOYFILES[@]} \
    --output "${GOF_DIR}/gof_${ALGO}.json"

# --- p-value / summary ---
python3 - "$GOF_DIR/gof_${ALGO}.json" "$ALGO" <<'PY'
import json, sys
path, algo = sys.argv[1], sys.argv[2]
d = json.load(open(path))
key = list(d.keys())[0]
e = d[key]
obs = e.get("obs", e.get("observed"))
toys = e.get("toy", e.get("toys", []))
if isinstance(obs, list): obs = obs[0]
n = len(toys)
p = (sum(1 for t in toys if t >= obs) / n) if n else float("nan")
print("=" * 60)
print(f"GoF result ({algo})  mass={key}")
print(f"  observed test statistic : {obs:.4f}")
print(f"  n_toys                  : {n}")
print(f"  p-value (frac toys>=obs): {p:.4f}")
print("=" * 60)
PY

if [[ "$ALGO" != "saturated" ]]; then
    plotGof.py --statistic ${ALGO} --mass ${MASS}.0 --output "gof_${ALGO}" "${GOF_DIR}/gof_${ALGO}.json" || true
fi
popd >/dev/null
echo "[run_gof] done. Outputs under ${GOF_DIR}"
