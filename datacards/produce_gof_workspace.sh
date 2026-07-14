#!/bin/bash
# Produce goodness-of-fit workspace for Combine
# Usage: ./datacards/produce_gof_workspace.sh ERA CHANNEL VARIABLE [TAG] [CORES]

set -e
ulimit -s unlimited

source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 ]] || { echo "Usage: $0 ERA CHANNEL VARIABLE [TAG] [CORES]"; exit 1; }

ERA=$1
CHANNEL=$2
VARIABLE=$3
TAG=${4:-"gof"}
CORES=${5:-1}

pushd "$FITDIR"

# make_datacards.py (invoked by produce_gof_datacard.sh) writes into
# {output-folder}/{channel}/{era}/*.txt -- descend into that same leaf here.
INPUT_DIR="output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/${CHANNEL}/${ERA}/"

combineTool.py -M T2W -o "ws.root" \
    -P HiggsAnalysis.CombinedLimit.PhysicsModel:multiSignalModel \
    --PO '"map=^.*/ggH125$:r_ggH[1,0,5]"' \
    --PO '"map=^.*/qqH125$:r_qqH[1,0,5]"' \
    -i "${INPUT_DIR}" \
    -m 125 \
    --parallel "$CORES"

popd
