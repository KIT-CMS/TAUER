from __future__ import annotations

import getpass
import re
from dataclasses import dataclass

XROOTD_REDIRECTOR = "root://cmsdcache-kit-disk.gridka.de/"
_NTUPLE_BASE_TEMPLATE = "/store/user/{user}/CROWN/ntuples/{ntupletag}"
_NTUPLE_DIRECTORY_RE = re.compile(
    "^"
    + _NTUPLE_BASE_TEMPLATE.format(user="([^/]+)", ntupletag="([^/]+)")
    + r"/CROWNRun/?$"
)


def crown_ntuple_base(ntupletag: str, user: str | None = None) -> str:
    user = user or getpass.getuser()
    return _NTUPLE_BASE_TEMPLATE.format(user=user, ntupletag=ntupletag)


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
    ntuples: str


def build_ul_sample_paths(ntupletag: str, era: str, user: str | None = None) -> UlSamplePaths:
    user = user or getpass.getuser()
    base = crown_ntuple_base(ntupletag, user=user)
    kingmaker_basedir = f"{base}/CROWNRun/"
    kingmaker_basedir_xrootd = f"{XROOTD_REDIRECTOR}{kingmaker_basedir}"

    if not any(supported in era for supported in RUN3_ERAS_SUPPORTED):
        raise ValueError(
            f"Unsupported era: {era} (TAUER is Run3-only: "
            f"{', '.join(RUN3_ERAS_SUPPORTED)})"
        )
    ntuples = kingmaker_basedir

    return UlSamplePaths(
        kingmaker_basedir=kingmaker_basedir,
        kingmaker_basedir_xrootd=kingmaker_basedir_xrootd,
        ntuples=ntuples,
    )


@dataclass(frozen=True)
class ShapeOutputPaths:
    base: str
    output: str
    validation: str
    training: str
    fake_factors: str


def build_shape_output_paths(ntupletag: str, user: str | None = None) -> ShapeOutputPaths:
    user = user or getpass.getuser()
    base = f"/ceph/{user}/TAUER_shapes/{ntupletag}"
    return ShapeOutputPaths(
        base=base,
        output=f"{base}/output",
        validation=f"{base}/validation",
        training=f"{base}/training",
        fake_factors=f"{base}/fake_factors",
    )


def build_selection_friend_dir(ntupletag: str, selection_tag: str, user: str | None = None) -> str:
    return f"{crown_ntuple_base(ntupletag, user=user)}/CROWNFriend/{selection_tag}/"


def build_friend_dir(ntupletag: str, friend_tag: str, user: str | None = None) -> str:
    return f"{crown_ntuple_base(ntupletag, user=user)}/CROWNFriend/{friend_tag}/"


def parse_ntuple_directory(directory: str) -> tuple[str, str]:
    m = _NTUPLE_DIRECTORY_RE.match(directory)
    if not m:
        raise ValueError(
            f"Cannot derive (user, ntupletag) from directory {directory!r}: "
            "it does not match the standard "
            "/store/user/<user>/CROWN/ntuples/<ntupletag>/CROWNRun/ convention "
            "(build_ul_sample_paths().ntuples). Pass --selection-friend as a "
            "full path instead, or use a --directory built by that helper."
        )
    return m.group(1), m.group(2)
