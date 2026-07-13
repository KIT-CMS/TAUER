#!/bin/bash
set -e
NTUPLETAG=$1
ERA=$2

# Base directories for CROWN ntuple output
KINGMAKER_BASEDIR="/store/user/${USER}/CROWN/ntuples/${NTUPLETAG}/CROWNRun/"
KINGMAKER_BASEDIR_XROOTD="root://cmsdcache-kit-disk.gridka.de/${KINGMAKER_BASEDIR}"

# Cross-section friend tree
XSEC_FRIENDS="/store/user/${USER}/CROWN/ntuples/${NTUPLETAG}/CROWNFriends/xsec/"

# Run3-only era support
if [[ $ERA == *"2022preEE"* ]]; then
    NTUPLES=$KINGMAKER_BASEDIR
elif [[ $ERA == *"2022postEE"* ]]; then
    NTUPLES=$KINGMAKER_BASEDIR
elif [[ $ERA == *"2023preBPix"* ]]; then
    NTUPLES=$KINGMAKER_BASEDIR
elif [[ $ERA == *"2023postBPix"* ]]; then
    NTUPLES=$KINGMAKER_BASEDIR
elif [[ $ERA == *"2024"* ]]; then
    NTUPLES=$KINGMAKER_BASEDIR
elif [[ $ERA == *"2025"* ]]; then
    NTUPLES=$KINGMAKER_BASEDIR
else
    echo "ERROR: Unsupported era: $ERA (TauHarvest is Run3-only: 2022preEE, 2022postEE, 2023preBPix, 2023postBPix, 2024, 2025)"
    exit 1
fi
