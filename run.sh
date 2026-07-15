#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# TauHarvest — SM H→ττ analysis framework
#
# Usage:
#   source run.sh <MODE> [options]
#
# Modes:
#   XSEC          Build cross-section friend trees
#   SHAPES        Produce shapes (with systematic variations)
#   SHAPES-NOSYS  Produce nominal shapes only (fast)
#   PLOT          Plot control shapes
#   TRAIN-SHAPES  Produce shapes for NN training
#   CONFIGS       Collect ntuple_processor configs (YAML) — no histogram production
#   FF-MEASURE    Run the full TauFakeFactors FF measurement (GEN-TFF-CONFIGS+PRESEL+FF+FF-CORR)
#
# ─────────────────────────────────────────────────────────────────────────────
set -e

# ── Argument parsing ──────────────────────────────────────────────────────────
# Supports both positional (run.sh XSEC) and flag-based (run.sh --mode XSEC ...) invocation.
if [[ "${1:-}" != --* && -n "${1:-}" ]]; then
    MODE=$1; shift
fi
_EXTRA=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)            MODE="$2";           shift 2 ;;
        --era)             ERA="$2";            shift 2 ;;
        --channel|--channels) CHANNELS="$2";   shift 2 ;;
        --ntupletag)       NTUPLETAG="$2";      shift 2 ;;
        --tag)             TAG="$2";            shift 2 ;;
        --vs-jet-wp)       VS_JET_WP="$2";      shift 2 ;;
        --vs-ele-wp)       VS_ELE_WP="$2";      shift 2 ;;
        --nthreads)        NTHREADS="$2";       shift 2 ;;
        --nprocs)          NPROCS="$2";         shift 2 ;;
        --output-dir)      OUTPUT_DIR="$2";     shift 2 ;;
        --ff-friends-dir)  FF_FRIENDS_DIR="$2"; shift 2 ;;
        --ff-config)       FF_CONFIG="$2";      shift 2 ;;
        --ff-corr-config)  FF_CORR_CONFIG="$2"; shift 2 ;;
        --presel-dir)      PRESEL_DIR="$2";    shift 2 ;;
        *)                 _EXTRA+=("$1");      shift ;;
    esac
done
set -- "${_EXTRA[@]}"

export PYTHONPATH="${PYTHONPATH}:${PWD}:${PWD}/TauFakeFactors"

# ── Run3 defaults ─────────────────────────────────────────────────────────────
ERA=${ERA:-"2022postEE"}
CHANNELS=${CHANNELS:-"et,mt,tt"}
VS_JET_WP=${VS_JET_WP:-"Medium"}
if [[ "$CHANNELS" == "et" ]]; then
    VS_ELE_WP=${VS_ELE_WP:-"Tight"}
else
    VS_ELE_WP=${VS_ELE_WP:-"VVLoose"}
fi
NTUPLETAG=${NTUPLETAG:-""}
TAG=${TAG:-""}
OUTPUT_DIR=${OUTPUT_DIR:-"output"}
NTHREADS=${NTHREADS:-4}
NPROCS=${NPROCS:-1}
PRESEL_DIR=${PRESEL_DIR:-""}

# ── Helper ────────────────────────────────────────────────────────────────────
check_env () {
    conda activate taukiktflow           
    
    if [[ -z "$NTUPLETAG" ]]; then
        echo "ERROR: NTUPLETAG must be set (CROWN ntuple tag, e.g. htt_260417_2022-23)."
        exit 1
    fi
}

source utils/setup_root.sh

# Column list for TFF preselection output — loaded after setup_root.sh so LCG Python (with pyyaml) is available.
mapfile -t OUTPUT_FEATURES < <(nice -n 19 python -c "from config.analysis import get_output_features; print('\n'.join(get_output_features()))")

# ── Modes ─────────────────────────────────────────────────────────────────────
case "$MODE" in

XSEC)
    check_env
    source utils/setup_ul_samples.sh "$NTUPLETAG" "$ERA"
    echo "[XSEC] Building cross-section friend trees for $NTUPLETAG"
    # Select datasets.json based on era (v12 for 2022/23, v15 for 2024/25)
    if [[ "$ERA" == 2024* || "$ERA" == 2025* ]]; then
        DATASETS_JSON="TauFakeFactors/datasets/nanoAOD_v15/datasets.json"
    else
        DATASETS_JSON="TauFakeFactors/datasets/nanoAOD_v12/datasets.json"
    fi
    nice -n 19 python friends/build_friend_tree.py \
        --basepath "$KINGMAKER_BASEDIR_XROOTD" \
        --outputpath "root://cmsdcache-kit-disk.gridka.de/${XSEC_FRIENDS}" \
        --dataset-config "$DATASETS_JSON" \
        --nthreads "$NTHREADS" \
        "$@"
    ;;

SHAPES|SHAPES-NOSYS)
    check_env
    source utils/setup_ul_samples.sh "$NTUPLETAG" "$ERA"

    OUTFILE="${OUTPUT_DIR}/${ERA}-${CHANNELS/,/-}-shapes.root"
    mkdir -p "$OUTPUT_DIR"

    EXTRA_ARGS=""
    FF_FRIENDS=""
    if [[ -n "$FF_FRIENDS_DIR" ]]; then
        FF_FRIENDS="--et-friend-directory $FF_FRIENDS_DIR --mt-friend-directory $FF_FRIENDS_DIR --tt-friend-directory $FF_FRIENDS_DIR"
        EXTRA_ARGS="--ff-type fake_factor"
    fi

    if [[ -n "$PRESEL_DIR" ]]; then
        EXTRA_ARGS="$EXTRA_ARGS --presel-dir $PRESEL_DIR"
    fi

    if [[ "$MODE" == "SHAPES-NOSYS" ]]; then
        EXTRA_ARGS="$EXTRA_ARGS --skip-systematic-variations"
    fi

    if [[ -z "$DNN_FRIENDS_DIR" ]]; then
        EXTRA_ARGS="$EXTRA_ARGS --no-dnn-categorization"
    fi

    echo "[${MODE}] Producing shapes: era=$ERA channels=$CHANNELS"
    nice -n 19 python shapes/produce_shapes.py \
        --era "$ERA" \
        --channels "$CHANNELS" \
        --vs-jet-wp "$VS_JET_WP" \
        --vs-ele-wp "$VS_ELE_WP" \
        --directory "$NTUPLES" \
        --et-friend-directory "$XSEC_FRIENDS" \
        --mt-friend-directory "$XSEC_FRIENDS" \
        --tt-friend-directory "$XSEC_FRIENDS" \
        --em-friend-directory "$XSEC_FRIENDS" \
        $FF_FRIENDS \
        --output-file "$OUTFILE" \
        --num-processes "$NPROCS" \
        --num-threads "$NTHREADS" \
        --xrootd \
        $EXTRA_ARGS \
        "$@"

    echo "[${MODE}] Running post-processing estimations on $OUTFILE"
    ESTIMATION_ARGS=""
    if [[ -n "$FF_FRIENDS_DIR" ]]; then
        ESTIMATION_ARGS="--do-ff"
    fi
    nice -n 19 python shapes/do_estimations.py \
        --era "$ERA" \
        --input "$OUTFILE" \
        $ESTIMATION_ARGS \
        "$@"
    ;;

PLOT)
    OUTFILE="${OUTPUT_DIR}/${ERA}-${CHANNELS/,/-}-shapes.root"
    PLOT_DIR="/web/sgiappic/public_html/CMS_HTT/${ERA}/test/"
    VARIABLES=${VARIABLES:-"m_vis,pt_1,pt_2,eta_1,eta_2,mt_1"}

    echo "[PLOT] Plotting shapes from $OUTFILE"
    nice -n 19 python plotting/plot_shapes_control.py \
        --input "$OUTFILE" \
        --output "$PLOT_DIR" \
        --era "$ERA" \
        --channels "$CHANNELS" \
        --variables "$VARIABLES" \
        "$@"
    ;;

TRAIN-SHAPES)
    check_env
    source utils/setup_ul_samples.sh "$NTUPLETAG" "$ERA"

    OUTFILE="${OUTPUT_DIR}/${ERA}-${CHANNELS/,/-}-training-shapes.root"
    mkdir -p "$OUTPUT_DIR"

    echo "[TRAIN-SHAPES] Producing training shapes: era=$ERA channels=$CHANNELS"
    nice -n 19 python shapes/produce_shapes.py \
        --era "$ERA" \
        --channels "$CHANNELS" \
        --vs-jet-wp "$VS_JET_WP" \
        --vs-ele-wp "$VS_ELE_WP" \
        --directory "$NTUPLES" \
        --et-friend-directory "$XSEC_FRIENDS" \
        --mt-friend-directory "$XSEC_FRIENDS" \
        --tt-friend-directory "$XSEC_FRIENDS" \
        --em-friend-directory "$XSEC_FRIENDS" \
        --output-file "$OUTFILE" \
        --num-processes "$NPROCS" \
        --num-threads "$NTHREADS" \
        --xrootd \
        --skip-systematic-variations \
        "$@"
    ;;

CONFIGS)
    check_env
    source utils/setup_ul_samples.sh "$NTUPLETAG" "$ERA"

    OUTFILE="${OUTPUT_DIR}/${ERA}-${CHANNELS/,/-}-config.yaml"
    mkdir -p "$OUTPUT_DIR"

    echo "[CONFIGS] Collecting ntuple_processor configs: era=$ERA channels=$CHANNELS"
    nice -n 19 python shapes/produce_shapes.py \
        --era "$ERA" \
        --channels "$CHANNELS" \
        --vs-jet-wp "$VS_JET_WP" \
        --vs-ele-wp "$VS_ELE_WP" \
        --directory "$NTUPLES" \
        --et-friend-directory "$XSEC_FRIENDS" \
        --mt-friend-directory "$XSEC_FRIENDS" \
        --tt-friend-directory "$XSEC_FRIENDS" \
        --em-friend-directory "$XSEC_FRIENDS" \
        --output-file "${OUTFILE%.yaml}.root" \
        --collect-config-only \
        --xrootd \
        --config-output-file "$OUTFILE" \
        "$@"
    ;;

GEN-TFF-CONFIGS)
    echo "[GEN-TFF-CONFIGS] Regenerating TFF per-channel preselection YAMLs from unified config"
    echo "[GEN-TFF-CONFIGS] era=$ERA channels=$CHANNELS"
    export PYTHONPATH="${PYTHONPATH}:${PWD}"
    nice -n 19 python config/generate_tff_configs.py \
        --era "$ERA" \
        --channels "$CHANNELS"
    ;;

PRESEL)
    check_env
    echo "[PRESEL] Running TauFakeFactors preselection: era=$ERA channels=$CHANNELS"
    export PYTHONPATH="${PYTHONPATH}:${PWD}/TauFakeFactors"
    IFS=',' read -ra CHANNEL_LIST <<< "$CHANNELS"
    for CH in "${CHANNEL_LIST[@]}"; do
        echo "[PRESEL] Processing channel $CH"
        # Phase 6e note: this used to also pass `--columns "${OUTPUT_FEATURES[@]}"`,
        # an argument preselection.py's argparse doesn't define at all (it reads
        # output_features from the config file itself) -- that made every real
        # PRESEL invocation fail with "unrecognized arguments". Removed; see
        # STATUS.md Phase 6e.
        nice -n 19 python TauFakeFactors/preselection.py \
            --config-file "TauFakeFactors/configs/smhtt_ul/${ERA}/preselection_${CH}.yaml" \
            --nthreads "$NTHREADS" \
            "$@"
    done
    ;;

FF)
    echo "[FF] Running TauFakeFactors fake factor calculation: era=$ERA channels=$CHANNELS"
    export PYTHONPATH="${PYTHONPATH}:${PWD}/TauFakeFactors"
    # Phase 6e note: TauFakeFactors/configs/smhtt_ul/{era}/ ships one config
    # PER CHANNEL (fake_factors_et.yaml, fake_factors_mt.yaml, ...), never a
    # joined-multi-channel file -- the old default here
    # (`fake_factors_${CHANNELS}.yaml`, CHANNELS defaulting to "et,mt,tt")
    # only ever matched a real file when $CHANNELS was a single channel. Now
    # loops per channel, same as PRESEL. $FF_CONFIG (if set) still overrides
    # for a single explicit config file, unchanged.
    if [[ -n "$FF_CONFIG" ]]; then
        nice -n 19 python TauFakeFactors/ff_calculation.py --config-file "$FF_CONFIG" "$@"
    else
        IFS=',' read -ra CHANNEL_LIST <<< "$CHANNELS"
        for CH in "${CHANNEL_LIST[@]}"; do
            nice -n 19 python TauFakeFactors/ff_calculation.py \
                --config-file "TauFakeFactors/configs/smhtt_ul/${ERA}/fake_factors_${CH}.yaml" \
                "$@"
        done
    fi
    ;;

FF-CORR)
    echo "[FF-CORR] Running TauFakeFactors fake factor corrections: era=$ERA channels=$CHANNELS"
    export PYTHONPATH="${PYTHONPATH}:${PWD}/TauFakeFactors"
    # Phase 6e note: same per-channel-file issue as FF above, plus the old
    # default filename prefix was wrong (`ff_corrections_{ch}.yaml` -- the
    # real files are named `corrections_{ch}.yaml`), so this mode's default
    # never pointed at a file that exists. Fixed; $FF_CORR_CONFIG still
    # overrides for a single explicit config file.
    if [[ -n "$FF_CORR_CONFIG" ]]; then
        nice -n 19 python TauFakeFactors/ff_corrections.py --config-file "$FF_CORR_CONFIG" "$@"
    else
        IFS=',' read -ra CHANNEL_LIST <<< "$CHANNELS"
        for CH in "${CHANNEL_LIST[@]}"; do
            nice -n 19 python TauFakeFactors/ff_corrections.py \
                --config-file "TauFakeFactors/configs/smhtt_ul/${ERA}/corrections_${CH}.yaml" \
                "$@"
        done
    fi
    ;;

FF-MEASURE)
    check_env
    echo "[FF-MEASURE] Running the full TauFakeFactors FF measurement chain: era=$ERA channels=$CHANNELS"
    echo "[FF-MEASURE] (GEN-TFF-CONFIGS -> PRESEL -> FF -> FF-CORR, see run_fake_factor_measurement.py)"
    nice -n 19 python run_fake_factor_measurement.py \
        --era "$ERA" \
        --channels "$CHANNELS" \
        --nthreads "$NTHREADS" \
        "$@"
    ;;

TRAIN)
    TRAIN_TAG=${TRAIN_TAG:-"260507"}
    TRAIN_TASK=${TRAIN_TASK:-"RunAllCENNTConfusionMatrixWorkflow"}
    CUDA_DEVICE=${CUDA_DEVICE:-"0,1"}
    WORKERS=${WORKERS:-2}
    DATASET_DIR=${DATASET_DIR:-"/ceph/sgiappic/Htt_training/cennt_folds/coarse"}
    UAT_CONFIG_DIR=${UAT_CONFIG_DIR:-"/work/sgiappic/smhtt_ul/trainings/uncertainty-aware-training/datasets/smhtt/run3-coarse"}
    echo "[TRAIN] task=$TRAIN_TASK tag=$TRAIN_TAG channels=$CHANNELS"
    export PYTHONPATH="${PYTHONPATH}:${PWD}"
    cd trainings/uncertainty-aware-training || { echo "ERROR: trainings/uncertainty-aware-training not found"; exit 1; }
    law index -v
    cd - > /dev/null
    IFS=',' read -ra _TRAIN_CHANNELS <<< "$CHANNELS"
    for CH in "${_TRAIN_CHANNELS[@]}"; do
        echo "[TRAIN] Running $TRAIN_TASK for channel $CH"
        (
            cd trainings/uncertainty-aware-training
            law run "$TRAIN_TASK" \
                --workers "$WORKERS" \
                --local-scheduler \
                --version "${TRAIN_TAG}_${CH}" \
                --log-level INFO \
                --cuda-device "$CUDA_DEVICE" \
                --no-lock \
                --dataset-directory="${DATASET_DIR}/${CH}/" \
                --base-config-file="${UAT_CONFIG_DIR}/smhtt_${CH}.yaml"
        )
    done
    ;;

*)
    echo "TauHarvest — SM H→ττ analysis framework"
    echo ""
    echo "Usage: source run.sh <MODE> [options]"
    echo ""
    echo "Available modes:"
    echo "  XSEC            Build cross-section friend trees"
    echo "  SHAPES          Produce shapes (with systematics)"
    echo "  SHAPES-NOSYS    Produce nominal shapes only (fast)"
    echo "  PLOT            Plot control shapes (mplhep)"
    echo "  TRAIN-SHAPES    Produce shapes for NN training"
    echo "  CONFIGS         Collect ntuple_processor YAML configs"
    echo "  GEN-TFF-CONFIGS Regenerate TFF per-channel YAMLs from unified config"
    echo "  PRESEL          Run TauFakeFactors preselection (per channel)"
    echo "  FF              Run TauFakeFactors fake factor calculation (per channel)"
    echo "  FF-CORR         Run TauFakeFactors fake factor corrections (per channel)"
    echo "  FF-MEASURE      Run the full FF measurement chain: GEN-TFF-CONFIGS -> PRESEL -> FF -> FF-CORR"
    echo "                  (the four modes above still exist for single-step reruns)"
    echo "  TRAIN           Run NN training via law (uncertainty-aware-training)"
    echo ""
    echo "Required environment variables (for shape production):"
    echo "  NTUPLETAG          CROWN ntuple tag (e.g. htt_260417_2022-23)"
    echo "  TAG                Output label tag (optional, e.g. 260417)"
    echo ""
    echo "Optional:"
    echo "  ERA              (default: 2022postEE)"
    echo "  CHANNELS         (default: et,mt,tt)"
    echo "  VS_JET_WP        (default: Medium)"
    echo "  VS_ELE_WP        (default: VVLoose)"
    echo "  FF_FRIENDS_DIR   Path to fake factor friend trees (enables FF mode)"
    echo "  FF_CONFIG        Override config path for FF mode"
    echo "  FF_CORR_CONFIG   Override config path for FF-CORR mode"
    echo "  OUTPUT_DIR       (default: output)"
    echo "  NTHREADS         (default: 4)"
    echo "  NPROCS           (default: 1)"
    echo "  TRAIN_TAG        Training version tag (default: 260507)"
    echo "  TRAIN_TASK       law task name (default: RunAllCENNTConfusionMatrixWorkflow)"
    echo "  CUDA_DEVICE      GPU device IDs for training (default: 0,1)"
    echo "  WORKERS          law workers for training (default: 2)"
    echo "  DATASET_DIR      Base dir for training datasets (default: /ceph/sgiappic/Htt_training/cennt_folds/coarse)"
    echo "  UAT_CONFIG_DIR   Base dir for uncertainty-aware-training base configs"
    ;;
esac

