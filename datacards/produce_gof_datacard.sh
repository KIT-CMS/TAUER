#!/bin/bash
# Produce goodness-of-fit datacard from shapes.
#
# Usage: ./datacards/produce_gof_datacard.sh ERA CHANNEL VARIABLE [TAG] [USE_MC] [NTUPLE_TAG]
#
# Rewired in Phase 2d (see STATUS.md "## Phase 2d") to call the relocated
# combine_datacards/make_datacards.py --categories gof instead of the
# previously-referenced "MorphingCatVariables" binary, which never existed
# anywhere in SMRun2Legacy's history. Expects a shape ROOT file produced by
# shapes/produce_shapes.py --gof-inputs at
#   ${FITDIR}/output/shapes/${ERA}-${CHANNEL}-${NTUPLE_TAG}-${TAG}.root
# (i.e. run shapes/produce_shapes.py with --output-file pointed at that exact
# path first). VARIABLE currently isn't used to select a sub-file -- GoF shape
# files, as produced by shapes/produce_shapes.py --gof-inputs today, are not
# yet split one-file-per-variable; see STATUS.md "## Phase 2d" for the
# validation this was checked against.

set -e
source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 ]] || { echo "Usage: $0 ERA CHANNEL VARIABLE [TAG] [USE_MC] [NTUPLE_TAG]"; exit 1; }

ERA=$1
CHANNEL=$2
VARIABLE=$3
TAG=${4:-"gof"}
USE_MC=${5:-0}
NTUPLE_TAG=${6:-${NTUPLE_TAG:-htt_260602_2024-25_v5}}

# USE_MC=1 -> use the Asimov (background+signal) expectation as the "observation"
# USE_MC=0 (default) -> use real recorded data_obs
if [[ "$USE_MC" == "1" ]]; then
    REAL_DATA=false
else
    REAL_DATA=true
fi

SHAPES_DIR="${FITDIR}/output/shapes"
# make_datacards.py appends /{channel}/{era}/*.txt to whatever --output-folder
# it's given (see combine_datacards/make_datacards.py) -- pass the base dir
# here and have produce_gof_workspace.sh descend into the same leaf.
OUTPUT_FOLDER="${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof"

export PYTHONPATH="$(pwd):${PYTHONPATH}"

python3 combine_datacards/make_datacards.py \
    --era="${ERA}" \
    --channels="${CHANNEL}" \
    --categories=gof \
    --gof-category-name="${TAG}" \
    --input-folder="${SHAPES_DIR}" \
    --ntuple-tag="${NTUPLE_TAG}" \
    --tag="${TAG}" \
    --real-data="${REAL_DATA}" \
    --output-folder="${OUTPUT_FOLDER}"
