from __future__ import annotations

import argparse
import contextlib
import getpass
import importlib
import io
import json
import os
import shlex
import shutil
import time
from collections import Counter
from pathlib import Path

import questionary
from questionary import Style
from common.sample_paths import crown_ntuple_base
from rich.console import Console, Group
from rich.tree import Tree

REPO_ROOT = Path(__file__).resolve().parent.parent
LAST_INPUTS = Path.home() / ".config/tauer/last_inputs.json"  # answers of the previous `tauer` session, used as defaults
console = Console(highlight=False)
# TAUER logo teal plus dark blue, light green and light blue: mid tones, readable on black and on white terminals
TEAL, DARK_BLUE, LIGHT_GREEN, LIGHT_BLUE, RED, AMBER, GREY = "#2a9d7f", "#3b6fd4", "#4caf3f", "#3a9be0", "#e0443e", "#c98b00", "#8a9a96"
custom_style = Style([
    ("qmark", f"fg:{TEAL} bold"), ("question", "bold"), ("answer", f"fg:{DARK_BLUE} bold"), ("pointer", f"fg:{TEAL} bold"),
    ("highlighted", f"fg:{TEAL} bold"), ("selected", f"fg:{LIGHT_GREEN}"), ("separator", f"fg:{LIGHT_BLUE}"), ("instruction", f"fg:{GREY}"),
    ("text", ""), ("disabled", f"fg:{GREY} italic"),
])
COLORS = {"done": LIGHT_GREEN, "missing": RED, "partial": AMBER, "stale": AMBER, "other-options": AMBER, "waiting": LIGHT_BLUE,
          "blocked": DARK_BLUE, "unknown": GREY, "manual": GREY, "queued": LIGHT_BLUE, "running": TEAL, "held": f"bold {RED}", "failed": f"bold {RED}"}
STXS_STAGES = ["stage0", "stage1p2"]
SPECIAL_ANALYSES = ["", "TauES", "TTbarDYWeight", "NjetsControl"]
PROMPTS = {  # key -> (question, default, choices | "friend" | None)
    "selection_friend": ("Selection friend tag", "", "friend"), "ff_friend": ("Fake-factor friend tag (skip: ss-os QCD method)", "", "friend"),
    "additional_friends": ("Additional friend tags, e.g. FastMTT (space to select)", "", "friends"),
    "stxs_stage": ("STXS stage", "stage0", STXS_STAGES), "tag": ("Run tag (empty: ntupletag)", "", None),
    "correction_tag": ("FF correction tag (empty: the one of corrections_<ch>.yaml)", "", None),
    "process_selection": ("Process groups for splitting the shapes jobs, e.g. data,ztt+zl+zj (empty: one job per era/channel)", "", None),
    "special_analysis": ("Special analysis", "", SPECIAL_ANALYSES), "dc_analysis": ("Datacard analysis (categorization scheme)", "stxs_stage0_run3", None),
    "variable": ("Datacard/GoF variable", "m_vis", None), "fitdir": ("FITDIR for Combine", os.environ.get("FITDIR", ""), None),
    "taues_fit_dir": ("TauES fit output directory (empty: <ntupletag>/taues_fit)", "", None),
    "plot_variables": ("Plot variables", "m_vis,pt_1,pt_2,eta_1,eta_2,mt_1", None), "dc_output_dir": ("Datacard output directory (empty: $FITDIR/output_<analysis>)", "", None),
    "train_task": ("Law training task", None, "train_tasks"), "request_gpus": ("GPUs per training job", "1", None), "sample_list": ("KingMaker sample list", None, "samples"),
}
S = status = tracker = None

# menu order: payloads for CROWN first, then the shapes-to-fit chain, CROWN steps last
MENU_GROUPS = ["btag", "ff", "nn", "train", "shapes", "estimations", "plot", "datacards", "taues", "crown"]


def load_modules(analysis):
    """TAUER_ANALYSIS is read when common.analysis is first imported, so it is set before anything else of TAUER."""
    global S, status, tracker
    os.environ["TAUER_ANALYSIS"] = analysis
    S, status, tracker = (importlib.import_module(f"workflow.{m}") for m in ("steps", "status", "tracker"))


def ask(prompt):
    answer = prompt.ask()
    if answer is None:
        raise SystemExit(1)
    return answer


def invalid_extras(cfg, selected, args):
    """argparse error of the first selected condor step whose submitter rejects the extra options, None if all accept them."""
    for step in (S.BY_NAME[n] for n in selected if S.BY_NAME[n].where == "condor"):
        us = S.units(cfg, step)
        if not us:
            continue
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                importlib.import_module(f"condor.{step.submitter}").parse_args([*step.argv(cfg, us[0]), *args])
        except SystemExit:
            return f"{step.name}: {err.getvalue().strip().splitlines()[-1]}"
    return None


def render(cfg, selected, result):
    tree = Tree(f"[bold {TEAL}]{cfg['ntupletag']}[/] analysis={cfg['analysis']} eras={','.join(cfg['eras'])} channels={','.join(cfg['channels'])}")
    for name, units in result.items():
        step = S.BY_NAME[name]
        counts = Counter(state for state, _ in units.values())
        head = f"{name} [{step.where}] " + ", ".join(f"[{COLORS.get(k, 'white')}]{n} {k}[/]" for k, n in counts.items())
        branch = tree.add(head if name in selected else f"[dim]{head} (needed)[/]")
        for state in (k for k in counts if k != "done"):
            labels = [lab for lab, (st, _) in units.items() if st == state]
            notes = [] if step.where == "crown" or state in ("running", "queued") else sorted({note for lab, (st, note) in units.items() if st == state and note})
            shown = f"all {len(labels)}" if len(labels) == len(units) > 1 else ", ".join(labels)
            branch.add(f"[{COLORS.get(state, 'white')}]{state}[/]: {shown}" + (f"  ({'; '.join(notes[:2])})" if notes else ""))
    return tree


def print_commands(cfg, step, us):
    extras = shlex.join(cfg["extras"].get(step.name, []))
    lines = [f"{line} {extras}".strip() if line.startswith(("python", "law")) else line for line in step.command(cfg, us)]
    if step.env in S.ENV_LINES:
        lines = [S.ENV_LINES[step.env], f"export TAUER_ANALYSIS={cfg['analysis']}", f"cd {S.REPO_ROOT}", *lines]
    console.print(f"\n[bold]{step.name}[/] ({step.desc}): not run by tauer, copy and run", markup=True)
    for line in lines:
        console.print("  " + line, markup=False, soft_wrap=True)


def handoff(step, copies, confirm, dry_run):
    """Copy the TAUER outputs into the CROWN payloads, after one confirmation per step."""
    if not copies:
        return
    console.print(f"\n[bold]{step.name}[/] ({step.desc}): {len(copies)} file(s) into {S.crown_analysis_dir()}/payloads")
    for src, dst in copies:
        console.print(f"  {src} -> {dst}", markup=False, soft_wrap=True)
    if dry_run or not confirm(f"Copy these {len(copies)} payload file(s), overwriting the CROWN ones?"):
        return
    for src, dst in copies:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    console.print(f"[{LIGHT_GREEN}]copied {len(copies)} file(s)[/]")


def setup(force=False):
    """Asks once where the CROWN analysis configuration is: payloads are copied there, the KingMaker commands run next to it."""
    current = S.settings()
    if "crown_analysis_dir" in current and not force:
        return
    path = ask(questionary.path("Where is KingMaker/CROWN/analysis_configurations/<CROWN analysis>?", default=str(S.crown_analysis_dir()), only_directories=True,
                                validate=lambda v: (Path(v).expanduser() / "payloads").is_dir() or "no payloads/ directory there", style=custom_style))
    S.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    S.SETTINGS.write_text(json.dumps({**current, "crown_analysis_dir": str(Path(path).expanduser().resolve())}, indent=1))
    console.print(f"Saved in {S.SETTINGS} (change it with `tauer setup`)")


def advance(state, confirm, dry_run=False, show=True):
    """Submit the condor units that are ready, print the commands of the local/CROWN ones. confirm(msg) -> bool."""
    cfg, selected = state["cfg"], state["steps"]
    polled = tracker.poll(state)
    result = status.resolve(cfg, selected, tracker.active_jobs(polled))
    for name, tracked in state["units"].items():
        for u in S.units(cfg, S.BY_NAME[name]):
            if not dry_run and S.label(u) in tracked and result[name][S.label(u)][0] == "done":
                status.record_stamp(cfg, S.BY_NAME[name], u)
    for step in (s for s in S.STEPS if s.name in result):  # also the missing steps the selected ones need
        todo = ("missing", "partial") if step.where == "condor" else ("missing", "partial", "manual", "unknown")
        # CROWN commands are printed for every unit not done yet, also when they wait for another CROWN step
        ready = [u for u in S.units(cfg, step) if (result[step.name][S.label(u)][0] != "done" if step.where == "crown" else result[step.name][S.label(u)][0] in todo)]
        if not ready:
            continue
        if step.where == "handoff":
            handoff(step, step.command(cfg, ready), confirm, dry_run)
            continue
        if step.where != "condor":
            if show:
                print_commands(cfg, step, ready)
            continue
        tracked = state["units"].get(step.name, {})
        capped = [S.label(u) for u in ready if tracked.get(S.label(u), {}).get("attempts", 0) >= tracker.MAX_ATTEMPTS]
        ready = [u for u in ready if S.label(u) not in capped]
        if capped and show:
            console.print(f"[{RED}]{step.name}: {', '.join(capped)} failed {tracker.MAX_ATTEMPTS} times, not resubmitted[/]")
        if not ready or (problem := tracker.proxy_problem()) and not dry_run and console.print(f"[{RED}]{problem}[/]") is None:
            continue
        if not dry_run and not confirm(f"condor_submit {step.name}: {len(ready)} unit(s) ({', '.join(S.label(u) for u in ready[:6])}{', ...' if len(ready) > 6 else ''})?"):
            console.print(f"\n[bold]{step.name}[/] ({step.desc}): not submitted, to run it locally instead")
            for line in tracker.local_commands(cfg, step, ready):
                console.print("  " + line, markup=False, soft_wrap=True)
            continue
        records = tracker.submit_units(cfg, step, ready, dry_run=dry_run)
        if not dry_run:
            for lab, rec in records.items():
                tracked[lab] = {**rec, "attempts": tracked.get(lab, {}).get("attempts", 0) + 1}
            state["units"][step.name] = tracked
            tracker.save(state)
    if not dry_run and any(state["units"].values()):
        tracker.save(state)
    return result


def handle_held(state, polled):
    for (step, lab), (job_state, note) in polled.items():
        if job_state != "held":
            continue
        console.print(f"[bold {RED}]{step} {lab} is held:[/] {note}")
        action = ask(questionary.select("Held job", choices=["leave it", "condor_release", "condor_rm"], style=custom_style))
        if action != "leave it" and ask(questionary.confirm(f"{action} {step} {lab}?", default=False, style=custom_style)):
            if action == "condor_release" and (problem := tracker.proxy_problem()):
                console.print(f"[{RED}]{problem}[/]")
            else:
                tracker.release_or_remove(action.split("_")[1], state, step, lab)


def show_tracking(state, polled):
    current = {(name, S.label(u)) for name in state["units"] for u in S.units(state["cfg"], S.BY_NAME[name])}
    for (step, lab), (job_state, note) in ((k, v) for k, v in polled.items() if v[0] in ("held", "failed") and k in current):
        attempts = state["units"][step][lab]["attempts"]
        console.print(f"  {step} {lab}: [{COLORS.get(job_state, 'white')}]{job_state}[/] (attempt {attempts}) {note}")


def pick_tag(message, tags, default, required=True):
    """Select one of the tags on the dCache or type a new one; optional tags are a checkbox where ticking nothing skips them."""
    new = "<type a new tag>"
    if required:
        answer = ask(questionary.select(message, choices=[*sorted(tags), new], default=default if default in tags else None, style=custom_style))
    else:
        picked = ask(questionary.checkbox(message + " (space to tick one, enter alone to skip)", choices=[questionary.Choice(t, checked=t == default) for t in sorted(tags)] + [new],
                                          validate=lambda v: len(v) <= 1 or "tick at most one", style=custom_style))
        answer = picked[0] if picked else ""
    if answer == new:
        answer = ask(questionary.text(message + ("" if required else " (empty: skip)"), default="" if default in tags else default, style=custom_style,
                                      validate=lambda v: bool(v.strip()) or not required or "a tag is needed")).strip()
    return answer


def friend_tags(cfg):
    return sorted(t for t in status.xrd_ls(f"{crown_ntuple_base(cfg['ntupletag'], user=cfg['user'])}/CROWNFriend") or [] if t != "job_tarball")


def interactive():
    try:
        last = json.loads(LAST_INPUTS.read_text())
    except (OSError, ValueError):
        last = {}
    analyses = sorted(p.name for p in (REPO_ROOT / "analyses").iterdir() if p.is_dir() and not p.name.startswith("__"))
    analysis = ask(questionary.select("Analysis", choices=analyses, default=last.get("analysis") if last.get("analysis") in analyses else os.environ.get("TAUER_ANALYSIS", "smhtt"), style=custom_style))
    load_modules(analysis)
    setup()
    from common.analysis import DATA_ERA_MERGE, RUN3_ERAS, SUPPORTED_ERAS, get_channels

    selected = ask(questionary.checkbox("Steps", choices=[questionary.Choice(f"{s.name:24} {s.desc} [{s.where}]", s.name, checked=s.name in last.get("steps", []))
                                                          for s in sorted(S.STEPS, key=lambda s: MENU_GROUPS.index(s.group))], style=custom_style, validate=bool))
    crown_only = all(S.BY_NAME[n].where == "crown" for n in selected)
    if not crown_only:
        # an analysis era and the eras whose data is merged into it are one choice, e.g. 2025+2026
        merged = {e: [e, *DATA_ERA_MERGE.get(e, ())] for e in SUPPORTED_ERAS if not any(e in m for m in DATA_ERA_MERGE.values())}
        picked = ask(questionary.checkbox("Eras", choices=[questionary.Choice("+".join(group), e, checked=e in last.get("eras", RUN3_ERAS)) for e, group in merged.items()],
                                          style=custom_style, validate=bool))
        eras = [x for e in picked for x in merged[e]]
    channels = ask(questionary.checkbox("Channels", choices=[questionary.Choice(c, checked=c in last.get("channels", get_channels())) for c in get_channels()], style=custom_style, validate=bool))
    ntupletag = pick_tag("Ntuple tag", status.xrd_ls(crown_ntuple_base("", user=getpass.getuser()).rstrip("/")) or [], last.get("ntupletag", ""))
    if crown_only:
        # the eras of a production come from its sample list: check the ones on the dCache, all if it does not exist yet
        on_disk = status.xrd_ls(f"{crown_ntuple_base(ntupletag, user=getpass.getuser())}/CROWNRun") or []
        eras = [e for e in SUPPORTED_ERAS if e in on_disk] or list(RUN3_ERAS)
    cfg = {"analysis": analysis, "eras": eras, "channels": channels, "ntupletag": ntupletag, "user": getpass.getuser()}
    params = {}
    for key in dict.fromkeys(k for name in selected for k in S.BY_NAME[name].params):
        question, default, choices = PROMPTS[key]
        default = last.get("params", {}).get(key, default)
        if choices == "friend":
            params[key] = pick_tag(question, friend_tags(cfg), default or "", required=key != "ff_friend")
        elif choices == "friends":
            others = [t for t in friend_tags(cfg) if t not in (params.get("selection_friend"), params.get("ff_friend"))]
            params[key] = ",".join(ask(questionary.checkbox(question, choices=[questionary.Choice(t, checked=t in (default or "").split(",")) for t in others], style=custom_style))
                                   if others else ask(questionary.text(question + ", comma-separated", default=default or "", style=custom_style)).split(","))
        elif choices == "train_tasks":
            params[key] = ask(questionary.select(question, choices=list(S.TRAIN_TASKS), default=default if default in S.TRAIN_TASKS else None, style=custom_style))
        elif choices == "samples":
            lists, other = [str(p) for p in sorted(S.kingmaker_dir().glob("samples*.txt"), key=os.path.getmtime, reverse=True)], "<type a path>"
            params[key] = ask(questionary.select(question, choices=[*lists, other], default=default if default in lists else None, style=custom_style))
            if params[key] == other:
                params[key] = ask(questionary.path(question, default="" if default in lists else default or "", style=custom_style,
                                                   validate=lambda v: os.path.isfile(os.path.expanduser(v)) or "not a file")).strip()
        elif choices:
            params[key] = ask(questionary.select(question, choices=choices, default=default if default in choices else None, style=custom_style))
        else:
            params[key] = ask(questionary.text(question, default=default or "", style=custom_style)).strip()
    cfg.update(params)
    # params are merged so answers to prompts not asked this time are kept for the next session
    LAST_INPUTS.parent.mkdir(parents=True, exist_ok=True)
    LAST_INPUTS.write_text(json.dumps({"analysis": analysis, "steps": selected, "eras": last.get("eras", eras) if crown_only else eras, "channels": channels, "ntupletag": ntupletag,
                                       "params": {**last.get("params", {}), **params}}, indent=1))
    cfg = S.finalize(cfg)
    while not crown_only:
        try:
            args = shlex.split(ask(questionary.text("Extra options added to the commands of the selected steps (empty: none)", style=custom_style)))
        except ValueError as exc:
            console.print(f"[{RED}]{exc}[/]")
            continue
        if not (problem := invalid_extras(cfg, selected, args)):
            cfg["extras"] = {name: args for name in selected} if args else {}
            break
        console.print(f"[{RED}]{problem}[/]")
    result = status.resolve(cfg, selected)
    console.print(render(cfg, selected, result))
    if not any(S.BY_NAME[name].where == "condor" for name in result):
        advance(tracker.new_state(cfg, selected), lambda msg: False, dry_run=True)
        return 0
    if ask(questionary.confirm("Dry run only (condor_submit -dry-run, nothing is written or saved)?", default=False, style=custom_style)):
        advance(tracker.new_state(cfg, selected), lambda msg: False, dry_run=True)
        return 0
    state = tracker.new_state(cfg, selected)
    advance(state, lambda msg: ask(questionary.confirm(msg, default=False, style=custom_style)))
    if not any(state["units"].values()):
        return 0
    tracker.save(state)
    console.print("\nWatching every job submitted through tauer (Ctrl+C stops watching, the jobs keep running; later: `tauer watch`, `tauer status`)")
    return watch(read_states(None), interval=5)


def read_states(flow_id):
    """The tauer session `flow_id`, or every session with jobs submitted through tauer."""
    sessions = {}
    for path in sorted(REPO_ROOT.glob("condor/run/**/tauer.json")):  # written by tracker.save next to each submit.sub
        record = json.loads(path.read_text())
        state = sessions.setdefault(record["id"], {**record, "units": {}})
        for step, units in record["units"].items():
            for lab, rec in units.items():  # of a resubmitted unit, the latest attempt
                if rec["attempts"] >= state["units"].setdefault(step, {}).get(lab, {}).get("attempts", 0):
                    state["units"][step][lab] = rec
    states = [st for fid, st in sorted(sessions.items()) if flow_id in (None, fid)]
    if not states:
        raise SystemExit(f"No jobs submitted through tauer{' with id ' + flow_id if flow_id else ''} under {REPO_ROOT}/condor/run: start with `tauer`.")
    load_modules(states[0]["cfg"]["analysis"])
    return states


def cmd_status(args):
    """Tree of each session, then asks about held jobs, resubmitting failed ones and submitting the steps that became ready."""
    states = [st for st in read_states(args.id) if args.id or st["units"]]
    for state in states:
        console.print(f"\n[bold]session {state['id']}[/] ({state['cfg']['ntupletag']}: {', '.join(state['steps'])})")
        polled = tracker.poll(state)
        console.print(render(state["cfg"], state["steps"], status.resolve(state["cfg"], state["steps"], tracker.active_jobs(polled))))
        show_tracking(state, polled)
        handle_held(state, polled)
        advance(state, lambda msg: ask(questionary.confirm(msg, default=False, style=custom_style)))
    if not states:
        console.print("No jobs submitted through tauer yet: start with `tauer`.")
    return 0


def watch(states, interval):
    """Show the sessions with jobs in the queue until none is left; never submits anything."""
    try:
        while True:
            trees = []
            for state in states:
                jobs = tracker.active_jobs(tracker.poll(state))
                if jobs:
                    trees.append(render(state["cfg"], state["steps"], status.resolve(state["cfg"], state["steps"], jobs)))
            console.clear()
            console.print(f"{time.strftime('%H:%M')}  tauer watch (every {interval:g} min, Ctrl+C to stop; the jobs keep running)")
            console.print(Group(*trees) if trees else "No tauer jobs in the queue.")
            if not trees:
                break
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        return 0
    console.print("All tauer jobs left the queue: run `tauer status` to resubmit failed jobs and submit the steps that became ready.")
    return 0


def cmd_watch(args):
    return watch(read_states(args.id), args.interval)


def cmd_setup(args):
    load_modules(os.environ.get("TAUER_ANALYSIS", "smhtt"))
    setup(force=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tauer", description="Guided TAUER workflow: plan, check, submit and track the steps of an analysis.")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("status", help="status of the jobs submitted through tauer (all sessions, or one id); asks before resubmitting failed jobs, handling held ones and submitting the steps that became ready")
    p.add_argument("id", nargs="?")
    p = sub.add_parser("watch", help="show the jobs submitted through tauer until they leave the queue (all sessions, or one id); never submits")
    p.add_argument("id", nargs="?")
    p.add_argument("--interval", type=float, default=5, help="minutes between polls (default: 5)")
    p = sub.add_parser("setup", help="where the CROWN analysis configuration (and its payloads/) is")
    args = parser.parse_args(argv)
    return {None: lambda a: interactive(), "status": cmd_status, "watch": cmd_watch, "setup": cmd_setup}[args.cmd](args)
