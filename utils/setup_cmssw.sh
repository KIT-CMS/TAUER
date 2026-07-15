#!/bin/bash
# Set up the CMSSW / CombineHarvester / Combine environment used by
# datacards/*.sh. CMSSW itself is an external dependency -- it is not vendored
# into TauKITFlow, only consumed via `cmsenv` from the checkout below.
#
# Override CMSSW_BASE_DIR / CMSSW_RELEASE before sourcing this script to point
# at a different checkout, e.g.:
#   CMSSW_BASE_DIR=/some/other/path CMSSW_RELEASE=CMSSW_15_0_2 source utils/setup_cmssw.sh

export SCRAM_ARCH=${SCRAM_ARCH:-el9_amd64_gcc12}
export VO_CMS_SW_DIR=/cvmfs/cms.cern.ch
source $VO_CMS_SW_DIR/cmsset_default.sh

# Phase 4 fix: a user-site numpy (~/.local/lib/python3.9/site-packages, picked
# up because Python's user-site is on sys.path by default even inside cmsenv)
# shadows CMSSW's own bundled numpy (CVMFS py3-numpy 1.24.3). CVMFS's pandas is
# a compiled extension built against that bundled numpy's ABI, so importing
# the wrong numpy first breaks it at import time:
#   ValueError: numpy.dtype size changed, may indicate binary incompatibility.
#   Expected 96 from C header, got 88 from PyObject
# which in turn crashes text2workspace.py (HiggsAnalysis.CombinedLimit.ShapeTools
# imports pandas). Not a CMSSW bug -- fixed by excluding the user site-packages
# directory for the lifetime of this CMSSW shell.
export PYTHONNOUSERSITE=1

CMSSW_BASE_DIR=${CMSSW_BASE_DIR:-/ceph/sgiappic}
CMSSW_RELEASE=${CMSSW_RELEASE:-CMSSW_15_0_2}

pushd "${CMSSW_BASE_DIR}/${CMSSW_RELEASE}/src"
eval `scramv1 runtime -sh`
popd

# FITDIR is where datacards/*.sh read shapes from and write datacards/workspaces
# to (see datacards/produce_datacard.sh, produce_workspace.sh). Defaults to the
# TauKITFlow repo root shapes/datacards output area; override before sourcing
# this script to point elsewhere.
export FITDIR=${FITDIR:-$(pwd)}
