from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_CMSSW = REPO_ROOT / "utils" / "setup_cmssw.sh"


def _merged_env(env_overrides: Optional[Mapping[str, str]]) -> dict:
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return env


def get_fitdir(env_overrides: Optional[Mapping[str, str]] = None) -> str:
    cmd = f'source {shlex.quote(str(SETUP_CMSSW))} >/dev/null && echo "$FITDIR"'
    result = subprocess.run(
        ["bash", "-c", cmd],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_merged_env(env_overrides),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to source {SETUP_CMSSW} to determine FITDIR:\n{result.stderr}"
        )
    fitdir = result.stdout.strip()
    if not fitdir:
        raise RuntimeError(f"{SETUP_CMSSW} produced an empty $FITDIR")
    return fitdir


def run_in_cmsenv(
    cmd_args: Iterable[str],
    cwd: Optional[Path] = None,
    env_overrides: Optional[Mapping[str, str]] = None,
    check: bool = True,
    unlimited_stack: bool = False,
    background: bool = False,
    stdout=None,
    stderr=None,
):
    inner = " ".join(shlex.quote(a) for a in cmd_args)
    prefix = "ulimit -s unlimited; " if unlimited_stack else ""
    # Every Combine/CombineTool/text2workspace invocation runs niced (matches
    # run.py's run_plain/run_conda convention) -- this is the single place
    # datacards/*.py and tau_es/*.py funnel through, so nicing it here covers
    # all of them without touching each call site.
    script = f"{prefix}source {shlex.quote(str(SETUP_CMSSW))} && nice -n 19 {inner}"
    popen_kwargs = dict(
        cwd=str(cwd or REPO_ROOT),
        env=_merged_env(env_overrides),
        stdout=stdout,
        stderr=stderr,
    )
    if background:
        return subprocess.Popen(["bash", "-c", script], **popen_kwargs)

    result = subprocess.run(["bash", "-c", script], **popen_kwargs)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd_args)
    return result


def pythonpath_with_tff(extra: str = "") -> str:
    parts = [str(REPO_ROOT), str(REPO_ROOT / "fake_factors")]
    if extra:
        parts.append(extra)
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    return ":".join(parts)
