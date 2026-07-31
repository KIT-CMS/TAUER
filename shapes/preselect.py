#!/usr/bin/env python
"""
shapes/preselect.py — Prepare preselected ntuples for TauKITFlow shape production.

This is the analysis' preselection step: it reads CROWN ntuples directly and
writes ONE flat preselection tree

    {output_dir}/{era}/{channel}/{key}.root

that is then consumed, unchanged and without any second copy/mirror of it, by
BOTH downstream consumers:

  * shape production -- ``shapes/produce_shapes.py --presel-dir`` (reads this
    layout via ntuple_processor.booking's ``flat_layout`` branch);
  * the fake-factor measurement -- ``TauFakeFactors``' ``ff_calculation.py`` /
    ``ff_corrections.py``, via ``run.py``'s ``--ff-input-dir`` (which points
    their ``file_path``/``output_path`` here).

Cuts and weights come from the central config (``config/cuts.yaml``,
``config/weights.yaml``) -- the same source ``channel_selection.py`` uses for
live shape production -- so this is a full replacement for TauFakeFactors'
own ``preselection.py`` within this pipeline. That file (and its generated
``configs/smhtt_ul/{era}/preselection_{ch}.yaml``) is untouched and still
works for running TauFakeFactors standalone; it is simply not part of this
pipeline. Output *naming* is deliberately identical to it, though --
``helper.functions.get_output_name`` is reused directly -- so TauFakeFactors
reads this tree with zero changes on its side. Gen-mode splitting likewise
reuses TauFakeFactors' own ``helper.filters.tau_origin_split``.

Backgrounds / data:
  Per TFF process (``DYjets``, ``ttbar``, ``data``, ...), all contributing
  samples are concatenated and split by tau gen. mode, giving one file per
  ``{process}[_{gen_mode}]`` key.

Signals:
  One file per physical sample name (signals are not concatenated into
  groups). The same event selection is applied and a ``weight`` column
  is computed (lumi × generator × tau-ID SFs × lepton SFs × Z/Top pt
  reweighting where applicable). All branches are saved, including systematic
  variations.

Usage
-----
  python shapes/preselect.py \\
      --era 2022postEE --channel mt \\
      --directory /store/.../CROWNRun/ \\
      --xsec-friends /store/.../xsec/ \\
      --output-dir /ceph/.../TauKITFlow_shapes/<tag>/preselection \\
      --nthreads 4
"""
import argparse
import contextlib
import glob
import logging
import os
import re
import subprocess
import sys
import time

import ROOT

ROOT.gROOT.SetBatch(True)

from config.analysis import (
    PRESELECTION_MASK_BRANCH,
    SIGNAL_SAMPLES as signal_files,
    get_background_processes,
    get_luminosity,
    get_mc_ntuple_era,
    get_mc_weights,
    get_output_features,
    get_preselection_cuts,
    get_region_mask_names,
)
from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

_TOP_PT_PROCESSES = {"ttbar", "ST"}
_Z_PT_PROCESSES   = {"DYjets"}

# Same redirector ntuple_processor.booking lists CROWN output through.
_XROOTD_REDIRECTOR = "root://cmsdcache-kit-disk.gridka.de:1094"

# Per-directory `xrdfs ls` budget. A cold dCache listing of one sample dir
# takes ~40 s here, a warm one well under a second -- 300 s is generous
# enough that only a genuine stall trips it.
_XRDFS_LS_TIMEOUT = 300
_XRDFS_LS_RETRIES = 3


# ---------------------------------------------------------------------------
# Input file discovery
# ---------------------------------------------------------------------------

def _strip_xrootd_prefix(path: str) -> str:
    if (match := re.match(r"^root://[^/]+(?::\d+)?(/.*)$", path)):
        path = match.group(1)
    return re.sub(r"^/+", "/", path)


def _is_remote(path: str) -> bool:
    """CROWN ntuples live on dCache; `--directory`/`--xsec-friends` are passed
    as bare `/store/user/...` paths (see common.sample_paths) that exist on no
    local filesystem."""
    return path.startswith("root://") or _strip_xrootd_prefix(path).startswith("/store/")


def _list_root_files(base_directory: str, *parts: str) -> tuple[list[str], str]:
    """Return (sorted .root files, human-readable location) under
    {base_directory}/{parts...}.

    Local paths are globbed as before; `/store/...` (or explicit `root://...`)
    paths are listed over xrootd -- exactly like ntuple_processor.booking's
    xrootd branch -- and returned as full root:// URLs, which TChain.Add reads
    directly. Plain glob.glob() on a bare /store path finds nothing and made
    every process silently preselect to an empty file.
    """
    directory = os.path.join(_strip_xrootd_prefix(base_directory), *parts)

    if not _is_remote(base_directory):
        pattern = os.path.join(directory, "*.root")
        return sorted(glob.glob(pattern)), pattern

    # NOTE the double slash after the redirector: `root://host:1094/store/...`
    # is a *relative* xrootd path and the server answers "No such file".
    location = f"{_XROOTD_REDIRECTOR}/{directory}/*.root"

    # Listing goes through the `xrdfs` binary rather than the XRootD python
    # bindings on purpose: importing/using `XRootD.client` in-process loads a
    # second XRootD stack next to the libXrdCl ROOT itself is linked against,
    # and the subsequent ROOT read of the very same file then deadlocks (hangs
    # forever in a futex, with the XRootD client threads gone). Out-of-process
    # there is no such conflict.
    # dCache namespace lookups occasionally stall for minutes; without a
    # timeout that stall is indistinguishable from a dead job (the whole
    # preselection just sits there with no output). Bound it and retry.
    proc = None
    for attempt in range(1, _XRDFS_LS_RETRIES + 1):
        try:
            proc = subprocess.run(
                ["xrdfs", _XROOTD_REDIRECTOR, "ls", directory],
                capture_output=True, text=True, timeout=_XRDFS_LS_TIMEOUT,
            )
            break
        except subprocess.TimeoutExpired:
            logger.warning(
                f"xrdfs ls timed out after {_XRDFS_LS_TIMEOUT}s "
                f"(attempt {attempt}/{_XRDFS_LS_RETRIES}): {directory}"
            )
    if proc is None:
        logger.error(f"xrdfs ls kept timing out, treating as empty: {directory}")
        return [], location
    if proc.returncode != 0:
        logger.debug(f"xrdfs ls failed for {directory}: {proc.stderr.strip()}")
        return [], location

    files = sorted(
        f"{_XROOTD_REDIRECTOR}/{line.strip()}"
        for line in proc.stdout.splitlines()
        if line.strip().endswith(".root")
    )
    return files, location


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _quiet_empty_tree_warnings():
    """Silence TChain::AddFile's "Adding tree with no entries" warning.

    CROWN routinely writes skimmed ntuple files that end up with zero events
    (and a matching zero-entry xsec friend), so this warning is expected, not
    a symptom: it fires once per empty file per Add and buries the actual
    progress log. Only the warning level is raised, and only around chain
    construction -- real errors still print.
    """
    prev = ROOT.gErrorIgnoreLevel
    ROOT.gErrorIgnoreLevel = ROOT.kError
    try:
        yield
    finally:
        ROOT.gErrorIgnoreLevel = prev


def _chain_with_friend(ntuple_files: list[str], xsec_files: list[str]) -> ROOT.TChain:
    """Main chain + (optional) xsec friend chain, built without the empty-tree
    warning spam. The two are index-aligned file by file, empty files
    included -- CROWN writes one friend file per ntuple file with the same
    entry count, so an empty ntuple file has an empty friend next to it."""
    with _quiet_empty_tree_warnings():
        chain = ROOT.TChain("ntuple")
        for f in ntuple_files:
            chain.Add(f)
        if xsec_files:
            fchain = ROOT.TChain("ntuple")
            for f in xsec_files:
                fchain.Add(f)
            chain.AddFriend(fchain)
            # The friend chain is owned by Python and must outlive the
            # TChain it is attached to -- keep a reference on the chain.
            chain._xsec_friend = fchain
    return chain


def _exit_without_closing_remote_files(code: int = 0) -> None:
    """Terminate without letting ROOT close the remote input files.

    At interpreter shutdown ROOT's atexit handler calls TROOT::CloseFiles(),
    which closes every still-open TNetXNGFile -- and that Close() blocks
    forever on an XrdCl condition variable in this environment (the
    `fake_factors` env loads a second XRootD stack via the pyxrootd bindings
    next to the one ROOT is linked against -- the same conflict
    _list_root_files avoids by shelling out to `xrdfs`). The work is done and
    fully written by this point; the process would just sit there, which is
    indistinguishable from a hung preselection.

    Local output files are closed properly first -- only the remote,
    read-only inputs are abandoned, which costs nothing.
    """
    for f in list(ROOT.gROOT.GetListOfFiles()):
        if not str(f.GetName()).startswith("root://"):
            f.Close()
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def _enable_mt(nthreads: int) -> None:
    """EnableImplicitMT is a no-op-with-warning once MT is on; this is called
    per sample, so guard it."""
    if not ROOT.ROOT.IsImplicitMTEnabled():
        ROOT.ROOT.EnableImplicitMT(nthreads)


def _run_graphs(results: list) -> None:
    """Run every booked result in ONE event loop.

    Each RDataFrame action triggers a full pass over the input, and the input
    here is 100+ files read over xrootd (~30 s per pass per sample). Booking
    the per-gen-mode counts and Snapshots and running them together turns the
    old count-then-count-again-then-snapshot sequence (7+ passes for a
    3-gen-mode background sample) into a single one.
    """
    if results:
        ROOT.RDF.RunGraphs(results)


def _define_weight(rdf, expr: str):
    """Define the preselection event weight as ``weight``.

    One number, one name, for both consumers of this tree: it is what
    TauFakeFactors' own preselection.py writes (so ff_calculation.py /
    ff_corrections.py and config/variables.yaml's ``output_features``
    whitelist find it where they expect), and what shape production reads
    back via shapes/selection/process_selection.py's preselected branch.
    """
    # Redefine, not Define, if the ntuples already ship a `weight` branch:
    # `weight` means "the preselection weight this step computed", so ours
    # wins -- and Define on an existing column would throw.
    if "weight" in {str(c) for c in rdf.GetColumnNames()}:
        return rdf.Redefine("weight", expr)
    return rdf.Define("weight", expr)


def _existing_columns(rdf, requested: list[str], label: str) -> list[str]:
    """Restrict `requested` to columns the RDataFrame actually has.

    Snapshotting a column that isn't defined crashes the process outright
    (ROOT 6.34 segfaults instead of raising), so a whitelist entry that this
    ntuple version simply doesn't carry would otherwise kill the whole run
    with no message. Warn and carry on with what exists instead.
    """
    have = {str(c) for c in rdf.GetColumnNames()}
    missing = [c for c in requested if c not in have]
    if missing:
        logger.warning(f"{label}: columns not in the ntuples, not written: {missing}")
    return [c for c in requested if c in have]


def _apply_preselection(rdf, event_selection: dict, label: str, force_legacy: bool = False):
    """Apply the preselection to `rdf`, preferring CROWN's `presel_mask` branch.

    Two equivalent paths, chosen per input file:

    * **mask path** — the ntuples carry CROWN's precomputed ``presel_mask``
      (booked by CROWN's ``selection.py``, feature/selection-masks): ONE
      ``Filter("presel_mask > 0.5")`` replaces the whole per-cut loop. The mask
      is the same per-channel ``preselection:`` block of config/cuts.yaml,
      evaluated once at ntuple-production time — so the selection is defined in
      exactly one place instead of being re-composed as C++ strings here.
    * **legacy path** — old (maskless) ntuples, or ``--force-legacy-cuts``:
      the historical loop, one named Filter per cut in `event_selection`.

    Detection reuses the same "does the RDataFrame have this column" mechanism
    as _existing_columns() (branch-existence, per file), so a mixed set of old
    and new productions just works, file by file. Both paths log which one was
    taken — that log line is the A/B-validation breadcrumb.
    """
    if force_legacy:
        logger.info(f"{label}: preselection via legacy cut strings (--force-legacy-cuts)")
    elif PRESELECTION_MASK_BRANCH in {str(c) for c in rdf.GetColumnNames()}:
        logger.info(
            f"{label}: preselection via CROWN mask branch "
            f"'{PRESELECTION_MASK_BRANCH}' (1 filter replaces "
            f"{len(event_selection)} cut strings)"
        )
        return rdf.Filter(f"{PRESELECTION_MASK_BRANCH} > 0.5", "presel:mask")
    else:
        logger.info(
            f"{label}: no '{PRESELECTION_MASK_BRANCH}' branch in these ntuples — "
            f"falling back to the legacy cut strings ({len(event_selection)} filters)"
        )

    for cut_name, cut_expr in event_selection.items():
        rdf = rdf.Filter(f"({cut_expr})", f"presel:{cut_name}")
    return rdf


def _build_weight_expr(mc_weights: dict, process: str, era: str) -> str:
    """
    Build a C++ event-weight expression for a signal or MC background process.

    Mirrors TFF mc_weights but replaces TFF-internal generator/lumi keys with
    CROWN xsec-friend columns so it works outside of TFF's helper library.
    Not used for "data" -- callers should skip this and use weight "1.0"
    directly (real data has no crossSectionPerEventWeight/genWeight branches).
    """
    lumi = get_luminosity(era) * 1000.0  # config/samples.yaml stores fb^-1; weight needs pb^-1
    parts = []
    for key, expr in mc_weights.items():
        if key == "generator":
            parts.append(
                "numberGeneratedEventsWeight"
                " * crossSectionPerEventWeight"
                " * (1.0 / negative_events_fraction)"
                " * (((genWeight < 0) * (-1)) + ((genWeight >= 0) * 1))"
            )
        elif key == "lumi":
            parts.append(str(lumi))
        elif key == "Z_pt_reweighting":
            if process in _Z_PT_PROCESSES and isinstance(expr, str) and expr.strip():
                parts.append(f"({expr})")
        elif key == "Top_pt_reweighting":
            if process in _TOP_PT_PROCESSES and isinstance(expr, str) and expr.strip():
                parts.append(f"({expr})")
        elif isinstance(expr, str) and expr.strip():
            parts.append(f"({expr})")
    return " * ".join(parts) if parts else "1.0"


# ---------------------------------------------------------------------------
# Background / data preselection
# ---------------------------------------------------------------------------

def process_background_process(
    *,
    tff_process: str,
    era: str,
    channel: str,
    directory: str,
    xsec_friends: str,
    flat_output_dir: str,
    event_selection: dict,
    mc_weights: dict,
    samples: list,
    tau_gen_modes: list,
    nthreads: int,
    force_legacy_cuts: bool = False,
) -> None:
    """
    Preselect + weight one background process (e.g. "DYjets", "data"),
    split by tau_gen_mode, from CROWN ntuples directly -- writing
    TauFakeFactors-native flat output:
        {flat_output_dir}/{process}[_{tau_gen_mode}].root

    Mirrors TauFakeFactors/preselection.py's two-phase approach (per-sample
    temp file, then concatenate per tau_gen_mode, delete temps) so
    TauFakeFactors' ff_calculation.py/ff_corrections.py can read this output
    unmodified. Cuts/weights come from the central config (config/cuts.yaml,
    config/weights.yaml) and CROWN xsec-friend columns -- same as
    process_signal_sample() above -- rather than TFF's own datasets.json
    sample database. Gen-mode splitting and output naming are delegated to
    TauFakeFactors' own helper.filters.tau_origin_split /
    helper.functions.get_output_name so the result is byte-layout-identical
    to a real TFF preselection.py run.
    """
    # Lazy import: pulls in
    # TauFakeFactors' own dependencies (e.g. ruamel.yaml) that plain
    # signal-only runs of this script must not require.
    import helper.filters as tff_filters
    import helper.functions as tff_func

    is_data = tff_process == "data"
    dataset_era = era if is_data else get_mc_ntuple_era(era)
    # config/variables.yaml's output_features is the branch whitelist for
    # this tree; it already contains `weight` (see _define_weight), which is
    # the single weight column both consumers read.
    # Plus the CROWN selection-mask branches for this scope: they must SURVIVE
    # the skim so the downstream fake-factor calculation can filter its regions
    # on them (they are kept out of `output_features` itself because that list
    # doubles as the training/control-plot variable set -- see the comment in
    # config/variables.yaml). Absent on old ntuples -> _existing_columns()
    # drops them with a warning, exactly as for any other missing branch.
    output_features = get_output_features()
    output_features += [
        m for m in get_region_mask_names(era, channel) if m not in output_features
    ]

    per_mode_files: dict = {mode: [] for mode in tau_gen_modes}

    lazy = ROOT.RDF.RSnapshotOptions()
    lazy.fLazy = True

    for i_sample, sample in enumerate(samples, start=1):
        t_sample = time.time()
        ntuple_files, ntuple_loc = _list_root_files(directory, dataset_era, sample, channel)
        if not ntuple_files:
            logger.warning(f"No ntuple files for {tff_process}/{sample}: {ntuple_loc}")
            continue

        xsec_files: list[str] = []
        if xsec_friends and not is_data:
            xsec_files, xsec_loc = _list_root_files(xsec_friends, dataset_era, sample, channel)
            if not xsec_files:
                logger.warning(f"No xsec friend files for {tff_process}/{sample}: {xsec_loc}")

        logger.info(
            f"[{era}/{channel}] {tff_process} [{i_sample}/{len(samples)}] {sample}: "
            f"{len(ntuple_files)} files -> reading"
        )
        chain = _chain_with_friend(ntuple_files, xsec_files)

        _enable_mt(nthreads)
        rdf = ROOT.RDataFrame(chain)

        rdf = _apply_preselection(
            rdf, event_selection, f"{tff_process}/{sample}", force_legacy=force_legacy_cuts
        )

        if is_data:
            rdf = _define_weight(rdf, "1.0")
        else:
            rdf = _define_weight(rdf, _build_weight_expr(mc_weights, tff_process, era))

        cols = _existing_columns(rdf, output_features, f"{tff_process}/{sample}")

        # Book every gen mode first, run them in ONE pass over the sample (see
        # _run_graphs) -- the counts decide afterwards which Snapshots were
        # empty, instead of costing an extra pass each up front.
        booked = []
        for mode in tau_gen_modes:
            tmp_rdf = rdf if mode == "all" else tff_filters.tau_origin_split(
                rdf=rdf, channel=channel, tau_gen_mode=mode
            )
            tmp_file = tff_func.get_output_name(path=flat_output_dir, process=sample, tau_gen_mode=mode)
            booked.append((mode, tmp_file, tmp_rdf.Count(),
                           tmp_rdf.Snapshot("ntuple", tmp_file, cols, lazy)))

        _run_graphs([r for entry in booked for r in entry[2:]])

        n_sample = 0
        for mode, tmp_file, count, _ in booked:
            if count.GetValue() == 0:
                # Snapshot wrote the (empty) file regardless -- drop it so the
                # concatenation below sees only real inputs.
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
                continue
            n_sample += count.GetValue()
            per_mode_files[mode].append(tmp_file)
        logger.info(
            f"[{era}/{channel}] {tff_process} [{i_sample}/{len(samples)}] {sample}: "
            f"{n_sample} events kept ({time.time() - t_sample:.0f}s)"
        )

    for mode, files in per_mode_files.items():
        out_file = tff_func.get_output_name(path=flat_output_dir, process=tff_process, tau_gen_mode=mode)
        if files:
            sum_rdf = ROOT.RDataFrame("ntuple", files)
            n_events = sum_rdf.Count()
            snap = sum_rdf.Snapshot(
                "ntuple", out_file,
                _existing_columns(sum_rdf, output_features, f"{tff_process}_{mode}"),
                lazy,
            )
            _run_graphs([n_events, snap])
            logger.info(f"[{era}/{channel}] {tff_process}_{mode}: {n_events.GetValue()} events -> {out_file}")
        else:
            logger.info(f"[{era}/{channel}] No events for {tff_process}_{mode}, writing empty file -> {out_file}")
            f = ROOT.TFile(out_file, "RECREATE")
            t = ROOT.TTree("ntuple", "ntuple")
            t.Write()
            f.Close()
        for rf in files:
            os.remove(rf)


def run_central_backgrounds(era: str, channel: str, directory: str, xsec_friends: str,
                             flat_output_dir: str, nthreads: int,
                             force_legacy_cuts: bool = False) -> None:
    """Preselect every background process for one era/channel centrally (see
    process_background_process()) into the TFF-native flat layout."""
    os.makedirs(flat_output_dir, exist_ok=True)
    event_selection = get_preselection_cuts(era, channel)
    mc_weights = get_mc_weights(era, channel)
    bg_processes = get_background_processes(era)
    for tff_process, info in bg_processes.items():
        if tff_process == "data":
            samples = info.get("by_channel", {}).get(channel, [])
        else:
            samples = info.get("samples", [])
        tau_gen_modes = info.get("tau_gen_modes", ["all"])
        logger.info(f"[{era}/{channel}] Central preselection: {tff_process} ({len(samples)} samples, modes={tau_gen_modes})")
        process_background_process(
            tff_process=tff_process,
            era=era,
            channel=channel,
            directory=directory,
            xsec_friends=xsec_friends,
            flat_output_dir=flat_output_dir,
            event_selection=event_selection,
            mc_weights=mc_weights,
            samples=samples,
            tau_gen_modes=tau_gen_modes,
            nthreads=nthreads,
            force_legacy_cuts=force_legacy_cuts,
        )


# ---------------------------------------------------------------------------
# Signal processing
# ---------------------------------------------------------------------------

def process_signal_sample(
    *,
    sample: str,
    era: str,
    channel: str,
    directory: str,
    xsec_friends: str,
    output_dir: str,
    event_selection: dict,
    mc_weights: dict,
    process: str,
    nthreads: int,
    force_legacy_cuts: bool = False,
) -> None:
    """Apply TFF event selection to a signal sample and save ALL columns."""

    # Signal is MC -- read ntuples/friends from the physical production-era
    # directory (may differ from the analysis `era`, e.g. 2026 borrowing
    # 2025's un-copied MC; see config.analysis.get_mc_ntuple_era). Output
    # still gets organised under the real analysis `era` below.
    mc_era = get_mc_ntuple_era(era)
    ntuple_files, ntuple_loc = _list_root_files(directory, mc_era, sample, channel)
    if not ntuple_files:
        logger.warning(f"No ntuple files for signal {sample}: {ntuple_loc}")
        return

    xsec_files: list[str] = []
    if xsec_friends:
        xsec_files, xsec_loc = _list_root_files(xsec_friends, mc_era, sample, channel)
        if not xsec_files:
            logger.warning(f"No xsec friend files for signal {sample}: {xsec_loc}")

    logger.info(f"[{era}/{channel}] signal {sample}: {len(ntuple_files)} files -> reading")
    chain = _chain_with_friend(ntuple_files, xsec_files)

    _enable_mt(nthreads)
    rdf = ROOT.RDataFrame(chain)

    # Apply the preselection (CROWN presel_mask when present, else legacy cuts)
    rdf = _apply_preselection(
        rdf, event_selection, f"signal/{sample}", force_legacy=force_legacy_cuts
    )

    # Compute the event weight using TFF mc_weights (adapted for CROWN xsec columns)
    w_expr = _build_weight_expr(mc_weights, process, era)
    rdf = _define_weight(rdf, w_expr)

    # Save ALL columns (including weight and systematic branches).
    # Flat layout, same as backgrounds: one file per dataset key, named after
    # the key itself. build_presel_files_dict() maps each signal group (ggH,
    # qqH, ...) to its list of original per-sample names, so for signals the
    # "key" is the physical sample name (signals are not concatenated the way
    # backgrounds are).
    out_dir = os.path.join(output_dir, era, channel)
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"{sample}.root")

    # Strip "ntuple." friend prefix from column names for clean output
    raw_cols = [str(c) for c in rdf.GetColumnNames()]
    seen: set[str] = set()
    cols: list[str] = []
    for c in raw_cols:
        clean = c.replace("ntuple.", "")
        if clean not in seen:
            seen.add(clean)
            cols.append(c)

    # Count + Snapshot in one pass (see _run_graphs): a second pass just to
    # learn the event count costs as much as the write itself over xrootd.
    lazy = ROOT.RDF.RSnapshotOptions()
    lazy.fLazy = True
    t_sample = time.time()
    count = rdf.Count()
    snap = rdf.Snapshot("ntuple", out_file, cols, lazy)
    _run_graphs([count, snap])

    n_events = count.GetValue()
    if n_events == 0:
        logger.info(f"No events left after presel for signal {sample}, dropping {out_file}")
        if os.path.exists(out_file):
            os.remove(out_file)
        return
    logger.info(f"Saved {n_events} signal events [{sample}] → {out_file} ({time.time() - t_sample:.0f}s)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Preselect CROWN ntuples (backgrounds, data and signals) into the one\n"
            "flat preselection tree consumed by both shape production and the\n"
            "TauFakeFactors fake-factor measurement."
        )
    )
    parser.add_argument("--era",          required=True,  help="CMS era (e.g. 2022postEE).")
    parser.add_argument("--channel",      required=True,  help="Channel (et, mt, tt).")
    parser.add_argument("--output-dir",   required=True,
                        help="Preselection output base dir; files are written flat as "
                             "{output-dir}/{era}/{channel}/{key}.root "
                             "(build_shape_output_paths(ntupletag).preselection).")
    parser.add_argument("--directory",    required=True,  help="CROWN ntuple base dir.")
    parser.add_argument("--xsec-friends", default=None,   help="xsec friends base dir (MC weighting).")
    parser.add_argument("--nthreads",     default=4, type=int, help="ROOT implicit MT threads.")
    parser.add_argument("--skip-signals", action="store_true",
                        help="Skip signal processing (backgrounds/data only).")
    parser.add_argument("--skip-backgrounds", action="store_true",
                        help="Skip background/data processing (signals only).")
    parser.add_argument("--force-legacy-cuts", action="store_true",
                        help="Never use CROWN's precomputed `presel_mask` branch; always apply "
                             "the per-cut preselection loop from config/cuts.yaml, even when the "
                             "mask is present. Escape hatch for A/B validation of the two paths "
                             "(they must agree event-by-event) and for debugging a suspect mask.")
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Backgrounds + data ─────────────────────────────────────────────────────
    if not args.skip_backgrounds:
        logger.info(f"[{args.era}/{args.channel}] Background preselection -> {args.output_dir}")
        run_central_backgrounds(
            era=args.era,
            channel=args.channel,
            directory=args.directory,
            xsec_friends=args.xsec_friends or "",
            flat_output_dir=os.path.join(args.output_dir, args.era, args.channel),
            nthreads=args.nthreads,
            force_legacy_cuts=args.force_legacy_cuts,
        )

    # ── Signals: process from CROWN ntuples ────────────────────────────────────
    if args.skip_signals:
        return

    era_signals = signal_files.get(args.era, {})
    if not era_signals:
        logger.info(f"No signals defined for era {args.era}, nothing to do.")
        return

    if not args.directory:
        logger.error("--directory is required for signal processing.")
        raise SystemExit(1)

    event_selection: dict = get_preselection_cuts(args.era, args.channel)
    mc_weights: dict      = get_mc_weights(args.era, args.channel)

    for sig_key, sig_samples in era_signals.items():
        for sample in sig_samples:
            logger.info(f"[{args.era}/{args.channel}] Signal {sig_key}/{sample}")
            process_signal_sample(
                sample=sample,
                era=args.era,
                channel=args.channel,
                directory=args.directory,
                xsec_friends=args.xsec_friends or "",
                output_dir=args.output_dir,
                event_selection=event_selection,
                mc_weights=mc_weights,
                process=sig_key,
                nthreads=args.nthreads,
                force_legacy_cuts=args.force_legacy_cuts,
            )


if __name__ == "__main__":
    main()
    # Not a plain fall-through: see _exit_without_closing_remote_files().
    _exit_without_closing_remote_files(0)
