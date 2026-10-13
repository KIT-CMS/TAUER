from __future__ import annotations

import datetime
import getpass
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONDA_ENV = "tauer"
DEFAULT_CONDA_BASE = f"/work/{getpass.getuser()}/MiniForge"
DEFAULT_ACCOUNTING_GROUP = "cms.higgs"

_BOOTSTRAP_SENTINEL = "TAUER_CONDOR_ENV_BOOTSTRAPPED"


def csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _ensure_tauer_env() -> None:
    import importlib.util

    if importlib.util.find_spec("CustomLogging") is not None:
        return
    if os.environ.get(_BOOTSTRAP_SENTINEL):
        return

    import sys

    env = dict(os.environ)
    env[_BOOTSTRAP_SENTINEL] = "1"
    env["PYTHONPATH"] = f"{REPO_ROOT}:{REPO_ROOT / 'fake_factors'}:{env.get('PYTHONPATH', '')}"
    inner = " ".join(shlex.quote(a) for a in ["python3", *sys.argv])
    script = (
        f"source {shlex.quote(DEFAULT_CONDA_BASE)}/etc/profile.d/conda.sh && "
        f"conda activate {shlex.quote(DEFAULT_CONDA_ENV)} && exec {inner}"
    )
    os.execvpe("bash", ["bash", "-c", script], env)


_ensure_tauer_env()


def default_proxy_path() -> str:
    proxy = os.environ.get("X509_USER_PROXY")
    if proxy:
        return proxy
    return str(Path.home() / ".globus" / "x509up")


@dataclass
class JobSpec:

    name: str
    arguments: str


@dataclass
class SubmissionPlan:
    stage: str  # "shapes" | "estimation-ff" | "estimation-ss-os" | "btag_efficiencies" | "fake_factors" | ...
    tag: str | None  # optional batch label; omitted from run_dir when unset
    entry_point: str  # path to the python script, relative to REPO_ROOT
    jobs: list  # list[JobSpec]
    ntupletag: str | None = None  # CROWN ntuple production tag, when the stage has one
    conda_env: str = DEFAULT_CONDA_ENV
    # tau_es/make_taues_datacard.py + run_taues_fit.py need the CMSSW/Combine environment
    # (utils/setup_cmssw.sh), not the tauer conda env; "cmssw" sources that instead.
    env_mode: str = "conda"  # "conda" | "cmssw" | "lcg"
    request_cpus: int = 1
    request_memory_mb: int = 4000
    request_disk_kb: int = 4_000_000
    extra_classads: dict = field(default_factory=dict)

    @cached_property
    def timestamp(self) -> str:
        return f"{datetime.datetime.now():%Y%m%d-%H%M%S}"

    @property
    def run_dir(self) -> Path:
        # condor/run/<ntupletag>/[<tag>/]<stage>/<timestamp>/
        parts = [self.ntupletag or "notag"]
        if self.tag:
            parts.append(self.tag)
        return Path(REPO_ROOT, "condor", "run", *parts, self.stage, self.timestamp)

    @property
    def log_dir(self) -> Path:
        return self.run_dir / "log"

    @property
    def out_dir(self) -> Path:
        return self.run_dir / "out"

    @property
    def err_dir(self) -> Path:
        return self.run_dir / "err"


def write_wrapper_script(plan: SubmissionPlan) -> Path:
    wrapper = plan.run_dir / "wrapper.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)

    if plan.env_mode == "cmssw":
        # tau_es/make_taues_datacard.py + run_taues_fit.py need CombineHarvester/Combine's
        # Python bindings and combine/combineTool.py/text2workspace.py, i.e. cmsenv.
        env_block = f"""source {REPO_ROOT}/utils/setup_cmssw.sh
export PYTHONPATH="{REPO_ROOT}:${{PYTHONPATH:-}}\""""
    elif plan.env_mode == "lcg":
        # CROWN's LCG view: its ROOT/xrootd client authenticates to the GridKA dCache, the conda xrootd 6 one does not.
        env_block = f"""source /cvmfs/sft.cern.ch/lcg/views/LCG_110/x86_64-el9-gcc16-opt/setup.sh
export LD_PRELOAD=/cvmfs/sft.cern.ch/lcg/releases/gcc/16.1.0-43042/x86_64-el9/lib64/libstdc++.so.6
export PYTHONPATH="{REPO_ROOT}:${{PYTHONPATH:-}}\""""
    else:
        env_block = f"""source {DEFAULT_CONDA_BASE}/etc/profile.d/conda.sh
conda activate {plan.conda_env}
export PYTHONPATH="{REPO_ROOT}:{REPO_ROOT}/fake_factors:${{PYTHONPATH:-}}\""""

    content = f"""#!/bin/bash
set -eo pipefail
cd {REPO_ROOT}
{env_block}
echo "[wrapper] host=$(hostname) stage={plan.stage} entry_point={plan.entry_point}"
echo "[wrapper] args: $@"
exec nice -n 19 python3 {plan.entry_point} "$@"
"""
    wrapper.write_text(content)
    wrapper.chmod(0o755)
    return wrapper


def build_submit_text(plan: SubmissionPlan, wrapper: Path) -> str:
    log_dir = plan.log_dir
    out_dir = plan.out_dir
    err_dir = plan.err_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    err_dir.mkdir(parents=True, exist_ok=True)
    classads = {
        "universe": "vanilla",
        "executable": str(wrapper),
        "should_transfer_files": "YES",
        "when_to_transfer_output": "ON_EXIT",
        "transfer_output_files": '""',
        "requirements": "(TARGET.ProvidesEtpResources =?= true)",
        "getenv": "False",
        "notification": "Never",
        "accounting_group": DEFAULT_ACCOUNTING_GROUP,
        "x509userproxy": default_proxy_path(),
        "request_cpus": str(plan.request_cpus),
        "request_memory": str(plan.request_memory_mb),
        "request_disk": str(plan.request_disk_kb),
        # Mirrors run_dir so condor_q groups each submission separately.
        "JobBatchName": "-".join(["tauer", *plan.run_dir.relative_to(REPO_ROOT / "condor" / "run").parts]),
        "log": str(log_dir / "$(job_name).log"),
        "output": str(out_dir / "$(job_name).out"),
        "error": str(err_dir / "$(job_name).err"),
    }
    classads.update(plan.extra_classads)

    lines = [f"{k} = {v}" for k, v in classads.items()]
    lines.append("")
    lines.append("queue job_name, arguments from (")
    for job in plan.jobs:
        if '"' in job.arguments:
            raise ValueError(
                f"Job {job.name!r} arguments contain a double-quote, which "
                "would break the condor 'queue ... from' itemdata quoting: "
                f"{job.arguments!r}"
            )
        lines.append(f'    {job.name}, "{job.arguments}"')
    lines.append(")")
    return "\n".join(lines) + "\n"


def write_submit_file(plan: SubmissionPlan, wrapper: Path) -> Path:
    submit_file = plan.run_dir / "submit.sub"
    submit_file.write_text(build_submit_text(plan, wrapper))
    return submit_file


def submit(plan: SubmissionPlan, dry_run: bool = False) -> int:
    """Write the wrapper + submit file, then either
    `condor_submit -dry-run` (validate classads only, no jobs queued) or a
    real `condor_submit`. Returns the subprocess return code."""
    if not plan.jobs:
        print(f"[condor] stage={plan.stage} tag={plan.tag or '-'}: no jobs to submit, skipping.")
        return 0

    wrapper = write_wrapper_script(plan)
    submit_file = write_submit_file(plan, wrapper)
    print(f"[condor] stage={plan.stage} tag={plan.tag or '-'} jobs={len(plan.jobs)}")
    for job in plan.jobs:
        print(f"[condor]   - {job.name}: {plan.entry_point} {job.arguments}")
    print(f"[condor] submit file: {submit_file}")
    print(f"[condor] wrapper:     {wrapper}")

    if dry_run:
        dry_run_out = plan.run_dir / "dry_run_classads.txt"
        cmd = ["condor_submit", "-dry-run", str(dry_run_out), str(submit_file)]
    else:
        cmd = ["condor_submit", str(submit_file)]
    print(f"[condor] running: {' '.join(shlex.quote(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=plan.run_dir)
    if dry_run and result.returncode == 0:
        print(f"[condor] dry-run classads written to: {dry_run_out}")
    return result.returncode
