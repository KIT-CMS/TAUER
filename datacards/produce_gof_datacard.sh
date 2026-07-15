#!/bin/bash
# Produce a goodness-of-fit (GoF) datacard from a synced shape file.
#
# Usage: ./datacards/produce_gof_datacard.sh ERA CHANNEL VARIABLE [NTUPLE_TAG] [USE_ASIMOV] [EMBEDDING] [JETFAKES]
#
# Calls the relocated combine_datacards/make_datacards.py --categories gof
# (see STATUS.md "## Phase 2d"/"## Phase 3"). Expects a *synced* shape ROOT file
# (produced by shapes/convert_to_synced_shapes.py --gof) placed at
#   ${FITDIR}/output/shapes/${ERA}-${CHANNEL}-${NTUPLE_TAG}-${VARIABLE}.root
# containing a TDirectory named "${CHANNEL}_${VARIABLE}" (e.g. "mt_m_vis").
# datacards/run_gof.sh does that placement for you; run this directly only if
# you already have such a synced file.
#
# IMPORTANT (Phase 4 fix): --gof-category-name must equal "${CHANNEL}_${VARIABLE}",
# which is the TDirectory name convert_to_synced_shapes.py --gof writes and the
# name make_datacards' ExtractShapes("$BIN/$PROCESS") looks up.  The previous
# scaffolding passed a bare "gof" here, which never matched a real synced file
# (it was only ever exercised against a hand-built synthetic file in Phase 2d).
#
# The GoF background model is the MC-only closure validated in Phase 3
# (embedding=False, jetfakes=False -> the 12-process ZTT/ZL/ZJ/TTT/TTL/TTJ/
# VVT/VVL/VVJ/W + ggH/qqH card whose yields came out bit-identical to legacy
# SMRun2Legacy).  Pass EMBEDDING/JETFAKES=1 to switch models once embedding/FF
# shape files are produced.

set -e
source utils/setup_cmssw.sh

[[ ! -z $1 && ! -z $2 && ! -z $3 ]] || { echo "Usage: $0 ERA CHANNEL VARIABLE [NTUPLE_TAG] [USE_ASIMOV] [EMBEDDING] [JETFAKES]"; exit 1; }

ERA=$1
CHANNEL=$2
VARIABLE=$3
NTUPLE_TAG=${4:-${NTUPLE_TAG:-htt_260602_2024-25_v5}}
USE_ASIMOV=${5:-0}
EMBEDDING=${6:-0}
JETFAKES=${7:-0}

# USE_ASIMOV=1 -> replace observation with the Asimov (b-only) expectation.
# USE_ASIMOV=0 (default) -> use the real recorded data_obs (needed for a real
#   data-vs-model GoF p-value).
if [[ "$USE_ASIMOV" == "1" ]]; then
    REAL_DATA=false
else
    REAL_DATA=true
fi
EMB=$([[ "$EMBEDDING" == "1" ]] && echo true || echo false)
FF=$([[ "$JETFAKES" == "1" ]] && echo true || echo false)

GOF_CATEGORY_NAME="${CHANNEL}_${VARIABLE}"
SHAPES_DIR="${FITDIR}/output/shapes"
OUTPUT_FOLDER="${FITDIR}/output/datacards/${ERA}-${CHANNEL}-${VARIABLE}-gof"

export PYTHONPATH="$(pwd):$(pwd)/TauFakeFactors:${PYTHONPATH}"

echo "[GoF datacard] era=$ERA channel=$CHANNEL variable=$VARIABLE real_data=$REAL_DATA embedding=$EMB jetfakes=$FF"
echo "[GoF datacard] input=${SHAPES_DIR}/${ERA}-${CHANNEL}-${NTUPLE_TAG}-${VARIABLE}.root  category=${GOF_CATEGORY_NAME}"

python3 combine_datacards/make_datacards.py \
    --era="${ERA}" \
    --channels="${CHANNEL}" \
    --categories=gof \
    --gof-category-name="${GOF_CATEGORY_NAME}" \
    --stxs-signals=stxs_stage0 \
    --input-folder="${SHAPES_DIR}" \
    --ntuple-tag="${NTUPLE_TAG}" \
    --tag="${VARIABLE}" \
    --real-data="${REAL_DATA}" \
    --embedding="${EMB}" \
    --jetfakes="${FF}" \
    --output-folder="${OUTPUT_FOLDER}"
