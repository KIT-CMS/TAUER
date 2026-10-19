"""The environments TAUER runs in: the `tauer` conda env, CMSSW (Combine) and CROWN's LCG view, for local runs and condor jobs."""
from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_CMSSW = REPO_ROOT / "utils" / "setup_cmssw.sh"
DEFAULT_CONDA_ENV = "tauer"
DEFAULT_CONDA_BASE = str(REPO_ROOT.parent / "MiniForge")
_BOOTSTRAP_SENTINEL = "TAUER_CONDOR_ENV_BOOTSTRAPPED"


def _merged_env(env_overrides: Optional[Mapping[str, str]]) -> dict:
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return env


def pythonpath_with_tff(extra: str = "") -> str:
    parts = [str(REPO_ROOT), str(REPO_ROOT / "fake_factors")]
    if extra:
        parts.append(extra)
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    return ":".join(parts)


def env_block(env_mode: str = "conda", conda_env: str = DEFAULT_CONDA_ENV) -> str:
    """Shell lines setting up a job environment: the condor wrapper and the local commands printed by `tauer`."""
    if env_mode == "cmssw":
        # tau_es/make_taues_datacard.py + run_taues_fit.py need CombineHarvester/Combine's
        # Python bindings and combine/combineTool.py/text2workspace.py, i.e. cmsenv.
        return f"""source {SETUP_CMSSW}
export PYTHONPATH="{REPO_ROOT}:${{PYTHONPATH:-}}\""""
    if env_mode == "lcg":
        # CROWN's LCG view: its ROOT/xrootd client authenticates to the GridKA dCache, the conda xrootd 6 one does not.
        return f"""source /cvmfs/sft.cern.ch/lcg/views/LCG_110/x86_64-el9-gcc16-opt/setup.sh
export LD_PRELOAD=/cvmfs/sft.cern.ch/lcg/releases/gcc/16.1.0-43042/x86_64-el9/lib64/libstdc++.so.6
export PYTHONPATH="{REPO_ROOT}:${{PYTHONPATH:-}}\""""
    return f"""source {DEFAULT_CONDA_BASE}/etc/profile.d/conda.sh
conda activate {conda_env}
export PYTHONPATH="{REPO_ROOT}:{REPO_ROOT}/fake_factors:${{PYTHONPATH:-}}\""""


def ensure_tauer_env() -> None:
    """Re-executes the current script inside the `tauer` conda env if it was started outside of it."""
    if importlib.util.find_spec("CustomLogging") is not None or os.environ.get(_BOOTSTRAP_SENTINEL):
        return
    env = {**os.environ, _BOOTSTRAP_SENTINEL: "1", "PYTHONPATH": pythonpath_with_tff()}
    inner = " ".join(shlex.quote(a) for a in ["python3", *sys.argv])
    script = (
        f"source {shlex.quote(DEFAULT_CONDA_BASE)}/etc/profile.d/conda.sh && "
        f"conda activate {shlex.quote(DEFAULT_CONDA_ENV)} && exec {inner}"
    )
    os.execvpe("bash", ["bash", "-c", script], env)


def run_in_conda(
    cmd_args: Iterable[str],
    cwd: Optional[Path] = None,
    env_overrides: Optional[Mapping[str, str]] = None,
    conda_env: str = DEFAULT_CONDA_ENV,
    conda_base: str = DEFAULT_CONDA_BASE,
    check: bool = True,
) -> subprocess.CompletedProcess:
    inner = " ".join(shlex.quote(a) for a in cmd_args)
    script = (
        f"source {shlex.quote(conda_base)}/etc/profile.d/conda.sh && "
        f"conda activate {shlex.quote(conda_env)} && {inner}"
    )
    result = subprocess.run(["bash", "-c", script], cwd=str(cwd or REPO_ROOT), env=_merged_env(env_overrides))
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd_args)
    return result


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
