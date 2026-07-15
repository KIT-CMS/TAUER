#!/bin/bash
# Produce SM H→ττ datacards from shapes output.
#
# Usage: ./datacards/produce_datacard.sh ERA CHANNEL ANALYSIS [NTUPLE_TAG]
#
# Rewired in Phase 2d (see STATUS.md "## Phase 2d") to call the relocated
# combine_datacards/make_datacards.py instead of the previously-referenced
# "MorphingCatVariables" binary, which never existed anywhere in
# SMRun2Legacy's history (grepped across every branch) -- that was a stale
# reference from before this repo's SMRun2Legacy-derived datacard code was
# relocated/rewired. CombineHarvester/Combine/CMSSW themselves remain an
# external dependency, reached via utils/setup_cmssw.sh's `cmsenv`, exactly as
# before -- nothing from CombineHarvester is vendored here.
#
# ANALYSIS selects the categorization scheme passed as --categories to
# make_datacards.py (e.g. gof, stxs_stage0, stxs_stage0_run3, ...) -- for
# GoF datacards use produce_gof_datacard.sh instead, which wires up the
# gof-specific shape file layout directly.
#
# NOTE: --categories stxs_stage0_run3 (the Run3 DNN categorization) requires
# per-category "synced shape" ROOT files produced by a convert_to_synced_shapes.py
# -style step that does not exist in TauKITFlow yet (see STATUS.md "## Phase 2d"
# / "## Blockers") -- until that's built, this script only works end-to-end for
# non-DNN categorizations (stxs_stage0, stxs_stage1p2_run2, ...) whose shape
# files follow the flat {era}-{channel}-{ntuple_tag}-{tag}.root naming.

set -e
source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 ]] || { echo "Usage: $0 ERA CHANNEL ANALYSIS [NTUPLE_TAG]"; exit 1; }

ERA=$1
CHANNEL=$2
ANALYSIS=$3
NTUPLE_TAG=${4:-${NTUPLE_TAG:-htt_260602_2024-25_v5}}

echo "Producing datacard: era=$ERA channel=$CHANNEL analysis=$ANALYSIS ntuple_tag=$NTUPLE_TAG"

SHAPES_DIR="${FITDIR}/output/shapes"
# output_${ANALYSIS}/{channel}/{era}/*.txt -- matches make_datacards.py's own
# per-era-then-channel loop nesting (channel outer, era inner) and
# produce_workspace.sh's INPUT_DIRS glob, which expects this same layout.
OUTPUT_FOLDER="${FITDIR}/output_${ANALYSIS}"

# combine_datacards/ and config/ need to be importable -- run from the repo root
# (this script is expected to be invoked as ./datacards/produce_datacard.sh from
# the TauKITFlow repo root, same convention as before).
# TauFakeFactors must also be on PYTHONPATH: config/logging_setup_configs.py
# imports the CustomLogging package, which only lives inside the TauFakeFactors
# submodule (Phase 4 finding -- this was untested under CMSSW's own Python
# until Phase 4's real run hit it; same fix as run.sh's shape-production path).
export PYTHONPATH="$(pwd):$(pwd)/TauFakeFactors:${PYTHONPATH}"

python3 combine_datacards/make_datacards.py \
    --era="${ERA}" \
    --channels="${CHANNEL}" \
    --categories="${ANALYSIS}" \
    --input-folder="${SHAPES_DIR}" \
    --ntuple-tag="${NTUPLE_TAG}" \
    --tag="${ANALYSIS}" \
    --output-folder="${OUTPUT_FOLDER}"
