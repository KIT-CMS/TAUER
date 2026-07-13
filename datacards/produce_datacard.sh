#!/bin/bash
# Produce SM H→ττ datacards from shapes output
# Usage: ./datacards/produce_datacard.sh ERA CHANNEL ANALYSIS [CORES]

set -e
source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 ]] || { echo "Usage: $0 ERA CHANNEL ANALYSIS [CORES]"; exit 1; }

ERA=$1
CHANNEL=$2
ANALYSIS=$3
CORES=${4:-1}

echo "Producing datacard: era=$ERA channel=$CHANNEL analysis=$ANALYSIS cores=$CORES"

SHAPES_DIR="${FITDIR}/output/shapes/${ERA}-${CHANNEL}-${ANALYSIS}"
OUTPUT_FOLDER="${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${ANALYSIS}"

MorphingCatVariables \
    --base-path="${SHAPES_DIR}" \
    --output_folder="${OUTPUT_FOLDER}" \
    --variable=m_sv_puppi \
    --era="${ERA}" \
    --channel="${CHANNEL}" \
    --verbose=1
