from __future__ import annotations

import datetime
import importlib
import json
import re
import shlex
import subprocess
from pathlib import Path

from condor.common import REPO_ROOT, env_block, submit
from workflow import steps as S

RUN_ROOT = S.REPO_ROOT / "condor/run"
MAX_ATTEMPTS = 3
ACTIVE = {1: "queued", 2: "running", 5: "held", 6: "running", 7: "queued"}


def proxy_problem(min_hours=2):
    out = subprocess.run(["voms-proxy-info", "-timeleft"], capture_output=True, text=True)
    left = int(out.stdout.strip() or 0) if out.stdout.strip().isdigit() else 0
    return None if left >= min_hours * 3600 else f"grid proxy has {left // 60} min left (need {min_hours} h): voms-proxy-init -voms cms -valid 192:00"


def build_plan(cfg, step, us):
    """The SubmissionPlan of the given units of a step, built by the step's own submitter, and {unit label: job names}."""
    module = importlib.import_module(f"condor.{step.submitter}")
    extras = cfg["extras"].get(step.name, [])
    plan, names = None, {}
    for u in us:
        part = module.build_plan(module.parse_args([*step.argv(cfg, u), *extras]))
        names[S.label(u)] = [j.name for j in part.jobs]
        if plan is None:
            plan = part
        else:
            plan.jobs += part.jobs
            plan.setups += part.setups
    return plan, names


def local_commands(cfg, step, us):
    """Shell lines running the condor jobs of the given units locally, in the same environment as the condor wrapper."""
    plan, _ = build_plan(cfg, step, us)
    lines = [f"cd {REPO_ROOT}", *env_block(plan).splitlines()]
    for job in plan.jobs:
        args = shlex.split(job.arguments)
        # the condor submission creates the output directories, the scripts do not
        lines += [f"mkdir -p {Path(args[i + 1]).parent}" for i, a in enumerate(args[:-1]) if a == "--output-file"]
        lines.append(f"python3 {plan.entry_point} {job.arguments}")
    return lines


def submit_units(cfg, step, us, dry_run=False):
    """One condor_submit for the given units of a step. Returns {unit label: record}."""
    plan, names = build_plan(cfg, step, us)
    if plan is None or submit(plan, dry_run=dry_run) != 0 or plan.cluster is None:
        return {}
    procs = {j.name: i for i, j in enumerate(plan.jobs)}
    return {lab: {"cluster": plan.cluster, "jobs": [{"name": n, "proc": procs[n]} for n in ns], "run_dir": str(plan.run_dir)} for lab, ns in names.items()}


def new_state(cfg, selected):
    flow_id = f"{datetime.datetime.now():%y%m%d-%H%M%S}"
    return {"id": flow_id, "cfg": cfg, "steps": list(selected), "units": {}}


def save(state):
    """One tracking record per condor run directory, holding the units submitted from it."""
    by_dir = {}
    for step, units in state["units"].items():
        for lab, rec in units.items():
            by_dir.setdefault(rec["run_dir"], {}).setdefault(step, {})[lab] = rec
    for run_dir, units in by_dir.items():
        Path(run_dir, "tauer.json").write_text(json.dumps({**state, "units": units}, indent=1))


def condor_json(cmd):
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    return json.loads(out) if out else []


def poll(state):
    """{(step, unit label): (state, note)} of every tracked unit, from condor_q (running) and condor_history (finished)."""
    records = [(s, lab, r) for s, units in state["units"].items() for lab, r in units.items()]
    clusters = sorted({r["cluster"] for _, _, r in records})
    if not clusters:
        return {}
    attrs = ["-json", "-attributes", "ClusterId,ProcId,JobStatus,HoldReason,ExitCode"]
    queue = {(j["ClusterId"], j["ProcId"]): j for j in condor_json(["condor_q", *map(str, clusters), *attrs])}
    gone = sorted({r["cluster"] for _, _, r in records if any((r["cluster"], job["proc"]) not in queue for job in r["jobs"])})
    history = {(j["ClusterId"], j["ProcId"]): j for c in gone for j in condor_json(["condor_history", str(c), *attrs])}
    result = {}
    for step, lab, rec in records:
        jobs = [(job, queue.get((rec["cluster"], job["proc"])), history.get((rec["cluster"], job["proc"]))) for job in rec["jobs"]]
        held = [q for _, q, _ in jobs if q and q["JobStatus"] == 5]
        active = [ACTIVE.get(q["JobStatus"], "queued") for _, q, _ in jobs if q and q["JobStatus"] != 5]
        failed = [(job, h) for job, q, h in jobs if not q and (not h or h.get("ExitCode", 1) != 0 or h["JobStatus"] != 4)]
        if held:
            result[(step, lab)] = ("held", held[0].get("HoldReason", ""))
        elif active:
            result[(step, lab)] = ("running" if "running" in active else "queued", f"{len(active)}/{len(jobs)} jobs in the queue")
        elif failed:
            job, h = failed[0]
            logs = [Path(rec["run_dir"]) / sub / f"{job['name']}.{sub}" for sub in ("err", "out")]
            lines = [line.strip(" │╭╰─╮╯") for log in logs if log.exists() for line in log.read_text(errors="replace").splitlines()]
            errors = [line for line in lines if re.search(r"\w+(Error|Exception)\b|Traceback|CRITICAL", line) and "Warning" not in line]
            tail = errors[-1] if errors else " | ".join(lines[-2:])
            result[(step, lab)] = ("failed", f"{job['name']}: exit {h.get('ExitCode', '?') if h else 'unknown (left the queue)'}; {tail}")
        else:
            result[(step, lab)] = ("exited", "")
    return result


def active_jobs(polled):
    return {key: val for key, val in polled.items() if val[0] in ("queued", "running", "held")}


def release_or_remove(verb, state, step, lab):
    rec = state["units"][step][lab]
    ids = [f"{rec['cluster']}.{job['proc']}" for job in rec["jobs"]]
    return subprocess.run([f"condor_{verb}", *ids]).returncode

