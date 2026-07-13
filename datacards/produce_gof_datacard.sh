#!/bin/bash
# Produce goodness-of-fit datacard from shapes
# Usage: ./datacards/produce_gof_datacard.sh ERA CHANNEL VARIABLE [TAG] [USE_MC]

set -e
source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 ]] || { echo "Usage: $0 ERA CHANNEL VARIABLE [TAG] [USE_MC]"; exit 1; }

ERA=$1
CHANNEL=$2
VARIABLE=$3
TAG=${4:-"gof"}
USE_MC=${5:-0}

MorphingCatVariables \
    --base-path="output/shapes/${ERA}-${CHANNEL}-${TAG}-synced_shapes/" \
    --category="${CHANNEL}_${VARIABLE}" \
    --variable="${VARIABLE}" \
    --verbose=1 \
    --output_folder="output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof/" \
    --use_mc="${USE_MC}" \
    --era="${ERA}"
