"""
Helper for running CombineHarvester/Combine binaries and combine_datacards/
scripts that need the CMSSW `cmsenv` environment set up first.

Phase 6d note (see STATUS.md "## Phase 6d"): the datacards/*.py control
scripts (produce_datacard.py, produce_gof_datacard.py, produce_workspace.py,
produce_gof_workspace.py, run_gof.py, run_impacts.py) are pure Python -- all
argument parsing, path construction, looping/parallel-toy logic, and JSON
post-processing lives there. The *only* remaining bash is `utils/setup_cmssw.sh`
itself (kept as a thin environment-sourcing shim, per the explicit exception in
the task instructions: sourcing `cmsenv` mutates PATH/LD_LIBRARY_PATH/PYTHONPATH
in a way that only takes effect in the shell that sources it -- there is no
portable way to do this from a plain `subprocess.run(...)` call without shelling
back out to bash for that one step). This module is the single place that shim
is invoked from Python: every datacards/*.py script goes through
`run_in_cmsenv()` (single command) or `get_fitdir()` (read `$FITDIR`) instead of
each re-implementing its own `bash -c "source utils/setup_cmssw.sh && ..."`
string.
"""
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
    """Source utils/setup_cmssw.sh in a throwaway subshell and return the
    resulting $FITDIR (mirrors what every datacards/*.sh script used to do by
    sourcing it directly and then referencing ${FITDIR})."""
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
    """Source utils/setup_cmssw.sh, then run `cmd_args` as a real subprocess
    in that environment (combine/combineTool.py/text2workspace.py/plotImpacts.py/
    plotGof.py are all genuine external CMSSW/Combine binaries reached this
    way, exactly as before -- nothing from CombineHarvester/Combine is
    vendored). Streams stdout/stderr straight through by default (no capture)
    so real-time `combine` progress output still shows up, matching the old
    bash scripts' behavior; pass stdout=/stderr= to redirect (e.g. to a log
    file, mirroring the old scripts' `>"toys_${SEED}.log" 2>&1`).

    `unlimited_stack=True` reproduces the old scripts' `ulimit -s unlimited`
    (several Combine fits need a larger stack than the default soft limit).

    `background=True` returns the live `subprocess.Popen` immediately instead
    of waiting for completion (mirrors the old scripts' `... &` + `wait`
    pattern for parallel toy-throwing in run_gof.py)."""
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
    """PYTHONPATH value that includes the repo root + TauFakeFactors (needed
    because config/logging_setup_configs.py imports TauFakeFactors's
    CustomLogging package -- see STATUS.md Phase 4)."""
    parts = [str(REPO_ROOT), str(REPO_ROOT / "TauFakeFactors")]
    if extra:
        parts.append(extra)
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    return ":".join(parts)
