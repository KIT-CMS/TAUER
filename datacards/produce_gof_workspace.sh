#!/bin/bash
# Produce a goodness-of-fit / impacts workspace for Combine.
# Usage: ./datacards/produce_gof_workspace.sh ERA CHANNEL VARIABLE [CORES]
#
# Builds ws.root next to the GoF datacard produced by produce_gof_datacard.sh,
# i.e. at ${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/${CHANNEL}/${ERA}/ws.root.
#
# Phase 4 change: uses Combine's *default* physics model (a single signal
# strength `r` scaling all Higgs processes) rather than the multiSignalModel
# (r_ggH/r_qqH) the pre-Phase-4 scaffolding used.  A single POI is what both the
# GoF test (`--fixedSignalStrength=0` == r=0, background-only) and single-POI
# Impacts (`combineTool.py -M Impacts`) expect; a multiSignalModel workspace
# breaks `--fixedSignalStrength` and needs an explicit --redefineSignalPOIs for
# Impacts.  For a one-bin `gof` category there is no ggH/qqH separation to gain
# from two POIs anyway.

set -e
ulimit -s unlimited

source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 ]] || { echo "Usage: $0 ERA CHANNEL VARIABLE [CORES]"; exit 1; }

ERA=$1
CHANNEL=$2
VARIABLE=$3
CORES=${4:-1}

# make_datacards.py writes {output-folder}/{channel}/{era}/{bin}.txt
INPUT_DIR="${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/${CHANNEL}/${ERA}"

CARD=$(ls "${INPUT_DIR}"/htt_*.txt 2>/dev/null | head -n1)
[[ -n "$CARD" ]] || { echo "ERROR: no datacard htt_*.txt found in ${INPUT_DIR}. Run produce_gof_datacard.sh first."; exit 1; }

echo "[GoF workspace] building default single-r workspace from ${CARD}"
text2workspace.py "${CARD}" -m 125 -o "${INPUT_DIR}/ws.root"
echo "[GoF workspace] wrote ${INPUT_DIR}/ws.root"
