"""
Run a subprocess inside the `taukitflow` conda env.

Phase 6d replacement for run.sh's `check_env()` (`conda activate taukitflow`)
-- see STATUS.md "## Phase 6d". `conda activate` mutates PATH/CONDA_* env-vars
in a way that only takes effect in the shell that runs it, so (like
common/cmsenv.py for CMSSW's `cmsenv`) this module is the one place that still
shells out to bash, only to source `conda.sh` + `conda activate`; the actual
command being run, its arguments, and all the orchestration/mode-dispatch
logic around it are plain Python (run.py), not more bash layered on top.
Mirrors the same activation sequence condor/common.py's generated wrapper
already uses (same conda base/env, same "don't also source the LCG view"
reasoning documented there).
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONDA_ENV = "taukitflow"
DEFAULT_CONDA_BASE = "/work/sgiappic/MiniForge"


def run_in_conda(
    cmd_args: Iterable[str],
    cwd: Optional[Path] = None,
    env_overrides: Optional[Mapping[str, str]] = None,
    conda_env: str = DEFAULT_CONDA_ENV,
    conda_base: str = DEFAULT_CONDA_BASE,
    check: bool = True,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    inner = " ".join(shlex.quote(a) for a in cmd_args)
    script = (
        f"source {shlex.quote(conda_base)}/etc/profile.d/conda.sh && "
        f"conda activate {shlex.quote(conda_env)} && {inner}"
    )
    result = subprocess.run(["bash", "-c", script], cwd=str(cwd or REPO_ROOT), env=env)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd_args)
    return result
