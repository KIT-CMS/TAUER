from __future__ import annotations

import filecmp
import glob
import hashlib
import json
import os
import subprocess
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.sample_paths import XROOTD_REDIRECTOR, crown_ntuple_base
from common.shapes_merge import _ff_only_parts, find_parts, missing_processes, read_expected_processes, ss_os_sibling
from common.analysis import ff_config_era, get_mc_ntuple_era, get_samples
from workflow import steps as S

REPO_ROOT = S.REPO_ROOT
DONE_LIKE = ("done", "other-options", "stale", "unknown", "manual")
FRIEND_PARAMS = ("selection_friend", "additional_friends", "ff_friend")
_PROBES: dict[str, dict] = {}
_XRD: dict[str, list | None] = {}


def nonempty(path):
    return os.path.getsize(path) > 0 if os.path.isfile(path) else os.path.isdir(path) and bool(os.listdir(path))


def matches(pattern):
    return [m for m in glob.glob(pattern, recursive=True) if nonempty(m)]


def newest(paths):
    return max((os.path.getmtime(p) for p in paths), default=None)


def probe_root(paths):
    """Open the shapes files in one ROOT subprocess: processes missing vs expected_processes.json, and the estimation histograms."""
    todo = [str(p) for p in paths if str(p) not in _PROBES and Path(p).exists()]
    if todo:
        env = {**os.environ, "PYTHONPATH": f"{REPO_ROOT}:{os.environ.get('PYTHONPATH', '')}"}
        out = subprocess.run([sys.executable, "-m", "workflow.status", "--probe", *todo], cwd=REPO_ROOT, env=env, capture_output=True, text=True)
        try:
            _PROBES.update(json.loads(out.stdout.strip().splitlines()[-1]))
        except (IndexError, ValueError):
            _PROBES.update({p: None for p in todo})


def xrd_ls(path):
    """Directory listing on the GridKA dCache: [] if it does not exist, None if the listing itself failed (no proxy, no XRootD)."""
    if path not in _XRD:
        try:
            from XRootD import client

            # see ntuple_processor/booking.py: silences ROOT's deprecation warning raised by XRootD's exit-time finalizer
            warnings.filterwarnings("ignore", message=r"\s*In ROOT 6\.36, the ROOT\.RDF\.Experimental\.Distributed", category=FutureWarning)
            status, listing = client.FileSystem(XROOTD_REDIRECTOR).dirlist(path)
            _XRD[path] = [e.name for e in listing] if status.ok else ([] if status.errno == 3011 else None)
        except Exception:
            _XRD[path] = None
    return _XRD[path]


def check_crown(cfg, step, us):
    base = crown_ntuple_base(cfg["ntupletag"], user=cfg["user"])
    friend = step.check == "crown-friend"
    ftag = cfg["selection_friend"] if step.name == "crown-selection-friend" else cfg.get("ff_friend")
    results = {}
    with ThreadPoolExecutor(32) as pool:
        for u in us:
            era, ch = u["era"], u["channel"]
            if friend and not ftag:
                results[S.label(u)] = ("missing", "friend tag not given")
                continue
            if xrd_ls(f"{base}/CROWNRun/{era}") is None:
                results[S.label(u)] = ("unknown", "XRootD listing failed (grid proxy?)")
                continue
            # MC of eras without their own campaign lives in get_mc_ntuple_era's directory, data in its own
            dirs = {nick: era if key == "data" else get_mc_ntuple_era(era) for key, ns in get_samples(era, ch).items() for nick in ns}
            nicks = sorted(dirs)
            count = lambda root, nick: len([f for f in xrd_ls(f"{root}/{dirs[nick]}/{nick}/{ch}") or [] if f.endswith(".root")])  # noqa: E731
            runs = dict(zip(nicks, pool.map(lambda n: count(f"{base}/CROWNRun", n), nicks)))
            if friend:
                friends = dict(zip(nicks, pool.map(lambda n: count(f"{base}/CROWNFriend/{ftag}", n), nicks)))
                bad = [n for n in nicks if not runs[n] or friends[n] != runs[n]]
            else:
                bad = [n for n in nicks if not runs[n]]
            ok = len(nicks) - len(bad)
            state = "done" if nicks and not bad else "partial" if ok else "missing"
            results[S.label(u)] = (state, f"{ok}/{len(nicks)} nicks" + (f", first incomplete: {bad[0]}" if bad else ""))
    return results


def check_btag_inputs(cfg, step, us):
    """Opens one MC file of the ntuples per era/channel and looks for the jet columns btag_efficiency.yaml reads."""
    import yaml

    base = crown_ntuple_base(cfg["ntupletag"], user=cfg["user"])
    files, results = {}, {}
    for u in us:
        era, ch = u["era"], u["channel"]
        config = REPO_ROOT / "btag_efficiencies/configs" / era / "btag_efficiency.yaml"
        if not config.exists():
            results[S.label(u)] = ("unknown", f"no {config.relative_to(REPO_ROOT)}")
            continue
        columns = sorted(v for k, v in yaml.safe_load(config.read_text()).items() if k.startswith("jet_") and k.endswith("_column"))
        mc = [n for key, ns in get_samples(era, ch, include_signals=False).items() if key != "data" for n in ns]
        found = next((f"{base}/CROWNRun/{get_mc_ntuple_era(era)}/{n}/{ch}/{f}" for n in mc
                      for f in (xrd_ls(f"{base}/CROWNRun/{get_mc_ntuple_era(era)}/{n}/{ch}") or []) if f.endswith(".root")), None)
        if found is None:
            results[S.label(u)] = ("missing", "no MC ntuples")
        else:
            files[S.label(u)] = (f"{XROOTD_REDIRECTOR}{found}", columns)
    if files:
        out = subprocess.run([sys.executable, "-m", "workflow.status", "--branches", json.dumps(list(files.values()))], cwd=REPO_ROOT,
                             env={**os.environ, "PYTHONPATH": f"{REPO_ROOT}:{os.environ.get('PYTHONPATH', '')}"}, capture_output=True, text=True)
        try:
            missing = json.loads(out.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            missing = [None] * len(files)
        for lab, miss in zip(files, missing):
            results[lab] = (("unknown", "could not open the ntuple") if miss is None else
                            ("missing", f"no {', '.join(miss)} in the ntuples") if miss else ("done", ""))
    return results


def check_handoff(cfg, step, u):
    states = []
    for src, dst in step.outputs(cfg, u):
        found = sorted(matches(src), key=os.path.getmtime)
        if not found:
            return "missing", "TAUER output not found"
        states.append("absent" if not Path(dst).exists() else "ok" if filecmp.cmp(found[-1], dst, shallow=False) else "differs")
    return ("done", "") if set(states) == {"ok"} else ("missing", "payload " + "/".join(sorted(set(states) - {"ok"})))


def shapes_of(cfg, step, u):
    # taues-shapes never uses the FF friend
    return S.shapes_file(cfg, u, "ss-os" if step.name.startswith("taues") else S.qcd_label(cfg))


def check_shapes(cfg, step, u):
    file = shapes_of(cfg, step, u)
    if file.exists():
        miss = (_PROBES.get(str(file)) or {}).get("missing")
        return ("unknown", "ROOT probe failed") if miss is None else ("partial", "missing " + ",".join(miss)) if miss else ("done", "")
    parts = find_parts(file)
    expected = read_expected_processes(file.parent)
    if parts and expected and all(any(f"_{p}_" in f"_{part.stem}_" for part in parts) for p in expected):
        return "done", "unmerged parts (merged by the estimations)"
    # ff run reusing the ss-os shapes: only the FF-weighted parts, merged with the ss-os file by the estimations
    ff_parts = _ff_only_parts(file)
    if ff_parts and (sibling := ss_os_sibling(file)) and sibling.exists() and (
            ff_parts[0].name == "shapes_ff_only.root" or expected and all(any(f"_{p}_" in f"_{part.stem}_" for part in ff_parts) for p in expected)):
        return "done", "ff-only parts + ss-os shapes (merged by the estimations)"
    parts += ff_parts
    return ("partial", f"{len(parts)} part(s)") if parts else ("missing", "")


def check_estimations(cfg, step, u):
    state, note = check_shapes(cfg, step, u)
    file = shapes_of(cfg, step, u)
    if state != "done" or not file.exists():
        return "missing", f"shapes {state}"
    probe = _PROBES.get(str(file))
    if probe is None:
        return "unknown", "ROOT probe failed"
    return ("done", "") if probe["QCD"] or probe["jetFakes"] else ("missing", "no QCD/jetFakes histograms")


def check_files(cfg, step, u):
    if step.outputs is None:
        return "manual", "not tracked"
    found = [matches(p) for p in step.outputs(cfg, u)]
    return ("done", "") if all(found) else ("missing", "")


CHECKS = {"files": check_files, "handoff": check_handoff, "shapes": check_shapes, "estimations": check_estimations}


def stamp_file(cfg):
    return REPO_ROOT / "condor/run" / cfg["ntupletag"] / "tauer_stamps.json"


def stamp_key(cfg, step, u):
    # outputs of steps with a tag live under it: sessions with other tags must not overwrite each other's stamps
    return f"{step.name}|{cfg['tag_arg'] + '|' if 'tag' in step.params and cfg['tag_arg'] else ''}{S.label(u)}"


def options_hash(cfg, step):
    keys = {k: cfg.get(k) for k in ("ntupletag", *step.params)}
    return hashlib.sha1(json.dumps([keys, cfg["extras"].get(step.name)], sort_keys=True).encode()).hexdigest()[:10]


def stamp_options(cfg, step):
    return {**{k: cfg.get(k) for k in ("ntupletag", *step.params)}, "extras": cfg["extras"].get(step.name)}


def changed_options(old, cfg, step):
    """Options that differ from the stamp: [] if equal, None if they differ but an old hash-only stamp cannot tell which."""
    if isinstance(old, str):
        return [] if old == options_hash(cfg, step) else None
    new = stamp_options(cfg, step)
    return [k for k in new.keys() | old.keys() if new.get(k) != old.get(k)]


def record_stamp(cfg, step, u):
    file = stamp_file(cfg)
    stamps = json.loads(file.read_text()) if file.exists() else {}
    stamps[stamp_key(cfg, step, u)] = stamp_options(cfg, step)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(stamps, indent=1))


def output_mtime(cfg, step, u):
    if step.check in ("shapes", "estimations"):
        file = shapes_of(cfg, step, u)
        return newest([file]) if file.exists() else None
    if step.outputs is None or step.where in ("crown", "handoff"):
        return None
    return min((newest(matches(p)) for p in step.outputs(cfg, u) if matches(p)), default=None)


def related(cfg, a, b):
    ctx = lambda u: {**u, "ffera": ff_config_era(u["era"])} if "era" in u and "ffera" not in u else u  # noqa: E731
    a, b = ctx(a), ctx(b)
    return all(a[k] == b[k] for k in a.keys() & b.keys())


def need_names(cfg, step):
    return step.needs(cfg) if callable(step.needs) else step.needs


def resolve(cfg, selected, jobs=None):
    """{step name: {unit label: (state, note)}} for the selected steps and everything they need, in DAG order."""
    _PROBES.clear()
    _XRD.clear()
    closure = set()
    todo = list(selected)
    while todo:
        name = todo.pop()
        if name not in closure:
            closure.add(name)
            todo += need_names(cfg, S.BY_NAME[name])
    stamps = json.loads(stamp_file(cfg).read_text()) if stamp_file(cfg).exists() else {}
    asked = {"ntupletag", *(k for name in selected for k in S.BY_NAME[name].params)}
    result, unit_list = {}, {}
    for step in (s for s in S.STEPS if s.name in closure):
        us = unit_list[step.name] = S.units(cfg, step)
        if step.check in ("shapes", "estimations"):
            probe_root([shapes_of(cfg, step, u) for u in us])
        raw = (check_crown(cfg, step, us) if step.check.startswith("crown") else check_btag_inputs(cfg, step, us) if step.check == "btag-inputs"
               else {S.label(u): CHECKS[step.check](cfg, step, u) for u in us})
        result[step.name] = {}
        for u in us:
            state, note = raw[S.label(u)]
            if job := (jobs or {}).get((step.name, S.label(u))):  # queued/running/held: the output is being (re)written
                state, note = job
            elif state == "done":
                own = output_mtime(cfg, step, u)
                upstream = [output_mtime(cfg, S.BY_NAME[n], v) for n in need_names(cfg, step) for v in unit_list[n] if related(cfg, u, v)]
                upstream += [newest([p]) for p in (step.inputs(cfg, u) if step.inputs else [])]
                changed = changed_options(old, cfg, step) if (old := stamps.get(stamp_key(cfg, step, u))) else []
                if step.name not in selected:
                    # the options of the other steps are not asked this session: only the asked ones can differ
                    changed = [k for k in changed or [] if k in asked]
                if changed != []:
                    # outputs made from other friend ntuples are other results in the same place: redo them
                    if friends := [f"{k}={old[k]}" for k in changed or [] if k in FRIEND_PARAMS]:
                        state, note = "missing", "made with " + ", ".join(friends)
                    else:
                        state, note = "other-options", "done with different options" + (f" ({', '.join(sorted(changed))})" if changed else "")
                elif own and any(t and t > own for t in upstream):
                    state, note = "stale", "an input is newer than the output"
            if state in ("missing", "partial", "manual", "unknown", "other-options"):
                pending = {n for n in need_names(cfg, step) for v in unit_list[n] if related(cfg, u, v) and result[n][S.label(v)][0] not in DONE_LIKE}
                if pending:
                    state, note = ("waiting" if pending <= set(selected) else "blocked"), "needs " + ", ".join(sorted(pending))
            elif state == "done":
                # its output is outdated as soon as an upstream unit is being redone
                redoing = {n for n in need_names(cfg, step) for v in unit_list[n] if related(cfg, u, v) and result[n][S.label(v)][0] in ("queued", "running", "held", "waiting")}
                if redoing:
                    state, note = "waiting", "needs " + ", ".join(sorted(redoing)) + " (being redone)"
            result[step.name][S.label(u)] = (state, note)
    # only show the upstream steps a shown step still waits for: the needs of fully done steps are not relevant
    shown = set(selected)
    for step in reversed([s for s in S.STEPS if s.name in shown or s.name in closure]):
        if step.name in shown and any(state != "done" for state, _ in result[step.name].values()):
            shown.update(need_names(cfg, step))
    return {name: units for name, units in result.items() if name in shown}


if __name__ == "__main__" and sys.argv[1:2] == ["--probe"]:
    import ROOT

    ROOT.gROOT.SetBatch(True)
    out = {}
    for path in sys.argv[2:]:
        f = ROOT.TFile.Open(path)
        names = set()
        if f and not f.IsZombie() and f.GetListOfKeys().GetSize():
            variable = f.GetListOfKeys()[0].ReadObj()
            names = {k.GetName() for b in variable.GetListOfKeys() for k in b.ReadObj().GetListOfKeys()}
        out[path] = {"missing": missing_processes(Path(path)), "QCD": "QCD" in names, "jetFakes": "jetFakes" in names}
    print(json.dumps(out))


if __name__ == "__main__" and sys.argv[1:2] == ["--branches"]:
    import ROOT

    ROOT.gROOT.SetBatch(True)
    out = []
    for url, columns in json.loads(sys.argv[2]):
        f = ROOT.TFile.Open(url)
        tree = f.Get("ntuple") if f and not f.IsZombie() else None
        names = {b.GetName() for b in tree.GetListOfBranches()} if tree else None
        out.append(None if names is None else [c for c in columns if c not in names])
    print(json.dumps(out))
