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
  reweighting where applicable).

Signals and backgrounds write EXACTLY the same column set, built in exactly
one place -- ``_output_columns()``: ``config/variables.yaml``'s
``output_features`` whitelist, plus the CROWN selection masks for the
era/channel, plus every ``<base>__<shift>`` systematic variation of those that
the input actually carries (derived from the input's own column list, never
from a hardcoded shift list).

Usage
-----
  python shapes/preselect.py \\
      --era 2022postEE --channel mt \\
      --directory /store/.../CROWNRun/ \\
      --xsec-friends /store/.../xsec/ \\
      --output-dir /ceph/.../TauKITFlow_shapes/<tag>/preselection \\
      --nthreads 4 --nworkers 4

Add ``--mask-friends /store/.../selection/`` when the production shipped
CROWN's selection masks as a friend tree instead of inside the ntuple; the
mask path is then taken exactly as it is for masks-in-the-ntuple productions.
"""
import argparse
import contextlib
import functools
import glob
import json
import logging
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

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

# Top pt reweighting is a ttbar-only correction, and CROWN only books the
# topPtReweightWeight branch for samples=["ttbar"] (config.py TopPtReweighting)
# -- including ST here makes the weight expression reference a column that does
# not exist in the single-top ntuples.
_TOP_PT_PROCESSES = {"ttbar"}
_Z_PT_PROCESSES   = {"DYjets"}

# Same redirector ntuple_processor.booking lists CROWN output through.
_XROOTD_REDIRECTOR = "root://cmsdcache-kit-disk.gridka.de:1094"

# Per-directory `xrdfs ls` budget. A cold dCache listing of one sample dir
# takes ~40 s here, a warm one well under a second. 300 s meant a single
# genuinely stuck namespace lookup cost 15 min of dead time before the third
# attempt gave up (the run log's "xrdfs ls timed out after 300s"); 60 s is
# still ~1.5x the worst honest cold listing measured, and a retry after a
# stall usually lands on a different door and answers immediately.
_XRDFS_LS_TIMEOUT = 60
_XRDFS_LS_RETRIES = 4

# CROWN's systematic-shift branch naming: `<base quantity>__<shift name>`
# (e.g. `pt_1__CMS_scale_j_AbsoluteUp`). Verified against the production
# ntuples -- there is no other double underscore in a CROWN branch name.
_SHIFT_SEPARATOR = "__"

# Read-ahead for the remote inputs. Without a TTreeCache the event loop asks
# dCache for one basket at a time, so a skim that touches ~50 of ~10k branches
# turns into thousands of small, latency-bound round trips per file; the cache
# coalesces one cluster's worth of baskets into a single request.
_TREE_CACHE_BYTES = 200 * 1024 * 1024


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


@functools.lru_cache(maxsize=None)
def _list_root_files(base_directory: str, *parts: str) -> tuple[tuple[str, ...], str]:
    """Return (sorted .root files, human-readable location) under
    {base_directory}/{parts...}.

    Memoised per (base_directory, era, sample, channel): the same directory is
    listed again whenever a sample is revisited, and a remote `xrdfs ls` is
    never free (and occasionally stalls for minutes). Contents do not change
    under a running preselection.

    Local paths are globbed as before; `/store/...` (or explicit `root://...`)
    paths are listed over xrootd -- exactly like ntuple_processor.booking's
    xrootd branch -- and returned as full root:// URLs, which TChain.Add reads
    directly. Plain glob.glob() on a bare /store path finds nothing and made
    every process silently preselect to an empty file.
    """
    directory = os.path.join(_strip_xrootd_prefix(base_directory), *parts)

    if not _is_remote(base_directory):
        pattern = os.path.join(directory, "*.root")
        return tuple(sorted(glob.glob(pattern))), pattern

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
        return (), location
    if proc.returncode != 0:
        logger.debug(f"xrdfs ls failed for {directory}: {proc.stderr.strip()}")
        return (), location

    files = tuple(sorted(
        f"{_XROOTD_REDIRECTOR}/{line.strip()}"
        for line in proc.stdout.splitlines()
        if line.strip().endswith(".root")
    ))
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


def _chain_with_friend(
    ntuple_files: list[str],
    xsec_files: list[str],
    mask_files: list[str] | None = None,
) -> ROOT.TChain:
    """Main chain + (optional) xsec and selection-mask friend chains, built
    without the empty-tree warning spam. All of them are index-aligned file by
    file, empty files included -- CROWN writes one friend file per ntuple file
    with the same entry count, so an empty ntuple file has an empty friend next
    to it.

    The mask friend is the second of CROWN's two equivalent ways of shipping
    the selection masks (selection_friends.py writes them next to the ntuple;
    selection_config.py writes them into it). Attaching it makes
    `presel_mask`/`sel_*`/`ff_*` visible to _apply_preselection() and to the
    Snapshot column list under their PLAIN names -- RDataFrame resolves the
    unqualified name in expressions and Snapshot even though
    GetColumnNames() only lists the qualified "<friend tree>.<column>" form
    (see _unqualified_columns)."""
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
        if mask_files:
            mchain = ROOT.TChain("ntuple")
            for f in mask_files:
                mchain.Add(f)
            # Tagged: the mask friend's tree is called `ntuple` too, exactly
            # like the xsec friend's, and two same-named friends on one chain
            # would be indistinguishable. The tag only changes the *qualified*
            # column names ("masks.presel_mask"); the unqualified ones the cut
            # expressions use are unaffected.
            chain.AddFriend(mchain, "masks")
            chain._mask_friend = mchain

    # Read-ahead. The inputs are ~10k-branch CROWN ntuples on dCache and the
    # skim touches a few dozen of those branches, scattered all over each
    # file: without a TTreeCache every one of those baskets is its own
    # latency-bound xrootd request. SetLearnEntries(1) matters as much as the
    # size -- the default 100-entry learning phase would do those scattered
    # single-basket reads for the first 100 entries of every file before the
    # cache starts prefetching anything.
    ROOT.TTreeCache.SetLearnEntries(1)
    chain.SetCacheSize(_TREE_CACHE_BYTES)
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


def _define_weight(rdf, expr: str, have: set[str] | None = None):
    """Define the preselection event weight as ``weight``.

    One number, one name, for both consumers of this tree: it is what
    TauFakeFactors' own preselection.py writes (so ff_calculation.py /
    ff_corrections.py and config/variables.yaml's ``output_features``
    whitelist find it where they expect), and what shape production reads
    back via shapes/selection/process_selection.py's preselected branch.

    `have` is the pre-computed column set (see _unqualified_columns) -- pass it
    to avoid a second, expensive GetColumnNames() call.
    """
    # Redefine, not Define, if the ntuples already ship a `weight` branch:
    # `weight` means "the preselection weight this step computed", so ours
    # wins -- and Define on an existing column would throw.
    if have is None:
        have = _unqualified_columns(rdf)
    if "weight" in have:
        return rdf.Redefine("weight", expr)
    return rdf.Define("weight", expr)


def _unqualified_columns(rdf) -> set[str]:
    """Every column of `rdf`, friend columns included under their PLAIN name.

    GetColumnNames() lists a friend's columns ONLY in their qualified form,
    "<friend tree name>.<column>" (or "<tag>.<column>" for a tagged friend),
    while RDataFrame resolves the *unqualified* name everywhere else -- in cut
    and weight expressions and in Snapshot. Both spellings are returned, so a
    membership test on the plain name is right for ntuple and friend columns
    alike.

    CALL THIS ONCE PER SAMPLE AND PASS THE RESULT AROUND. GetColumnNames() on
    a CROWN chain is not a cheap accessor: RDataFrame resolves the type of
    every one of the ~10k branches (plus the friends'), which measured at
    ~12 s per call on the 2024 production. Doing it once instead of the three
    times the preselection used to (mask detection, weight definition, Snapshot
    column list) is worth ~25 s on *every* sample.
    """
    have = {str(c) for c in rdf.GetColumnNames()}
    return have | {c.split(".", 1)[1] for c in have if "." in c}


def _shift_columns(have: set[str], base_names: set[str]) -> list[str]:
    """Every systematic-shift column in `have` whose base quantity is wanted.

    CROWN names a shifted quantity `<base>__<shift>` (``_SHIFT_SEPARATOR``),
    e.g. `mt_1__CMS_scale_j_AbsoluteUp`. The shift list is derived from the
    input's real column names, never hardcoded: which shifts a production
    carries depends on the CROWN config, the era and the sample, and a
    hardcoded list would silently drop new ones and warn about absent ones.

    Only shifts of a whitelisted base quantity are kept -- a shifted copy of a
    branch that is not written in its nominal form is of no use downstream, and
    keeping all of them is what made the signal files 10k branches wide.
    """
    return sorted(
        c for c in have
        if "." not in c                       # skip the qualified friend spellings
        and _SHIFT_SEPARATOR in c
        and c.split(_SHIFT_SEPARATOR, 1)[0] in base_names
    )


def _output_columns(rdf, era: str, channel: str, label: str,
                    have: set[str] | None = None, keep_shifts: bool = True) -> list[str]:
    """THE Snapshot column list -- identical for backgrounds, data and signals.

    Three pieces, in this order:

    1. ``config/variables.yaml``'s ``output_features`` -- the branch whitelist
       both consumers of this tree read (see get_output_features()); it already
       contains `weight` and the xsec-friend weight inputs.
    2. the CROWN selection masks for this era/channel
       (get_region_mask_names()), which must survive the skim so the
       fake-factor calculation can filter its regions on them. They are kept
       out of `output_features` itself because that list doubles as the
       training/control-plot variable set -- see config/variables.yaml.
    3. every systematic-shift variant of 1.+2. that this input actually has
       (see _shift_columns) -- shape production needs the shifted quantities to
       build its systematic templates, and they are the only reason the signal
       path ever wanted "all columns".

    Signals used to bypass this and Snapshot `rdf.GetColumnNames()` wholesale,
    which (a) wrote ~10k branches per signal file, (b) wrote the xsec-friend
    columns under mangled `ntuple_crossSectionPerEventWeight` names because
    Snapshot cannot put a '.' in a branch name -- so produce_shapes.py's MC
    weight failed to JIT on signals with "use of undeclared identifier
    'negative_events_fraction'" -- and (c) segfaulted outright on the 2024
    production. Building the list here, once, is what keeps the two paths
    honestly identical.

    `keep_shifts=False` (--no-shift-branches) drops piece 3. MEASURE BEFORE
    YOU CHOOSE: on the 2024 mt production piece 3 is ~3340 of the ~3390
    columns and ~44% of the input bytes (against 0.6% for pieces 1+2), and a
    ~3400-column Snapshot costs ~3 ms/event of pure compression on top of a
    ~50 s one-off RDataFrame JIT -- measured 1341 s for four background files
    against ~50 s without. Shape production needs the shifted quantities
    (shapes/selection/variations.py's ReplaceVariable appends `__<shift>` to
    the branch it reads), so signals want them; a background skim of the whole
    era does not survive them.
    """
    if have is None:
        have = _unqualified_columns(rdf)
    wanted = get_output_features()
    wanted += [m for m in get_region_mask_names(era, channel) if m not in wanted]
    cols = _existing_columns(rdf, wanted, label, have=have)
    if not keep_shifts:
        return cols
    shifts = _shift_columns(have, set(wanted))
    if shifts:
        logger.info(f"{label}: {len(cols)} nominal + {len(shifts)} systematic-shift branches")
    return cols + shifts


def _existing_columns(rdf, requested: list[str], label: str,
                      have: set[str] | None = None) -> list[str]:
    """Restrict `requested` to columns the RDataFrame actually has.

    Snapshotting a column that isn't defined crashes the process outright
    (ROOT 6.34 segfaults instead of raising), so a whitelist entry that this
    ntuple version simply doesn't carry would otherwise kill the whole run
    with no message. Warn and carry on with what exists instead.

    Friend columns count as present. GetColumnNames() lists a friend's columns
    ONLY in their qualified form, "<friend tree name>.<column>" -- and the xsec
    friend's tree is itself called `ntuple`, so
    `crossSectionPerEventWeight` shows up as
    `ntuple.crossSectionPerEventWeight`. RDataFrame resolves the *unqualified*
    name everywhere else (the weight expression built by _build_weight_expr
    uses it, and Snapshot both accepts it and writes it under the plain name),
    so matching on the listed names alone silently dropped every xsec column
    from the preselection tree on MC -- with a "not in the ntuples" warning
    that was simply wrong. The same applies to the CROWN selection-mask
    branches when they arrive as a mask friend rather than inside the ntuple
    (see _chain_with_friend): they too must stay in the Snapshot column list.
    """
    if have is None:
        have = _unqualified_columns(rdf)
    missing = [c for c in requested if c not in have]
    if missing:
        logger.warning(f"{label}: columns not in the ntuples, not written: {missing}")
    return [c for c in requested if c in have]


def _apply_preselection(rdf, event_selection: dict, label: str, force_legacy: bool = False,
                        have: set[str] | None = None):
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
    and new productions just works, file by file. It goes through
    _unqualified_columns(), so it fires both when CROWN wrote the mask INTO
    the ntuple and when it wrote it into an attached mask FRIEND (where
    GetColumnNames() only ever lists "masks.presel_mask"). Both paths log
    which one was taken — that log line is the A/B-validation breadcrumb.
    """
    if have is None:
        have = _unqualified_columns(rdf)
    if force_legacy:
        logger.info(f"{label}: preselection via legacy cut strings (--force-legacy-cuts)")
    elif PRESELECTION_MASK_BRANCH in have:
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

def preselect_background_sample(
    *,
    tff_process: str,
    sample: str,
    era: str,
    channel: str,
    directory: str,
    xsec_friends: str,
    mask_friends: str,
    flat_output_dir: str,
    event_selection: dict,
    mc_weights: dict,
    tau_gen_modes: list,
    nthreads: int,
    force_legacy_cuts: bool = False,
    keep_shifts: bool = True,
    progress: str = "",
) -> None:
    """Preselect ONE background/data sample into its per-gen-mode temp files.

    Phase one of process_background_process()'s two-phase scheme, factored out
    so it can also be the unit of parallelism (see _run_jobs): the samples of a
    process are completely independent of each other, each writes only its own
    {flat_output_dir}/{sample}[_{mode}].root, and the whole step is dominated
    by latency-bound remote reads -- exactly the shape of work that wants
    several jobs in flight at once rather than a 54-iteration `for` loop.

    Files for gen modes with no surviving events are deleted, so "the temp file
    exists" is the signal the concatenation phase uses.
    """
    import helper.filters as tff_filters
    import helper.functions as tff_func

    is_data = tff_process == "data"
    dataset_era = era if is_data else get_mc_ntuple_era(era)

    t_sample = time.time()
    ntuple_files, ntuple_loc = _list_root_files(directory, dataset_era, sample, channel)
    if not ntuple_files:
        logger.warning(f"No ntuple files for {tff_process}/{sample}: {ntuple_loc}")
        return

    xsec_files: tuple = ()
    if xsec_friends and not is_data:
        xsec_files, xsec_loc = _list_root_files(xsec_friends, dataset_era, sample, channel)
        if not xsec_files:
            logger.warning(f"No xsec friend files for {tff_process}/{sample}: {xsec_loc}")

    # Selection-mask friend: only when the production put the masks NEXT
    # to the ntuples instead of inside them. Needed for data too (the
    # masks are pure selection bookkeeping, unlike the MC-only xsec ones).
    mask_files: tuple = ()
    if mask_friends:
        mask_files, mask_loc = _list_root_files(mask_friends, dataset_era, sample, channel)
        if not mask_files:
            logger.warning(f"No mask friend files for {tff_process}/{sample}: {mask_loc}")

    logger.info(
        f"[{era}/{channel}] {tff_process} {progress}{sample}: "
        f"{len(ntuple_files)} files -> reading"
    )
    chain = _chain_with_friend(ntuple_files, xsec_files, mask_files)

    _enable_mt(nthreads)
    rdf = ROOT.RDataFrame(chain)

    # ONE GetColumnNames() for the whole sample -- see _unqualified_columns.
    have = _unqualified_columns(rdf)

    rdf = _apply_preselection(
        rdf, event_selection, f"{tff_process}/{sample}",
        force_legacy=force_legacy_cuts, have=have,
    )

    if is_data:
        rdf = _define_weight(rdf, "1.0", have=have)
    else:
        rdf = _define_weight(rdf, _build_weight_expr(mc_weights, tff_process, era), have=have)
    have.add("weight")

    cols = _output_columns(rdf, era, channel, f"{tff_process}/{sample}",
                           have=have, keep_shifts=keep_shifts)

    lazy = ROOT.RDF.RSnapshotOptions()
    lazy.fLazy = True

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
    logger.info(
        f"[{era}/{channel}] {tff_process} {progress}{sample}: "
        f"{n_sample} events kept, {len(cols)} branches ({time.time() - t_sample:.0f}s)"
    )


def concatenate_background_process(
    *,
    tff_process: str,
    era: str,
    channel: str,
    flat_output_dir: str,
    samples: list,
    tau_gen_modes: list,
    nthreads: int,
) -> None:
    """Phase two: concatenate the per-sample temp files of one process into
    {flat_output_dir}/{process}[_{tau_gen_mode}].root and delete the temps.

    Which temps exist is discovered from disk rather than remembered in
    memory, so the sample jobs can have run anywhere (in-process or in worker
    subprocesses).
    """
    import helper.functions as tff_func

    _enable_mt(nthreads)
    lazy = ROOT.RDF.RSnapshotOptions()
    lazy.fLazy = True

    for mode in tau_gen_modes:
        files = [
            f for f in (
                tff_func.get_output_name(path=flat_output_dir, process=s, tau_gen_mode=mode)
                for s in samples
            )
            if os.path.exists(f)
        ]
        out_file = tff_func.get_output_name(path=flat_output_dir, process=tff_process, tau_gen_mode=mode)
        if files:
            # The temps were written with _output_columns(), so they carry the
            # shift branches too and the concatenation must keep them -- but it
            # can only keep the ones EVERY temp has: which systematic shifts a
            # CROWN sample carries depends on the sample, and a TChain over
            # files with different branch sets fails on the first file that is
            # missing one. Intersect (order fixed by the first file) and say so.
            cols, uniform = _common_columns(files, f"{tff_process}_{mode}")
            if uniform:
                # Identical trees -> hadd them. A raw basket copy, where the
                # RDataFrame route would decompress and recompress every one of
                # (with shifts) ~3400 branches and pay a ~50 s JIT for the
                # ~3400-column Snapshot template on top.
                n_written = _fast_merge(files, out_file)
            else:
                sum_rdf = ROOT.RDataFrame("ntuple", files)
                n_events = sum_rdf.Count()
                snap = sum_rdf.Snapshot("ntuple", out_file, cols, lazy)
                _run_graphs([n_events, snap])
                n_written = n_events.GetValue()
            logger.info(f"[{era}/{channel}] {tff_process}_{mode}: {n_written} events -> {out_file}")
        else:
            logger.info(f"[{era}/{channel}] No events for {tff_process}_{mode}, writing empty file -> {out_file}")
            f = ROOT.TFile(out_file, "RECREATE")
            t = ROOT.TTree("ntuple", "ntuple")
            t.Write()
            f.Close()
        for rf in files:
            os.remove(rf)


def _common_columns(files: list[str], label: str) -> tuple[list[str], bool]:
    """(branches present in EVERY one of `files`, are all the files identical?).

    Order follows the first file. Local files only (the per-sample temps), so
    this is a handful of cheap header reads -- no event data is touched.
    """
    per_file = []
    for path in files:
        fh = ROOT.TFile.Open(path)
        tree = fh.Get("ntuple")
        per_file.append([str(b.GetName()) for b in tree.GetListOfBranches()])
        fh.Close()
    if not per_file:
        return [], True
    common = set(per_file[0]).intersection(*(set(p) for p in per_file[1:]))
    dropped = sorted(set().union(*(set(p) for p in per_file)) - common)
    if dropped:
        logger.warning(
            f"{label}: {len(dropped)} branches are not in every sample of this "
            f"process and are dropped from the concatenation: {dropped[:10]}"
            f"{' ...' if len(dropped) > 10 else ''}"
        )
    return [c for c in per_file[0] if c in common], not dropped


def _fast_merge(files: list[str], out_file: str) -> int:
    """hadd `files` into `out_file` and return the merged entry count.

    TFileMerger in fast mode copies compressed baskets straight through, so
    merging costs the disk bandwidth and nothing else -- as opposed to an
    RDataFrame Snapshot, which decompresses and recompresses every branch of
    every event and JITs a Snapshot template as wide as the column list
    (~50 s alone at ~3400 columns; see _output_columns).

    Only valid when every input has the identical tree structure, which is
    what _common_columns()' second return value certifies.
    """
    # `hadd`, not TFileMerger in-process: with implicit MT already enabled this
    # process crashes inside TTree::FlushBasketsImpl's TBB parallel_for during
    # the merge. Out-of-process there is no such interaction, and hadd is the
    # exact same TFileMerger with sane defaults.
    proc = subprocess.run(["hadd", "-f", out_file, *files], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"hadd into {out_file} failed: {proc.stderr.strip()[-2000:]}")
    fh = ROOT.TFile.Open(out_file)
    n = int(fh.Get("ntuple").GetEntries())
    fh.Close()
    return n


def process_background_process(
    *,
    tff_process: str,
    era: str,
    channel: str,
    directory: str,
    xsec_friends: str,
    mask_friends: str,
    flat_output_dir: str,
    event_selection: dict,
    mc_weights: dict,
    samples: list,
    tau_gen_modes: list,
    nthreads: int,
    force_legacy_cuts: bool = False,
    keep_shifts: bool = True,
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
    process_signal_sample() below -- rather than TFF's own datasets.json
    sample database. Gen-mode splitting and output naming are delegated to
    TauFakeFactors' own helper.filters.tau_origin_split /
    helper.functions.get_output_name so the result is byte-layout-identical
    to a real TFF preselection.py run.

    Kept as the single-process entry point (used by the tests and by anything
    driving one process at a time); run_central_backgrounds() interleaves the
    sample jobs of ALL processes instead, for better load balance.
    """
    for i_sample, sample in enumerate(samples, start=1):
        preselect_background_sample(
            tff_process=tff_process, sample=sample, era=era, channel=channel,
            directory=directory, xsec_friends=xsec_friends, mask_friends=mask_friends,
            flat_output_dir=flat_output_dir, event_selection=event_selection,
            mc_weights=mc_weights, tau_gen_modes=tau_gen_modes, nthreads=nthreads,
            force_legacy_cuts=force_legacy_cuts, keep_shifts=keep_shifts,
            progress=f"[{i_sample}/{len(samples)}] ",
        )
    concatenate_background_process(
        tff_process=tff_process, era=era, channel=channel,
        flat_output_dir=flat_output_dir, samples=samples,
        tau_gen_modes=tau_gen_modes, nthreads=nthreads,
    )


def run_central_backgrounds(era: str, channel: str, directory: str, xsec_friends: str,
                             flat_output_dir: str, nthreads: int,
                             mask_friends: str = "",
                             force_legacy_cuts: bool = False,
                             nworkers: int = 1,
                             keep_shifts: bool = True) -> list[dict]:
    """Preselect every background process for one era/channel centrally into
    the TFF-native flat layout.

    Returns the list of per-sample job specs instead of running them, so the
    caller can run the background AND signal jobs through one shared pool (see
    main()); the per-process concatenation is done here afterwards.
    """
    os.makedirs(flat_output_dir, exist_ok=True)
    bg_processes = get_background_processes(era)

    jobs: list[dict] = []
    processes: list[tuple[str, list, list]] = []
    for tff_process, info in bg_processes.items():
        if tff_process == "data":
            samples = info.get("by_channel", {}).get(channel, [])
        else:
            samples = info.get("samples", [])
        tau_gen_modes = info.get("tau_gen_modes", ["all"])
        logger.info(f"[{era}/{channel}] Central preselection: {tff_process} ({len(samples)} samples, modes={tau_gen_modes})")
        processes.append((tff_process, samples, tau_gen_modes))
        jobs += [
            dict(kind="background", tff_process=tff_process, sample=sample,
                 era=era, channel=channel, directory=directory,
                 xsec_friends=xsec_friends, mask_friends=mask_friends,
                 output_dir=flat_output_dir, tau_gen_modes=tau_gen_modes,
                 nthreads=nthreads, force_legacy_cuts=force_legacy_cuts,
                 keep_shifts=keep_shifts)
            for sample in samples
        ]

    _run_jobs(jobs, nworkers)

    for tff_process, samples, tau_gen_modes in processes:
        concatenate_background_process(
            tff_process=tff_process, era=era, channel=channel,
            flat_output_dir=flat_output_dir, samples=samples,
            tau_gen_modes=tau_gen_modes, nthreads=nthreads,
        )
    return jobs


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
    mask_friends: str = "",
    event_selection: dict,
    mc_weights: dict,
    process: str,
    nthreads: int,
    force_legacy_cuts: bool = False,
    keep_shifts: bool = True,
) -> None:
    """Preselect + weight one signal sample into {output_dir}/{era}/{channel}/{sample}.root.

    Writes exactly the same column set as the background path -- see
    _output_columns(); "save ALL columns" is what this used to do and it was
    wrong in three separate ways (mangled xsec branch names, ~10k branches of
    pure I/O waste, and an outright segfault on the 2024 production).
    """

    # Signal is MC -- read ntuples/friends from the physical production-era
    # directory (may differ from the analysis `era`, e.g. 2026 borrowing
    # 2025's un-copied MC; see config.analysis.get_mc_ntuple_era). Output
    # still gets organised under the real analysis `era` below.
    mc_era = get_mc_ntuple_era(era)
    ntuple_files, ntuple_loc = _list_root_files(directory, mc_era, sample, channel)
    if not ntuple_files:
        logger.warning(f"No ntuple files for signal {sample}: {ntuple_loc}")
        return

    xsec_files: tuple = ()
    if xsec_friends:
        xsec_files, xsec_loc = _list_root_files(xsec_friends, mc_era, sample, channel)
        if not xsec_files:
            logger.warning(f"No xsec friend files for signal {sample}: {xsec_loc}")

    mask_files: tuple = ()
    if mask_friends:
        mask_files, mask_loc = _list_root_files(mask_friends, mc_era, sample, channel)
        if not mask_files:
            logger.warning(f"No mask friend files for signal {sample}: {mask_loc}")

    logger.info(f"[{era}/{channel}] signal {sample}: {len(ntuple_files)} files -> reading")
    chain = _chain_with_friend(ntuple_files, xsec_files, mask_files)

    _enable_mt(nthreads)
    rdf = ROOT.RDataFrame(chain)

    # ONE GetColumnNames() for the whole sample -- see _unqualified_columns.
    have = _unqualified_columns(rdf)

    # Apply the preselection (CROWN presel_mask when present, else legacy cuts)
    rdf = _apply_preselection(
        rdf, event_selection, f"signal/{sample}",
        force_legacy=force_legacy_cuts, have=have,
    )

    # Compute the event weight using TFF mc_weights (adapted for CROWN xsec columns)
    w_expr = _build_weight_expr(mc_weights, process, era)
    rdf = _define_weight(rdf, w_expr, have=have)
    have.add("weight")

    # Flat layout, same as backgrounds: one file per dataset key, named after
    # the key itself. build_presel_files_dict() maps each signal group (ggH,
    # qqH, ...) to its list of original per-sample names, so for signals the
    # "key" is the physical sample name (signals are not concatenated the way
    # backgrounds are).
    out_dir = os.path.join(output_dir, era, channel)
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"{sample}.root")

    # The SAME whitelist + masks + present shift branches the background path
    # writes, with friend qualification already stripped (_existing_columns and
    # _shift_columns work on the unqualified names, which Snapshot accepts and
    # writes under exactly that plain name).
    cols = _output_columns(rdf, era, channel, f"signal/{sample}",
                           have=have, keep_shifts=keep_shifts)

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
    logger.info(f"Saved {n_events} signal events [{sample}], {len(cols)} branches → {out_file} ({time.time() - t_sample:.0f}s)")


# ---------------------------------------------------------------------------
# Job execution (one job == one input sample)
# ---------------------------------------------------------------------------

def run_job(spec: dict) -> None:
    """Run ONE sample job in this process.

    `spec` is a plain-JSON description (see run_central_backgrounds() and
    main()) so the very same job can be handed to a worker subprocess.
    The cut/weight configuration is re-read from config here rather than
    shipped in the spec: it is derived purely from (era, channel) and reading
    it is microseconds.
    """
    era, channel = spec["era"], spec["channel"]
    event_selection = get_preselection_cuts(era, channel)
    mc_weights = get_mc_weights(era, channel)
    if spec["kind"] == "background":
        preselect_background_sample(
            tff_process=spec["tff_process"], sample=spec["sample"],
            era=era, channel=channel, directory=spec["directory"],
            xsec_friends=spec["xsec_friends"], mask_friends=spec["mask_friends"],
            flat_output_dir=spec["output_dir"], event_selection=event_selection,
            mc_weights=mc_weights, tau_gen_modes=spec["tau_gen_modes"],
            nthreads=spec["nthreads"], force_legacy_cuts=spec["force_legacy_cuts"],
            keep_shifts=spec["keep_shifts"],
        )
    elif spec["kind"] == "signal":
        process_signal_sample(
            sample=spec["sample"], era=era, channel=channel,
            directory=spec["directory"], xsec_friends=spec["xsec_friends"],
            mask_friends=spec["mask_friends"], output_dir=spec["output_dir"],
            event_selection=event_selection, mc_weights=mc_weights,
            process=spec["tff_process"], nthreads=spec["nthreads"],
            force_legacy_cuts=spec["force_legacy_cuts"], keep_shifts=spec["keep_shifts"],
        )
    else:
        raise ValueError(f"unknown job kind: {spec['kind']!r}")


def _run_jobs(jobs: list[dict], nworkers: int) -> None:
    """Run sample jobs, `nworkers` at a time.

    The step is almost entirely latency-bound remote I/O -- a single job leaves
    the CPU idle waiting on dCache most of the time -- so running several
    samples concurrently is the one change that scales the whole preselection,
    which used to be a strictly serial 54-iteration `for` loop over samples
    plus a serial loop over signals.

    Each job runs in a fresh WORKER SUBPROCESS (`--run-job`), not in a thread
    and not in a forked pool:

    * ROOT's implicit MT, the JIT and the XRootD client are all process-global;
      two RDataFrame event loops in one process would serialise on them and
      share one `EnableImplicitMT` setting.
    * forking a process that already has ROOT + XRootD threads running is the
      classic way to get a child stuck in a futex on its first remote read.
    * a crashing or hanging sample takes down only its own subprocess, and the
      exit-code shows up in the log instead of killing the whole preselection.

    nworkers=1 runs jobs inline in this process, which keeps the old behaviour
    for debugging (and makes tracebacks land where you expect).
    """
    if not jobs:
        return
    if nworkers <= 1:
        for i, spec in enumerate(jobs, start=1):
            logger.info(f"job [{i}/{len(jobs)}] {spec['kind']} {spec['tff_process']}/{spec['sample']}")
            run_job(spec)
        return

    env = dict(os.environ)
    # The worker is `python <this file>`, so it needs the same import roots the
    # parent got from however IT was started (run.py inserts the repo root and
    # TauFakeFactors/ into sys.path).
    env["PYTHONPATH"] = os.pathsep.join(
        [p for p in sys.path if p] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )

    def _one(indexed: tuple[int, dict]) -> tuple[dict, int]:
        i, spec = indexed
        label = f"{spec['kind']} {spec['tff_process']}/{spec['sample']}"
        logger.info(f"job [{i}/{len(jobs)}] start: {label}")
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--run-job", json.dumps(spec)],
            env=env,
        )
        logger.info(
            f"job [{i}/{len(jobs)}] done ({time.time() - t0:.0f}s, rc={proc.returncode}): {label}"
        )
        return spec, proc.returncode

    with ThreadPoolExecutor(max_workers=nworkers) as pool:
        results = list(pool.map(_one, enumerate(jobs, start=1)))

    failed = [s for s, rc in results if rc != 0]
    if failed:
        logger.error(
            f"{len(failed)}/{len(jobs)} preselection jobs FAILED: "
            + ", ".join(f"{s['tff_process']}/{s['sample']}" for s in failed)
        )


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
    # Not `required=True`: the internal --run-job mode carries everything it
    # needs in its JSON spec and is invoked with nothing else.
    parser.add_argument("--era",          default=None,   help="CMS era (e.g. 2022postEE).")
    parser.add_argument("--channel",      default=None,   help="Channel (et, mt, tt).")
    parser.add_argument("--output-dir",   default=None,
                        help="Preselection output base dir; files are written flat as "
                             "{output-dir}/{era}/{channel}/{key}.root "
                             "(build_shape_output_paths(ntupletag).preselection).")
    parser.add_argument("--directory",    default=None,   help="CROWN ntuple base dir.")
    parser.add_argument("--xsec-friends", default=None,   help="xsec friends base dir (MC weighting).")
    parser.add_argument("--mask-friends", default=None,
                        help="Selection-mask friends base dir, for productions where CROWN wrote "
                             "the masks (presel_mask, sel_os/sel_ss, ff_*) into a FRIEND tree "
                             "(selection_friends.py) instead of into the ntuple itself "
                             "(selection_config.py). Same {era}/{sample}/{channel} layout as "
                             "--xsec-friends. Leave unset for productions with the masks inside "
                             "the ntuple, or with no masks at all -- both keep working unchanged. "
                             "Env: MASK_FRIENDS_DIR (via run.py --mask-friends-dir).")
    parser.add_argument("--nthreads",     default=4, type=int, help="ROOT implicit MT threads per sample job.")
    parser.add_argument("--nworkers",     default=4, type=int,
                        help="How many sample jobs to run concurrently, each in its own worker "
                             "subprocess with --nthreads threads. The step is dominated by "
                             "latency-bound xrootd reads, so several jobs in flight is what makes "
                             "it finish; 1 runs everything serially in this process (debugging).")
    parser.add_argument("--no-shift-branches", action="store_true",
                        help="Write ONLY the nominal whitelist + selection masks, dropping the "
                             "`<base>__<shift>` systematic variations that are kept by default. "
                             "Those variations are what shape production's ReplaceVariable "
                             "systematics read -- but on the 2024 mt production they are ~3340 of "
                             "the ~3390 output branches and ~44%% of the input bytes (nominal: "
                             "0.6%%), measured at 1341 s for four background files against ~50 s "
                             "without. Keep them for signals; consider dropping them for the "
                             "background/data skim if you only need nominal shapes from it.")
    parser.add_argument("--run-job",      default=None,
                        help=argparse.SUPPRESS)  # internal: JSON spec of ONE sample job
    parser.add_argument("--skip-signals", action="store_true",
                        help="Skip signal processing (backgrounds/data only).")
    parser.add_argument("--skip-backgrounds", action="store_true",
                        help="Skip background/data processing (signals only).")
    parser.add_argument("--force-legacy-cuts", action="store_true",
                        help="Never use CROWN's precomputed `presel_mask` branch; always apply "
                             "the per-cut preselection loop from config/cuts.yaml, even when the "
                             "mask is present. Escape hatch for A/B validation of the two paths "
                             "(they must agree event-by-event) and for debugging a suspect mask.")
    args = parser.parse_args()
    if not args.run_job:
        missing = [f"--{n.replace('_', '-')}" for n in ("era", "channel", "output_dir", "directory")
                   if not getattr(args, n)]
        if missing:
            parser.error(f"the following arguments are required: {', '.join(missing)}")
    return args


def main():
    args = parse_args()

    # Internal worker mode: one sample, then exit (see _run_jobs).
    if args.run_job:
        run_job(json.loads(args.run_job))
        return

    # ── Backgrounds + data ─────────────────────────────────────────────────────
    if not args.skip_backgrounds:
        logger.info(f"[{args.era}/{args.channel}] Background preselection -> {args.output_dir}")
        run_central_backgrounds(
            era=args.era,
            channel=args.channel,
            directory=args.directory,
            xsec_friends=args.xsec_friends or "",
            mask_friends=args.mask_friends or "",
            flat_output_dir=os.path.join(args.output_dir, args.era, args.channel),
            nthreads=args.nthreads,
            force_legacy_cuts=args.force_legacy_cuts,
            nworkers=args.nworkers,
            keep_shifts=not args.no_shift_branches,
        )

    # ── Signals: process from CROWN ntuples ────────────────────────────────────
    if args.skip_signals:
        return

    era_signals = signal_files.get(args.era, {})
    if not era_signals:
        logger.info(f"No signals defined for era {args.era}, nothing to do.")
        return

    signal_jobs = [
        dict(kind="signal", tff_process=sig_key, sample=sample,
             era=args.era, channel=args.channel, directory=args.directory,
             xsec_friends=args.xsec_friends or "", mask_friends=args.mask_friends or "",
             output_dir=args.output_dir, nthreads=args.nthreads,
             force_legacy_cuts=args.force_legacy_cuts,
             keep_shifts=not args.no_shift_branches)
        for sig_key, sig_samples in era_signals.items()
        for sample in sig_samples
    ]
    _run_jobs(signal_jobs, args.nworkers)


if __name__ == "__main__":
    main()
    # Not a plain fall-through: see _exit_without_closing_remote_files().
    _exit_without_closing_remote_files(0)
