"""
CROWN ntuple / friend-tree path helpers for Run3 (Phase 6d, see STATUS.md
"## Phase 6d"). This replaces the former `utils/setup_ul_samples.sh`, whose
only job was pure path-string construction from (ntuple_tag, era) -- no
environment sourcing, no PATH/PYTHONHOME mutation -- so unlike
`utils/setup_cmssw.sh`/`utils/setup_root.sh` there is no reason for it to stay
bash; it is a plain function now, importable directly by `run.py` and (in the
future, if it ever needs to stop hand-duplicating this logic)
`condor/submit_shapes.py`, which currently has its own inline copy of the same
`/store/user/.../CROWN/ntuples/...` convention (see its own docstring).

Run3-only, matching the original script's era support exactly (the original
`elif` chain covered exactly these six eras and raised for anything else).
"""
from __future__ import annotations

import getpass
from dataclasses import dataclass

XROOTD_REDIRECTOR = "root://cmsdcache-kit-disk.gridka.de/"

RUN3_ERAS_SUPPORTED = (
    "2022preEE",
    "2022postEE",
    "2023preBPix",
    "2023postBPix",
    "2024",
    "2025",
    "2026",
)


@dataclass(frozen=True)
class UlSamplePaths:
    kingmaker_basedir: str
    kingmaker_basedir_xrootd: str
    xsec_friends: str
    ntuples: str


def build_ul_sample_paths(ntupletag: str, era: str, user: str | None = None) -> UlSamplePaths:
    """Mirrors utils/setup_ul_samples.sh's NTUPLETAG/ERA -> path derivation
    byte-for-byte: same directory convention, same era substring matching
    (`"2024" in era` etc.), same "Unsupported era" failure for anything else."""
    user = user or getpass.getuser()
    kingmaker_basedir = f"/store/user/{user}/CROWN/ntuples/{ntupletag}/CROWNRun/"
    kingmaker_basedir_xrootd = f"{XROOTD_REDIRECTOR}{kingmaker_basedir}"
    xsec_friends = f"/store/user/{user}/CROWN/ntuples/{ntupletag}/CROWNFriends/xsec/"

    if not any(supported in era for supported in RUN3_ERAS_SUPPORTED):
        raise ValueError(
            f"Unsupported era: {era} (TauKITFlow is Run3-only: "
            f"{', '.join(RUN3_ERAS_SUPPORTED)})"
        )
    # All supported eras use the same bare CROWNRun directory (no per-era
    # subdirectory split) -- matching every branch of the original if/elif
    # chain, which all set NTUPLES=$KINGMAKER_BASEDIR.
    ntuples = kingmaker_basedir

    return UlSamplePaths(
        kingmaker_basedir=kingmaker_basedir,
        kingmaker_basedir_xrootd=kingmaker_basedir_xrootd,
        xsec_friends=xsec_friends,
        ntuples=ntuples,
    )


@dataclass(frozen=True)
class ShapeOutputPaths:
    base: str
    preselection: str
    output: str
    validation: str


def build_shape_output_paths(ntupletag: str, user: str | None = None) -> ShapeOutputPaths:
    """Single source of truth for the unified TauKITFlow shape-production output
    tree, replacing the previously scattered bare "output"/CWD-relative
    "validation_database" defaults and TFF's own separate /ceph/.../CMS_FF/<tag>
    output area.

        /ceph/$USER/TauKITFlow_shapes/$ntupletag/
        |-- preselection/<era>/<channel>/<process>[_<tau_gen_mode>].root
        |-- output/<tag>/<ss-os|ff>/<era>/<channels>/shapes.root
        `-- validation/<tag>/...

    One preselection directory, in one layout, consumed directly by BOTH
    shape production (shapes/produce_shapes.py --presel-dir, via
    ntuple_processor.booking's flat_layout branch) and TauFakeFactors'
    ff_calculation.py/ff_corrections.py (run.py's --ff-input-dir). No
    second CROWN-shaped mirror of it is needed.
    """
    user = user or getpass.getuser()
    base = f"/ceph/{user}/TauKITFlow_shapes/{ntupletag}"
    return ShapeOutputPaths(
        base=base,
        preselection=f"{base}/preselection",
        output=f"{base}/output",
        validation=f"{base}/validation",
    )
