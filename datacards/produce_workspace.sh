#!/bin/bash
# Produce SM H→ττ workspace (RooWorkspace) for Combine
# Usage: ./datacards/produce_workspace.sh ERA ANALYSIS [CORES]

set -e
ulimit -s unlimited

IFS="," read -a ERA_ARR <<< $1
ANALYSIS=$2
CORES=${3:-1}

echo "Use $CORES cores."
source utils/setup_cmssw.sh

pushd "$FITDIR"

# combine_datacards/make_datacards.py (Phase 2d) writes
# output_${ANALYSIS}/{channel}/{era}/*.txt (channel outer, era inner) --
# see datacards/produce_datacard.sh.
INPUT_DIRS="output_${ANALYSIS}/{et,mt,tt,em,cmb}/{$(IFS="," ; echo ${ERA_ARR[*]})}"

combineTool.py -M T2W -o "ws.root" \
    -P HiggsAnalysis.CombinedLimit.PhysicsModel:multiSignalModel \
    --PO '"map=^.*/ggH125$:r_ggH[1,0,5]"' \
    --PO '"map=^.*/qqH125$:r_qqH[1,0,5]"' \
    -i $INPUT_DIRS \
    -m 125 \
    --parallel "$CORES"

popd
