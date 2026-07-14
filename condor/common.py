"""
Shared HTCondor submission machinery for TauKITFlow's shapes/plotting/training
stages (condor/submit_shapes.py, condor/submit_plotting.py, condor/submit_training.py).

Design decision (recorded in STATUS.md, "Phase 2c"): this is a *standalone*
Python condor submitter, not a law/luigi HTCondorWorkflow.

- `law` is already used in this repo, but only in
  trainings/uncertainty-aware-training/ (_law_workflow_ff.py,
  _law_CENNT_workflow.py), and only for a *local* task graph (law.Task
  subclasses that call subprocess.run(...) directly, no
  law.contrib.htcondor.HTCondorWorkflow, no remote submission). It is not used
  anywhere for condor orchestration today.
- The instructions say to keep the law dependency as-is rather than grow it.
  Building a new law.contrib.htcondor.HTCondorWorkflow task graph for
  shapes/plotting/training would be a materially larger dependency footprint
  (bootstrap/job-file/proxy plumbing through law's workflow machinery,
  law.cfg wiring, luigi scheduler) than what "one job per (era, channel[, ...])
  fan-out from a single CLI invocation" actually requires.
- KingMaker's own condor usage (law.contrib.htcondor, see
  /work/sgiappic/KingMaker/law/law/contrib/htcondor and the generated
  htcondor_job.jdl files under KingMaker/data/*/htcondor_files/) is built for
  *containerized* CROWN production jobs (universe = container, a specific
  cvmfs-unpacked docker image, law's own job-wrapper/bootstrap scripts) — not
  a natural fit for shapes/plotting/training, which run in the existing
  `taukiktflow` conda env against a CVMFS LCG view, exactly like run.sh
  already invokes them interactively.
- Conclusion: a lightweight, standalone Python classad generator + `condor_submit`
  subprocess call is the right tool for this slice. All fan-out / job-spec logic
  is Python (this module + the per-stage submit_*.py CLIs); only the small
  per-job environment-bootstrap wrapper is generated as a bash script, which is
  the same division of labour run.sh already uses (bash for env setup, Python
  for everything else).

Conventions (validated against the live KIT-ETP condor pool, see STATUS.md):
- `/work/sgiappic` (this repo's location) and `/cvmfs` are mounted on execute
  nodes, so `should_transfer_files = NO` is used — no need to transfer the
  repo or the LCG view, jobs run in place. This differs from KingMaker's
  container-universe jobs, which explicitly transfer inputs/outputs because
  they assume no shared filesystem (remote/grid-submittable sites).
- `x509userproxy` / `accounting_group = cms.higgs` follow the same convention
  as KingMaker's generated .jdl files, for consistency across this user's
  condor usage at KIT-ETP.
- One shared "queue job_name, arguments from (...)" submit file per batch
  (per stage + tag), so `condor_submit` is invoked exactly once per
  submission command, fanning out into N separate jobs.
"""
from __future__ import annotations

import datetime
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONDA_ENV = "taukiktflow"
DEFAULT_CONDA_BASE = "/work/sgiappic/MiniForge"
DEFAULT_ACCOUNTING_GROUP = "cms.higgs"


def default_proxy_path() -> str:
    """Grid proxy path: $X509_USER_PROXY if set, else the standard
    ~/.globus/x509up location already used by this user's other tooling
    (see STATUS.md pre-flight: `voms-proxy-info -path`)."""
    proxy = os.environ.get("X509_USER_PROXY")
    if proxy:
        return proxy
    return str(Path.home() / ".globus" / "x509up")


@dataclass
class JobSpec:
    """One HTCondor job: `name` must be a filesystem/classad-safe token
    (used for log/out/err filenames and JobBatchName disambiguation);
    `arguments` is the full argument string passed to the target script."""

    name: str
    arguments: str


@dataclass
class SubmissionPlan:
    stage: str  # "shapes" | "plotting" | "training"
    tag: str  # batch tag: run directory name + JobBatchName suffix
    entry_point: str  # path to the python script, relative to REPO_ROOT
    jobs: list  # list[JobSpec]
    conda_env: str = DEFAULT_CONDA_ENV
    request_cpus: int = 1
    request_memory_mb: int = 4000
    request_disk_kb: int = 4_000_000
    extra_classads: dict = field(default_factory=dict)

    @property
    def run_dir(self) -> Path:
        return REPO_ROOT / "condor" / "run" / self.stage / self.tag

    @property
    def log_dir(self) -> Path:
        return self.run_dir / "logs"


def make_tag(prefix: str) -> str:
    return f"{prefix}-{datetime.datetime.now():%Y%m%d-%H%M%S}"


def write_wrapper_script(plan: SubmissionPlan) -> Path:
    """Write the bash wrapper HTCondor executes. Its only job is environment
    bootstrap (LCG view + conda env + PYTHONPATH), mirroring utils/setup_root.sh
    and run.sh's `check_env`/PYTHONPATH export — then it execs the target
    python entry point with condor's per-job --arguments. All job-spec / fan-out
    logic lives in Python; this is intentionally the only bash artifact."""
    wrapper = plan.run_dir / "wrapper.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    content = f"""#!/bin/bash
set -eo pipefail
cd {REPO_ROOT}
# NOTE: deliberately does NOT `source utils/setup_root.sh` (the CVMFS LCG view
# setup). The `taukiktflow` conda env is self-contained (ROOT + XRootD
# bindings included, per STATUS.md Phase 1 validation) and sourcing the LCG
# view *before* `conda activate` leaves PYTHONHOME pointed at the LCG
# interpreter while PATH now resolves to conda's python -- a mismatched
# interpreter/home pairing that crashes on startup
# ("Fatal Python error: init_fs_encoding ... No module named 'encodings'").
# Confirmed reproducible while building this wrapper; conda-only activation
# (this block) is the environment run.sh's own SHAPES/PLOT/etc. modes end up
# using in practice (LCG is redundant once TauFakeFactors's `taukiktflow` env
# provides ROOT). If a future stage genuinely needs the LCG view instead of
# this conda env, `unset PYTHONHOME` immediately before `conda activate` here.
source {DEFAULT_CONDA_BASE}/etc/profile.d/conda.sh
conda activate {plan.conda_env}
export PYTHONPATH="{REPO_ROOT}:{REPO_ROOT}/TauFakeFactors:${{PYTHONPATH:-}}"
echo "[wrapper] host=$(hostname) stage={plan.stage} entry_point={plan.entry_point}"
echo "[wrapper] args: $@"
exec python3 {plan.entry_point} "$@"
"""
    wrapper.write_text(content)
    wrapper.chmod(0o755)
    return wrapper


def build_submit_text(plan: SubmissionPlan, wrapper: Path) -> str:
    log_dir = plan.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    classads = {
        "universe": "vanilla",
        "executable": str(wrapper),
        "should_transfer_files": "NO",
        "getenv": "False",
        "notification": "Never",
        "accounting_group": DEFAULT_ACCOUNTING_GROUP,
        "x509userproxy": default_proxy_path(),
        "request_cpus": str(plan.request_cpus),
        "request_memory": str(plan.request_memory_mb),
        "request_disk": str(plan.request_disk_kb),
        "JobBatchName": f"taukitflow-{plan.stage}-{plan.tag}",
        "log": str(log_dir / "$(job_name).log"),
        "output": str(log_dir / "$(job_name).out"),
        "error": str(log_dir / "$(job_name).err"),
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
        print(f"[condor] stage={plan.stage} tag={plan.tag}: no jobs to submit, skipping.")
        return 0

    wrapper = write_wrapper_script(plan)
    submit_file = write_submit_file(plan, wrapper)
    print(f"[condor] stage={plan.stage} tag={plan.tag} jobs={len(plan.jobs)}")
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
