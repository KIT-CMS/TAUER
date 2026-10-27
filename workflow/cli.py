from __future__ import annotations

import argparse
import contextlib
import filecmp
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
from rich.markup import escape
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
SPECIAL_ANALYSES = ["", "TauES", "TTbarDYWeight", "NjetsControl", "TriggerRegions", "AntiIsoTauSF"]
PROMPTS = {  # key -> (question, default, choices | "friend" | "bool" | None)
    "selection_friend": ("Selection friend tag", "", "friend"), "ff_friend": ("Fake-factor friend tag (skip: ss-os QCD method)", "", "friend"),
    "additional_friends": ("Additional friend tags, e.g. FastMTT (space to select)", "", "friends"),
    "stxs_stage": ("STXS stage", "stage0", STXS_STAGES), "tag": ("Run tag (empty: ntupletag)", "", None),
    "correction_tag": ("Fake-factor correction tag (empty: the one of corrections_<ch>.yaml)", "", None),
    "skip_systematics": ("Skip the systematic variations?", False, "bool"),
    "process_selection": ("Process groups for splitting the shapes jobs, e.g. data,ztt+zl+zj (empty: one job per era/channel)", "", None),
    "special_analysis": ("Special analysis", "", SPECIAL_ANALYSES), "dc_analysis": ("Datacard analysis (categorization scheme)", "stxs_stage0_run3", None),
    "variable": ("Datacard/GoF variable", "m_vis", None), "fitdir": ("FITDIR for Combine", os.environ.get("FITDIR", ""), None),
    "taues_fit_dir": ("TauES fit output directory (empty: <ntupletag>/taues_fit)", "", None),
    "dc_output_dir": ("Datacard output directory (empty: $FITDIR/output_<analysis>)", "", None),
    "model_tag": ("NN model tag, law version <tag>_<channel> (empty: <ntupletag>_<STXS stage>)", "", None),
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
            notes = [] if state in ("running", "queued") else sorted({note for lab, (st, note) in units.items() if st == state and note})
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


def show_plan(cfg, step, us, after):
    """Dry run of a condor step: its jobs by submission wave and unit, checked with condor_submit -dry-run. after: {unit label: steps it waits for}."""
    if not us:
        return
    out = io.StringIO()
    try:
        plan, names = tracker.build_plan(cfg, step, us)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = tracker.submit(plan, dry_run=True)
    except Exception as exc:  # noqa: BLE001
        console.print(f"\n[bold]{step.name}[/] ({step.desc}): [{RED}]plan not built: {escape(str(exc))}[/]")
        return
    args = {j.name: j.arguments for j in plan.jobs}
    check = f"[{LIGHT_GREEN}]condor_submit -dry-run ok[/]" if code == 0 else f"[{RED}]condor_submit -dry-run failed[/]"
    tree = Tree(f"[bold]{step.name}[/] ({step.desc}): {len(plan.jobs)} job(s), {plan.request_cpus} cpu, {plan.request_memory_mb} MB, "
                f"python3 {plan.entry_point}  {check}")
    waves = {}
    for u in us:
        waves.setdefault(tuple(after[S.label(u)]), []).append(S.label(u))
    for wave, labels in waves.items():
        branch = tree.add(f"[{TEAL}]now[/]" if not wave else f"[{LIGHT_BLUE}]after {', '.join(wave)}[/] (automatic only if every submission is approved)")
        for lab in labels:
            unit = branch.add(f"[bold]{escape(lab)}[/]")
            for name in names[lab]:
                unit.add(f"{escape(name)}  [{GREY}]{escape(args[name])}[/]")
    console.print()
    console.print(tree)
    if code != 0:
        console.print(escape(out.getvalue().strip()), style=RED)


def handoff(step, copies, confirm, dry_run):
    """Copy the TAUER outputs into the CROWN payloads or the /web gallery, after one confirmation per step."""
    # units can share a file (the era-level index.php), identical ones are skipped
    copies = [(src, dst) for src, dst in dict.fromkeys(copies) if not Path(dst).exists() or not filecmp.cmp(src, dst, shallow=False)]
    if not copies:
        return
    replaced = sum(Path(dst).exists() for _, dst in copies)
    console.print(f"\n[bold]{step.name}[/] ({step.desc}): {len(copies)} file(s) into {os.path.commonpath([dst for _, dst in copies])}")
    groups = {}  # one line per destination directory, a single file shown in full
    for src, dst in copies:
        groups.setdefault(os.path.dirname(dst), []).append((src, dst))
    for dst_dir, files in groups.items():
        n_replaced = sum(Path(dst).exists() for _, dst in files)
        line = (f"{files[0][0]} -> {files[0][1]}" if len(files) == 1 else
                f"{dst_dir}/: {len(files)} files from {', '.join(dict.fromkeys(os.path.dirname(src) + '/' for src, _ in files))}")
        console.print(f"  {line}" + (f"  ({n_replaced} replace different ones)" if n_replaced else ""), markup=False, soft_wrap=True)
    if dry_run or not confirm(f"{step.name}: copy {len(copies) - replaced} new file(s)" + (f" and overwrite {replaced} different existing one(s)" if replaced else "") + "?"):
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
            if not dry_run and S.label(u) in tracked and result.get(name, {}).get(S.label(u), ("",))[0] == "done":
                status.record_stamp(cfg, S.BY_NAME[name], u)
    submitted = set()
    for step in (s for s in S.STEPS if s.name in result):  # also the missing steps the selected ones need
        todo = ("missing", "partial") if step.where == "condor" else ("missing", "partial", "manual", "unknown")
        # CROWN commands are printed for every unit not done yet, also when they wait for another CROWN step
        # units on top of upstream ones submitted (or held back) in this pass wait for them, also transitively
        held = {S.label(u) for u in S.units(cfg, step)
                if any((n, S.label(v)) in submitted for n in status.need_names(cfg, step) for v in S.units(cfg, S.BY_NAME[n]) if status.related(cfg, u, v))}
        submitted |= {(step.name, lab) for lab in held}
        ready = [u for u in S.units(cfg, step) if (result[step.name][S.label(u)][0] != "done" if step.where == "crown" else result[step.name][S.label(u)][0] in todo)
                 and S.label(u) not in held]
        redo = [u for u in S.units(cfg, step) if step.where == "condor" and result[step.name][S.label(u)][0] == "other-options" and S.label(u) not in held]
        if redo and (dry_run or confirm(f"condor_submit {step.name} again: {len(redo)} unit(s) done with different options "
                                        f"({result[step.name][S.label(redo[0])][1]})?")):
            ready += redo
        if dry_run and step.where == "condor":
            # the units an approved session submits later, once what they need is done
            ready += [u for u in S.units(cfg, step) if S.label(u) in held or result[step.name][S.label(u)][0] == "waiting"]
            show_plan(cfg, step, ready, {S.label(u): sorted({n for n in status.need_names(cfg, step) for v in S.units(cfg, S.BY_NAME[n])
                                                             if (n, S.label(v)) in submitted and status.related(cfg, u, v)}) for u in ready})
            submitted |= {(step.name, S.label(u)) for u in ready}
            continue
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
        capped =[S.label(u) for u in ready if tracked.get(S.label(u), {}).get("attempts", 0) >= tracker.MAX_ATTEMPTS]
        ready = [u for u in ready if S.label(u) not in capped]
        if confirm is auto_confirm:  # a condor_rm stops the automatic resubmission, `tauer status` still offers it
            ready = [u for u in ready if "removed (condor_rm)" not in polled.get((step.name, S.label(u)), ("", ""))[1]]
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
        submitted |= {(step.name, S.label(u)) for u in ready}
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
    from common.analysis import _VARIABLES_YAML, DATA_ERA_MERGE, RUN3_ERAS, SUPPORTED_ERAS, _load_variables, get_channels, get_mc_ntuple_era, get_output_features

    selected = ask(questionary.checkbox("Steps", choices=[questionary.Choice(f"{s.name:24} {s.desc} [{s.where}]", s.name, checked=s.name in last.get("steps", []))
                                                          for s in sorted(S.STEPS, key=lambda s: MENU_GROUPS.index(s.group))], style=custom_style, validate=bool))
    crown_only = all(S.BY_NAME[n].where == "crown" for n in selected)
    if not crown_only:
        # an analysis era and the eras whose data is merged into it are one choice, e.g. 2025+2026
        merged = {e: [e, *DATA_ERA_MERGE.get(e, ())] for e in SUPPORTED_ERAS if not any(e in m for m in DATA_ERA_MERGE.values())}
        alone = {e: [e] for m in DATA_ERA_MERGE.values() for e in m}  # its own data only, with the MC of MC_NTUPLE_ERA_OVERRIDE scaled to its lumi
        picked = ask(questionary.checkbox("Eras", choices=[questionary.Choice("+".join(group), e, checked=e in last.get("eras", RUN3_ERAS)) for e, group in merged.items()]
                                          + [questionary.Choice(f"{e} alone ({get_mc_ntuple_era(e)} MC)", e, checked=False) for e in alone],
                                          style=custom_style, validate=bool))
        eras = list(dict.fromkeys(x for e in picked for x in {**merged, **alone}[e]))
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
        elif choices == "bool":
            params[key] = ask(questionary.confirm(question, default=bool(default), style=custom_style))
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
    if {"shapes", "plot"} & set(selected):
        from common.binning import control_binning
        unbinned = lambda t: [v for v in t.replace(" ", "").split(",") if v and v not in control_binning["mt"]]
        new = [v for v in dict.fromkeys(ask(questionary.text("Variables to add to common/variables.yaml output_features, comma-separated (empty: none)", style=custom_style,
                                                             validate=lambda t: not unbinned(t) or f"no control binning in common/binning.py: {', '.join(unbinned(t))}"))
                                        .replace(" ", "").split(",")) if v and v not in get_output_features()]
        if new and ask(questionary.confirm(f"Add {', '.join(new)} to {_VARIABLES_YAML}? (shapes must be rerun to book them)", default=False, style=custom_style)):
            head, sep, tail = _VARIABLES_YAML.read_text().partition("\nselection_masks:")
            _VARIABLES_YAML.write_text(head.rstrip("\n") + "".join(f"\n  - {v}" for v in new) + "\n" + sep + tail)
            _load_variables.cache_clear()
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
    if not any(S.BY_NAME[name].where == "condor" and state in ("missing", "partial", "other-options") for name in result for state, _ in result[name].values()):
        # nothing for condor: print the local/CROWN commands and ask directly about the payload copies
        advance(tracker.new_state(cfg, selected), lambda msg: ask(questionary.confirm(msg, default=False, style=custom_style)))
        return 0
    if ask(questionary.confirm("Dry run first (nothing is written or saved)?", default=False, style=custom_style)):
        advance(tracker.new_state(cfg, selected), lambda msg: False, dry_run=True)
        if not ask(questionary.confirm("Submit these now?", default=False, style=custom_style)):
            return 0
    state = tracker.new_state(cfg, selected)
    state["auto"] = ask(questionary.confirm("Approve now every condor submission of these steps?",
                                            default=False, style=custom_style))
    advance(state, auto_confirm if state["auto"] else lambda msg: ask(questionary.confirm(msg, default=False, style=custom_style)))
    if not any(state["units"].values()):
        console.print("Nothing submitted: every selected unit is done or waits for a step that is not.")
        return 0
    tracker.save(state)
    console.print("\nWatching every job submitted through tauer (Ctrl+C stops watching, the jobs keep running; later: `tauer status --watch`, `tauer status`)")
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
    for state in states:  # sessions saved before a key was added get its default
        state["cfg"] = S.finalize(state["cfg"])
    return states


def cmd_status(args):
    """Tree of each session, then asks about held jobs, resubmitting failed ones and submitting the steps that became ready; --watch loops without asking."""
    if args.watch:
        return watch(read_states(args.id), args.watch)
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


def auto_confirm(msg):
    """Pre-approved sessions: condor submissions and the /web plot copies go through, payload copies into CROWN still wait for `tauer status`."""
    return msg.startswith(("condor_submit", "plot-web:"))


def watch(states, interval):
    """Show the sessions with jobs in the queue until none is left; submits the ready condor steps of the sessions approved at the start."""
    try:
        while True:
            trees, waiting = [], []
            for state in states:
                if state.get("auto"):
                    with console.capture():  # the screen is redrawn below
                        result = advance(state, auto_confirm, show=False)
                    waiting += [f"{name} [{S.BY_NAME[name].where}]" for name, units in result.items() if S.BY_NAME[name].where in ("local", "crown", "handoff")
                                and any(st in ("missing", "partial", "manual", "unknown") for st, _ in units.values())]
                jobs = tracker.active_jobs(tracker.poll(state))
                if jobs:
                    trees.append(render(state["cfg"], state["steps"], status.resolve(state["cfg"], state["steps"], jobs)))
            console.clear()
            console.print(f"{time.strftime('%H:%M')}  tauer status --watch (every {interval:g} min, Ctrl+C to stop; the jobs keep running)")
            console.print(Group(*trees) if trees else "No tauer jobs in the queue.")
            if waiting:
                console.print(f"[{AMBER}]not run by tauer, `tauer status` prints/copies them: {', '.join(dict.fromkeys(waiting))}[/]")
            if any(st.get("auto") for st in states) and (problem := tracker.proxy_problem()):
                console.print(f"[{RED}]{problem}: nothing new is submitted[/]")
            if not trees:
                break
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        return 0
    console.print("All tauer jobs left the queue: run `tauer status` to resubmit failed jobs and submit the steps that became ready.")
    return 0


def cmd_clean(args):
    """Asks for each session whether to drop its tauer.json files: status/watch stop showing it, the condor run directories and jobs are kept."""
    sessions = {}
    for path in sorted(REPO_ROOT.glob("condor/run/**/tauer.json")):
        record = json.loads(path.read_text())
        sessions.setdefault(record["id"], []).append((path, record))
    if not sessions:
        console.print("No tauer sessions to clean.")
    for fid, records in sorted(sessions.items()):
        steps = dict.fromkeys(step for _, record in records for step in record["units"])
        if ask(questionary.confirm(f"Clean session {fid} ({records[0][1]['cfg']['ntupletag']}: {', '.join(steps)}; {len(records)} submissions)?",
                                   default=False, style=custom_style)):
            for path, _ in records:
                path.unlink()
    return 0


def cmd_setup(args):
    load_modules(os.environ.get("TAUER_ANALYSIS", "smhtt"))
    setup(force=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tauer", description="Guided TAUER workflow: plan, check, submit and track the steps of an analysis.")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("status", help="status of the jobs submitted through tauer (all sessions, or one id); asks before resubmitting failed jobs, handling held ones and submitting the steps that became ready")
    p.add_argument("id", nargs="?")
    p.add_argument("--watch", nargs="?", type=float, const=5, default=None, metavar="MIN",
                   help="redraw every MIN minutes (default 5) until no job is left, without asking: only the sessions approved at the start get their ready condor steps submitted")
    p = sub.add_parser("watch", help="alias of `status --watch`")
    p.add_argument("id", nargs="?")
    p.add_argument("--interval", dest="watch", type=float, default=5, help="minutes between polls (default: 5)")
    sub.add_parser("clean", help="asks for each tauer session whether to stop tracking it (its condor run directories and jobs are kept)")
    p = sub.add_parser("setup", help="where the CROWN analysis configuration (and its payloads/) is")
    args = parser.parse_args(argv)
    return {None: lambda a: interactive(), "status": cmd_status, "watch": cmd_status, "clean": cmd_clean, "setup": cmd_setup}[args.cmd](args)
