from __future__ import annotations

import getpass
import os
import shlex
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONDA_ENV = "tauer"
DEFAULT_CONDA_BASE = f"/work/{getpass.getuser()}/MiniForge"


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
