from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Callable

HaddRunner = Callable[[list], int]

_EXPECTED_PROCESSES_FILENAME = "expected_processes.json"


def _default_run_hadd(argv: list) -> int:
    return subprocess.run(argv).returncode


def find_parts(merged_path: Path) -> list[Path]:
    pattern = f"{merged_path.stem}__*{merged_path.suffix}"
    return sorted(merged_path.parent.glob(pattern))


def merge_if_needed(merged_path: Path, logger: logging.Logger | None = None) -> bool:
    log = logger or logging.getLogger(__name__)
    parts = find_parts(merged_path)
    if not parts:
        return False

    stale = not merged_path.exists() or any(
        p.stat().st_mtime > merged_path.stat().st_mtime for p in parts
    )
    if not stale:
        log.info(
            "%s is already up to date with its %d shapes__*.root part(s); skipping merge.",
            merged_path, len(parts),
        )
        return False

    log.info(
        "Found %d shapes__*.root part(s) newer than %s (or it doesn't exist yet) -- "
        "merging via hadd before continuing: %s",
        len(parts), merged_path, [p.name for p in parts],
    )
    subprocess.run(
        ["hadd", "-f", str(merged_path), *[str(p) for p in parts]], check=True,
    )
    return True


def ss_os_sibling(ff_path: Path) -> Path | None:
    parts = list(ff_path.parts)
    if len(parts) < 4 or parts[-4] != "ff":
        return None
    parts[-4] = "ss-os"
    return Path(*parts)


_FF_ONLY_PER_PROCESS_PREFIX = "shapes_ff_only__"

# shapes/estimations/qcd.py's qcd_estimation() proc_name values
_QCD_ESTIMATION_DATASETS = frozenset({"QCD", "QCDMC", "QCD_NLO", "QCDMC_NLO"})


def _strip_stale_qcd_estimation(ff_path: Path, log: logging.Logger) -> None:
    import ROOT

    f = ROOT.TFile(str(ff_path), "update")
    if f.IsZombie():
        f.Close()
        return
    try:
        stale = [
            key.GetName() for key in f.GetListOfKeys()
            if key.GetName().split("#", 1)[0] in _QCD_ESTIMATION_DATASETS
        ]
        for name in stale:
            f.Delete(f"{name};*")
        if stale:
            log.info(
                "%s: removed %d stale QCD-estimation histogram(s) inherited from the ss-os "
                "sibling (%s).", ff_path, len(stale), sorted(set(n.split('#', 1)[0] for n in stale)),
            )
    finally:
        f.Close()


def _ff_only_parts(ff_path: Path) -> list[Path]:
    parent = ff_path.parent
    whole = parent / "shapes_ff_only.root"
    per_process = sorted(parent.glob(f"{_FF_ONLY_PER_PROCESS_PREFIX}*.root"))
    return ([whole] if whole.exists() else []) + per_process


def merge_ff_reuse_if_needed(
    ff_path: Path,
    logger: logging.Logger | None = None,
    run_hadd: HaddRunner | None = None,
) -> bool:
    log = logger or logging.getLogger(__name__)
    hadd = run_hadd or _default_run_hadd
    parts = _ff_only_parts(ff_path)
    if not parts:
        return False
    if ff_path.exists() and ff_path.stat().st_mtime >= max(p.stat().st_mtime for p in parts):
        log.info(
            "%s is already merged with its %d ff-only part(s); skipping.", ff_path, len(parts),
        )
        return False

    ss_os_path = ss_os_sibling(ff_path)
    if ss_os_path is None or not ss_os_path.exists():
        log.warning(
            "%s has %d ff-only part(s) waiting but its ss-os sibling (%s) is missing or "
            "unresolvable -- cannot merge; leaving the ff-only part(s) in place (they only "
            "contain FF-weighted systematics, not a complete shapes file on their own).",
            ff_path, len(parts), ss_os_path,
        )
        return False

    log.info(
        "Merging ss-os shapes (%s) + %d ff-only part(s) into %s: %s",
        ss_os_path, len(parts), ff_path, [p.name for p in parts],
    )
    rc = hadd(["hadd", "-f", str(ff_path), str(ss_os_path), *[str(p) for p in parts]])
    if rc != 0:
        raise RuntimeError(
            f"hadd failed (exit {rc}) merging {ss_os_path} + {[p.name for p in parts]} into {ff_path}"
        )
    _strip_stale_qcd_estimation(ff_path, log)
    for p in parts:
        p.unlink(missing_ok=True)
    return True


def write_expected_processes(run_dir: Path, processes: list[str]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = run_dir / _EXPECTED_PROCESSES_FILENAME
    manifest.write_text(json.dumps(sorted(processes)))


def read_expected_processes(run_dir: Path) -> list[str] | None:
    manifest = run_dir / _EXPECTED_PROCESSES_FILENAME
    if not manifest.exists():
        return None
    return json.loads(manifest.read_text())


def missing_processes(shapes_path: Path) -> list[str]:
    expected = read_expected_processes(shapes_path.parent)
    if not expected:
        return []
    if not shapes_path.exists():
        return sorted(expected)

    from shapes.produce_shapes import PROCESS_DATASET_KEYS, SIGNAL_PROCESSES

    import ROOT

    is_ff = ss_os_sibling(shapes_path) is not None
    present_anti_iso: set[str] = set()
    present_other: set[str] = set()
    f = ROOT.TFile(str(shapes_path), "read")
    if f.IsZombie():
        f.Close()
        return sorted(expected)
    try:
        for key in f.GetListOfKeys():
            fields = key.GetName().split("#")
            if len(fields) != 4:
                continue
            dataset, _selection, systematic, _variable = fields
            if "anti_iso" in systematic:
                present_anti_iso.add(dataset)
            else:
                present_other.add(dataset)
    finally:
        f.Close()

    if is_ff:
        # Both halves required for a normal process: an ff run's merged file inherits every
        # ss-os process's nominal content (present_other) and adds this process's own
        # FF-weighted systematics (present_anti_iso) on top. SIGNAL_PROCESSES are the
        # exception -- they never get an anti_iso half in an --ff-only production.
        present_both = present_anti_iso & present_other
        present = present_both | (present_other & {
            PROCESS_DATASET_KEYS.get(name, name) for name in SIGNAL_PROCESSES
        })
    else:
        present = present_other | present_anti_iso
    return sorted(
        name for name in expected
        if PROCESS_DATASET_KEYS.get(name, name) not in present
    )
