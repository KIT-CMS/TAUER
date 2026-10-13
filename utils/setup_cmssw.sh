#!/bin/bash
# Set up the CMSSW / CombineHarvester / Combine environment used by
# datacards/*.sh. 

export SCRAM_ARCH=${SCRAM_ARCH:-el9_amd64_gcc12}
export VO_CMS_SW_DIR=/cvmfs/cms.cern.ch
source $VO_CMS_SW_DIR/cmsset_default.sh

export PYTHONNOUSERSITE=1

CMSSW_BASE_DIR=${CMSSW_BASE_DIR:-/ceph/${USER}}
CMSSW_RELEASE=${CMSSW_RELEASE:-CMSSW_15_0_2}

pushd "${CMSSW_BASE_DIR}/${CMSSW_RELEASE}/src"
eval `scramv1 runtime -sh`
popd

# FITDIR is where datacards/*.sh read shapes from and write datacards/workspaces
# to (see datacards/produce_datacard.sh, produce_workspace.sh). Defaults to the
# TAUER repo root shapes/datacards output area; override before sourcing
# this script to point elsewhere.
export FITDIR=${FITDIR:-$(pwd)}
