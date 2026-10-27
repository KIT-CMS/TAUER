from __future__ import annotations

import datetime
import getpass
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from functools import cached_property
from typing import Callable
from pathlib import Path

from utils.environment import DEFAULT_CONDA_BASE, DEFAULT_CONDA_ENV, REPO_ROOT, ensure_tauer_env, env_block as _env_block

DEFAULT_ACCOUNTING_GROUP = "cms.higgs"
PACKED_ENV_DIR = Path(f"/ceph/{getpass.getuser()}/tauer_envs")
# the TOpAS GPU containers have no /ceph: packed jobs get their /ceph inputs through this GridKa dCache mirror
DCACHE_HOST = "cmsdcache-kit-disk.gridka.de"
DCACHE_MIRROR = f"/store/user/{getpass.getuser()}/tauer_remote"
CODE_EXCLUDES = ("./.git", "./condor/run", "./logs", "./fake_factors", "./btag_efficiencies", "./validation_database", "__pycache__")


def csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


ensure_tauer_env()


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
    env_mode: str = "conda"  # "conda" | "cmssw" | "lcg" | "packed"
    request_cpus: int = 1
    request_memory_mb: int = 4000
    request_disk_kb: int = 4_000_000
    extra_classads: dict = field(default_factory=dict)
    cluster: int | None = None  # set by submit() from condor_submit's output
    setups: list[Callable] = field(default_factory=list)  # filesystem writes the jobs rely on, run only by a real submit
    run_root: Path | None = None  # redirects run_dir (a dry run uses a temporary directory)
    # env_mode "packed": {job-local dir: /ceph path} copied in through dCache, and the /ceph directory the job's ./<its name> is transferred back into
    stage_in: dict = field(default_factory=dict)
    stage_out: str | None = None

    @cached_property
    def timestamp(self) -> str:
        return f"{datetime.datetime.now():%Y%m%d-%H%M%S}"

    @property
    def run_parts(self) -> tuple:
        # <ntupletag>/[<tag>/]<stage>/<timestamp>
        return (self.ntupletag or "notag", *([self.tag] if self.tag else []), self.stage, self.timestamp)

    @property
    def run_dir(self) -> Path:
        # condor/run/<ntupletag>/[<tag>/]<stage>/<timestamp>/
        return Path(self.run_root or REPO_ROOT / "condor" / "run", *self.run_parts)

    @property
    def log_dir(self) -> Path:
        return self.run_dir / "log"

    @property
    def out_dir(self) -> Path:
        return self.run_dir / "out"

    @property
    def err_dir(self) -> Path:
        return self.run_dir / "err"


def env_block(plan: SubmissionPlan) -> str:
    return _env_block(plan.env_mode, plan.conda_env)


def packed_env_path(conda_env: str) -> Path:
    return PACKED_ENV_DIR / f"{conda_env}.tar.gz"


def dcache_url(path) -> str:
    return f"root://{DCACHE_HOST}/{DCACHE_MIRROR}/{Path(path).relative_to(f'/ceph/{getpass.getuser()}')}"


def mirror_to_dcache(path: Path) -> None:
    """Uploads the files of `path` that are missing on the dCache mirror or have another size there."""
    env = {**os.environ, "X509_USER_PROXY": default_proxy_path()}
    for f in [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file()):
        url = dcache_url(f)
        stat = subprocess.run(["xrdfs", DCACHE_HOST, "stat", url.split(DCACHE_HOST, 1)[1]], capture_output=True, text=True, env=env).stdout
        if (m := re.search(r"Size:\s+(\d+)", stat)) and int(m.group(1)) == f.stat().st_size:
            continue
        print(f"[condor] uploading {f} to {url}")
        subprocess.run(["xrdcp", "-f", "-s", str(f), url], check=True, env=env)


def pack_for_remote(plan: SubmissionPlan) -> None:
    """env_mode "packed": the working tree goes next to submit.sub, the conda env to /ceph (re-packed when the env changed)."""
    plan.run_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "-czf", str(plan.run_dir / "code.tar.gz"), *(f"--exclude={e}" for e in CODE_EXCLUDES), "-C", str(REPO_ROOT), "."], check=True)
    prefix, tarball = Path(DEFAULT_CONDA_BASE, "envs", plan.conda_env), packed_env_path(plan.conda_env)
    changed = max(p.stat().st_mtime for p in [prefix / "conda-meta", *prefix.glob("lib/python3*/site-packages")])
    if not tarball.exists() or tarball.stat().st_mtime < changed:
        print(f"[condor] packing the {plan.conda_env} env into {tarball} (a few minutes)")
        tarball.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["conda-pack", "-p", str(prefix), "-o", f"{tarball}.tmp", "--format", "tar.gz", "--force", "--ignore-missing-files", "--quiet"], check=True)
        os.replace(f"{tarball}.tmp", tarball)
    for path in [tarball, *plan.stage_in.values()]:
        mirror_to_dcache(Path(path))


def write_wrapper_script(plan: SubmissionPlan) -> Path:
    wrapper = plan.run_dir / "wrapper.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    # remote workers (TOpAS GPUs) have neither /ceph nor /work: env and inputs come from dCache, the code with the job
    stage_in = "".join(f"mkdir -p {Path(local).parent} && xrdcp -r -s {dcache_url(path)} {Path(local).parent}/\n" for local, path in plan.stage_in.items())
    setup = f"""mkdir -p env tauer {Path(plan.stage_out).name if plan.stage_out else ""}
xrdcp -s {dcache_url(packed_env_path(plan.conda_env))} env.tar.gz
tar -xzf env.tar.gz -C env && rm env.tar.gz
{stage_in}source env/bin/activate
conda-unpack
tar -xzf code.tar.gz -C tauer
cd tauer
export LAW_HOME="$PWD/.law"
export PYTHONPATH="$PWD:$PWD/fake_factors:${{PYTHONPATH:-}}\"""" if plan.env_mode == "packed" else f"cd {REPO_ROOT}\n{env_block(plan)}"

    content = f"""#!/bin/bash
set -eo pipefail
ulimit -c 0
export USER={getpass.getuser()}
{setup}
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
        "JobBatchName": "-".join(["tauer", *plan.run_parts]),
        "log": str(log_dir / "$(job_name).log"),
        "output": str(out_dir / "$(job_name).out"),
        "error": str(err_dir / "$(job_name).err"),
    }
    if plan.env_mode == "packed":
        classads["transfer_input_files"] = str(plan.run_dir / "code.tar.gz")
        if plan.stage_out:
            classads.update(initialdir=str(Path(plan.stage_out).parent), transfer_output_files=Path(plan.stage_out).name)
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
    `condor_submit -dry-run` (validate classads only, no jobs queued, nothing written outside a
    temporary directory) or a real `condor_submit`. Returns the subprocess return code; the
    cluster id lands in plan.cluster."""
    if not plan.jobs:
        print(f"[condor] stage={plan.stage} tag={plan.tag or '-'}: no jobs to submit, skipping.")
        return 0

    if dry_run:
        with tempfile.TemporaryDirectory(prefix="tauer_dry_run_") as tmp:
            plan.run_root = Path(tmp)
            try:
                return _submit(plan, dry_run=True)
            finally:
                plan.run_root = None
    if plan.env_mode == "packed":
        pack_for_remote(plan)
    for setup in plan.setups:
        setup()
    return _submit(plan, dry_run=False)


def _submit(plan: SubmissionPlan, dry_run: bool) -> int:
    wrapper = write_wrapper_script(plan)
    submit_file = write_submit_file(plan, wrapper)
    print(f"[condor] stage={plan.stage} tag={plan.tag or '-'} jobs={len(plan.jobs)}")
    for job in plan.jobs:
        print(f"[condor]   - {job.name}: {plan.entry_point} {job.arguments}")
    if dry_run:
        print("[condor] dry run: submit file, wrapper and classads live in a temporary directory that is removed afterwards")
    else:
        print(f"[condor] submit file: {submit_file}")
        print(f"[condor] wrapper:     {wrapper}")

    if dry_run:
        cmd = ["condor_submit", "-dry-run", str(plan.run_dir / "dry_run_classads.txt"), str(submit_file)]
    else:
        cmd = ["condor_submit", str(submit_file)]
    print(f"[condor] running: {' '.join(shlex.quote(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=plan.run_dir, capture_output=True, text=True)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if match := re.search(r"submitted to cluster (\d+)", result.stdout):
        plan.cluster = int(match.group(1))
    return result.returncode
