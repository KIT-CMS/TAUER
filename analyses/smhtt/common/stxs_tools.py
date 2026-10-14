import hashlib
import json
import logging
import multiprocessing as mp
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import uproot
import yaml
from XRootD.client import File
from tqdm import tqdm

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

REPO_ROOT = Path(__file__).resolve().parents[3]
RECS_DIR = Path(os.environ.get(
    "STXS_RECOMMENDATIONS_DIR",
    REPO_ROOT.parent / "KingMaker/CROWN/data/htxs/stxs-run3-recommendations",
))
NNLOPS_FILE = RECS_DIR.parents[0] / "NNLOPS_reweight.root"
NICK_TABLE = REPO_ROOT / "sample_database/aux_data/stxs_nick_table.json"
LHE_SCALE_TABLE = REPO_ROOT / "sample_database/aux_data/stxs_lhe_scale_table.json"
MH = 125.08
XROOTD_SERVERS = ["root://cmsdcache-kit-disk.gridka.de", "root://xrootd-cms.infn.it", "root://cms-xrd-global.cern.ch"]

# B(H->tautau), B(H->bb) from BR4.txt (LHCHWG YR4), linearly interpolated to MH
_BR = {125.0: {"htt": 6.272e-2, "hbb": 5.824e-1}, 125.09: {"htt": 6.256e-2, "hbb": 5.809e-1}}
# generator-filter efficiency per family, AN2025_055 Table 12 (ttH is unfiltered)
FILTER_EFFICIENCY = {"ggH": 0.3869, "VBF": 0.4216, "WPLUSH": 0.3582, "WMINUSH": 0.3869, "ZH": 0.4030, "ttH": 1.0}

# sample family -> (code written to the ntuple friend as stxs_family, [(process, first HTXS bin)])
FAMILIES = {
    "ggH": (1, [("GG2H", 100)]),
    "VBF": (2, [("VBF", 200)]),
    "WPLUSH": (3, [("WPLUSH2HQQ", 200), ("WPLUSH2HLNU", 300)]),
    "WMINUSH": (4, [("WMINUSH2HQQ", 200), ("WMINUSH2HLNU", 300)]),
    "ZH": (5, [("ZH2HQQ", 200), ("ZH2HLEPLEP", 400)]),
    "ttH": (6, [("TTH", 600)]),
}
_FAMILY_NICK = (
    ("ggH", r"^GluGluH"), ("VBF", r"^VBFH"), ("WPLUSH", r"^WplusH"), ("WMINUSH", r"^WminusH"),
    ("ZH", r"^ZH"), ("ttH", r"^TTH-?H?(to)?Non2B"),
)
_FILTERED = re.compile(r"Filtered|Fil-TauFilter")
_RENANO = re.compile(r"ReNano")
# production mode of the datacard's stage-0 signal each process belongs to
STAGE0_GROUP = {"GG2H": "ggH", "VBF": "qqH", "TTH": "ttH"}


def family_of_nick(nick: str):
    return next((fam for fam, pat in _FAMILY_NICK if re.search(pat, nick)), None)


def stage0_group(process: str) -> str:
    return STAGE0_GROUP.get(process, "qqH" if process.endswith("2HQQ") else "VH")


def _read_xlsx(path) -> dict:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(path)
    strings = [''.join(t.text or '' for t in si.iter(ns + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    names = [s.get("name") for s in ET.fromstring(z.read("xl/workbook.xml")).iter(ns + "sheet")]
    sheets = {}
    for i, name in enumerate(names, 1):
        rows = []
        for row in ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml")).iter(ns + "row"):
            vals = [c.find(ns + "v") for c in row]
            rows.append([None if v is None else (strings[int(v.text)] if c.get("t") == "s" else float(v.text)) for c, v in zip(row, vals)])
        sheets[name] = rows[1:]
    return sheets


@lru_cache(maxsize=None)
def _recommendations() -> dict:
    data = RECS_DIR / "data"
    xsec = {p: sorted((mh, xs) for mh, xs, *_ in rows if mh is not None and xs is not None) for p, rows in _read_xlsx(data / "SM_Higgs_XS_13p6TeV.xlsx").items()}
    fractions = {p: {name: frac for name, frac, *_ in rows} for p, rows in _read_xlsx(data / "STXS_fractions_13p6TeV.xlsx").items()}
    return {
        "xsec": xsec, "fractions": fractions,
        "thu": json.loads((data / "thu_norm_stxs1p2.json").read_text()),
        "lhe_scale": json.loads((data / "lhe_scale_np_scheme.json").read_text()),
    }


def xsec(process: str, mh: float = MH) -> float:
    pts = _recommendations()["xsec"][process]
    return float(np.interp(mh, [p[0] for p in pts], [p[1] for p in pts]))


def branching_ratio(decay: str, mh: float = MH) -> float:
    (m0, b0), (m1, b1) = sorted(_BR.items())
    return b0[decay] + (b1[decay] - b0[decay]) * (mh - m0) / (m1 - m0)


def stxs_bins(process: str) -> dict:
    """HTXS stage-1.2 integer -> `<PROCESS>_<STXS_BIN>` name for every bin of a recommended process."""
    first = dict(p for _, procs in FAMILIES.values() for p in procs)[process]
    return {first + i: name for i, name in enumerate(_recommendations()["fractions"][process])}


@lru_cache(maxsize=None)
def _name_info() -> dict:
    """`<PROCESS>_<STXS_BIN>` -> (family, process, HTXS bin) for every recommended signal model."""
    return {name: (fam, process, htxs_bin) for fam, (_, procs) in FAMILIES.items() for process, _ in procs for htxs_bin, name in stxs_bins(process).items()}


def member_cut(name: str) -> str:
    """Cut on the CROWN friend's stxs_family and the HTXS bin selecting one `<PROCESS>_<STXS_BIN>`."""
    fam, _, htxs_bin = _name_info()[name]
    return f"(stxs_family=={FAMILIES[fam][0]})&&(HTXS_stage1_2_cat_pTjet30GeV=={htxs_bin})"


_DATASET = {"ggH": "ggH", "VBF": "qqH", "WPLUSH": "VH", "WMINUSH": "VH", "ZH": "VH", "ttH": "ttH"}
# produce_shapes process key of a recommended process, EW qqH = VBF + hadronic-V-associated production
_PROCESS_KEY = lambda process: {"GG2H": "ggh", "VBF": "qqh", "TTH": "tth"}.get(process, "qqh" if process.endswith("2HQQ") else "vh")
_HTXS = "HTXS_stage1_2_cat_pTjet30GeV"


@lru_cache(maxsize=None)
def signal_units(stage: str) -> dict:
    """Booked signal units (stage0: per production mode, stage1p2: per `<PROCESS>_<STXS_BIN>`): key, datasets, selection, cut, members, group."""
    info = _name_info()
    if stage == "stage1p2":
        return {name: {"key": _PROCESS_KEY(process), "datasets": (_DATASET[fam],), "selection": f"{name}__13p6TeV__htt", "cut": member_cut(name),
                       "members": [name], "group": stage0_group(process)} for name, (fam, process, _) in info.items()}
    if stage != "stage0":
        raise ValueError(f"Unknown STXS stage {stage!r}")
    units = {}
    for key, datasets, selection, cut, group, fams in (
        ("ggh", ("ggH",), "ggH_htt125", f"(({_HTXS}>=100)&&({_HTXS}<=116))", "ggH", ("ggH",)),
        ("qqh", ("qqH", "VH"), "qqH_htt125", f"(({_HTXS}>=200)&&({_HTXS}<=210))", "qqH", ("VBF", "WPLUSH", "WMINUSH", "ZH")),
        ("vh", ("VH",), "VH_htt125", f"(({_HTXS}>=300)&&({_HTXS}<=505))", "VH", ("WPLUSH", "WMINUSH", "ZH")),
        ("tth", ("ttH",), "ttH_htt125", None, "ttH", ("ttH",)),
    ):
        members = [n for n, (fam, process, _) in info.items() if fam in fams and _PROCESS_KEY(process) == key]
        units[key] = {"key": key, "datasets": datasets, "selection": selection, "cut": cut, "members": members, "group": group}
    return units


def group_members(stage: str) -> dict:
    """Datacard signal process -> `<PROCESS>_<STXS_BIN>` models it holds (stage0: ggH, qqH, VH, ttH; stage1p2: itself)."""
    groups = {}
    for unit in signal_units(stage).values():
        groups.setdefault(unit["group"] if stage == "stage0" else unit["members"][0], []).extend(unit["members"])
    return groups


def thu_values() -> dict:
    """`<PROCESS>_<STXS_BIN>` -> {systematic: (down, up)} lnN from thu_norm_stxs1p2.json, '-' entries dropped."""
    result = {}
    for name, nps in _recommendations()["thu"]["values"].items():
        result[name] = {}
        for np_name, val in nps.items():
            if val != "-":
                down, _, up = val.partition("/")
                result[name][np_name] = (float(down), float(up or down))
    return result


def thu_lnN(members: list) -> dict:
    """THU systematic -> (down, up) lnN of a datacard process: member values averaged with the recommended sigma x fraction (1 where absent)."""
    values, info, fractions = thu_values(), _name_info(), _recommendations()["fractions"]
    weight = {m: xsec(info[m][1]) * fractions[info[m][1]][m] for m in members}
    lnN = {}
    for np_name in sorted({n for m in members for n in values[m]}):
        down, up = (sum(weight[m] * values[m].get(np_name, (1.0, 1.0))[i] for m in members) / sum(weight.values()) for i in (0, 1))
        if abs(down - 1.0) > 1e-9 or abs(up - 1.0) > 1e-9:
            lnN[np_name] = (down, up)
    return lnN


def lhe_scale_systematics(members: list) -> dict:
    """LHEScaleWeight systematic -> the members of this unit it applies to, empty systematics dropped."""
    result = {np_name: [m for m in members if m in names] for np_name, names in lhe_scale_scheme().items()}
    return {np_name: hit for np_name, hit in result.items() if hit}


def lhe_scale_scheme() -> dict:
    """LHEScaleWeight systematic -> list of `<PROCESS>_<STXS_BIN>` it applies to."""
    return _recommendations()["lhe_scale"]


def write_lhe_scale_table(output_path: str = str(LHE_SCALE_TABLE)) -> dict:
    """LHEScaleWeight systematic -> [[stxs_family code, HTXS bin], ...] it applies to, read by CROWN's STXSLheScale."""
    info = _name_info()
    table = {np_name: [[FAMILIES[info[n][0]][0], info[n][2]] for n in names if n in info] for np_name, names in lhe_scale_scheme().items()}
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    json.dump(table, open(output_path, "w"), indent=1, sort_keys=True)
    return table


@lru_cache(maxsize=None)
def _nnlops_graphs(generator: str = "powheg"):
    with uproot.open(NNLOPS_FILE) as f:
        return [tuple(np.asarray(f[f"gr_NNLOPSratio_pt_{generator}_{n}jet"].member(m)) for m in ("fX", "fY")) for n in range(4)]


def nnlops_weight(pth, njets, generator: str = "powheg"):
    """numpy twin of htxs::ggHNNLOWeights (CROWN src/htxs.cxx)."""
    cutoff = np.array([125.0, 625.0, 800.0, 925.0])
    nj = np.minimum(3, njets)
    pt = np.minimum(pth, cutoff[nj])
    graphs = _nnlops_graphs(generator)
    return np.select([nj == n for n in range(4)], [np.interp(pt, *graphs[n]) for n in range(4)])


def _scan_file(args):
    for attempt in range(3):
        try:
            return _scan_file_once(args)
        except Exception as exc:
            logger.warning(f"{args[0]} attempt {attempt + 1}: {exc}")
    raise RuntimeError(f"unreadable file {args[0]}")


def _scan_file_once(args):
    """Per-bin pre-selection sums of one nanoAOD file: events, sign, NNLOPS-weighted sign, LHEScale nominal/up/down."""
    import ROOT
    path, is_ggh = args
    # as KingMaker's get_alternate_file_uri: first server that has the file
    m = re.match(r"^root://[^/]+/+(.+)$", path)
    path = next((uri for srv in XROOTD_SERVERS if m and (uri := f"{srv}///{m[1]}") and File().open(uri)[0].ok), path)
    df = (ROOT.RDataFrame("Events", path)
          .Define("sgn", "genWeight > 0 ? 1.0 : -1.0")
          .Define("sc_nom", "LHEScaleWeight.size() == 9 ? (double)LHEScaleWeight[4] : 1.0")
          .Define("sc_up", "LHEScaleWeight.size() >= 8 ? (double)LHEScaleWeight[LHEScaleWeight.size() - 1] : 1.0")
          .Define("sc_down", "LHEScaleWeight.size() >= 8 ? (double)LHEScaleWeight[0] : 1.0"))
    arr = df.AsNumpy(["sgn", "sc_nom", "sc_up", "sc_down", "HTXS_stage1_2_cat_pTjet30GeV"] + (["HTXS_Higgs_pt", "HTXS_njets30"] if is_ggh else []))
    sign, cat = arr["sgn"], arr["HTXS_stage1_2_cat_pTjet30GeV"]
    corr = nnlops_weight(arr["HTXS_Higgs_pt"], arr["HTXS_njets30"].astype(int)) if is_ggh else np.ones(len(sign))
    sums = {}
    for b in np.unique(cat):
        m = cat == b
        sums[int(b)] = [m.sum(), sign[m].sum(), (sign * corr)[m].sum(), (sign * arr["sc_nom"])[m].sum(), (sign * arr["sc_up"])[m].sum(), (sign * arr["sc_down"])[m].sum()]
    return sums


def scan_nick(files, is_ggh, n_workers):
    """Sum _scan_file over all files -> {bin: [n_raw, sum_sign, sum_sign_corr, sum_nom, sum_up, sum_down]}."""
    total = {}
    with mp.Pool(n_workers) as pool:
        for sums in tqdm(pool.imap_unordered(_scan_file, [(f, is_ggh) for f in files]), total=len(files)):
            for b, vals in sums.items():
                total[b] = np.add(total.get(b, np.zeros(6)), vals)
    return total


SIGNAL_SAMPLE_TYPES = ("ggh_htautau", "vbf_htautau", "rem_htautau", "rem_higgs")


def _br_eps(fam: str, nick: str):
    """(B, eps_F) of a signal sample: the ttH sample is inclusive over decays except bb, the others are H->tautau."""
    return (1.0 - branching_ratio("hbb") if fam == "ttH" else branching_ratio("htt")), (FILTER_EFFICIENCY[fam] if _FILTERED.search(nick) else 1.0)


def nick_xsec(nick: str) -> float:
    """Recommended xsec x B x eps_F (pb) of a signal sample at MH=125.08."""
    fam = family_of_nick(nick)
    br, eps = _br_eps(fam, nick)
    return sum(xsec(p) for p, _ in FAMILIES[fam][1]) * br * eps


def _write_json_like(path: Path, text: str, data) -> None:
    out = json.dumps(data, indent=4)
    path.write_text(out + "\n" if text.endswith("\n") else out)


def update_sample_database(roots) -> None:
    """Set the xsec of every Run 3 signal sample in the datasets.json and per-sample json files of the given sample database roots."""
    for root in map(Path, roots):
        for datasets_path in sorted(root.glob("nanoAOD_v1[25]/datasets.json")):
            text = datasets_path.read_text()
            datasets = json.loads(text)
            changed = 0
            for entry in datasets.values():
                if entry["sample_type"] not in SIGNAL_SAMPLE_TYPES or not family_of_nick(entry["nick"]) or int(str(entry["era"])[:4]) < 2022:
                    continue
                new = nick_xsec(entry["nick"])
                if entry["xsec"] != new:
                    entry["xsec"] = new
                    changed += 1
                nick_path = datasets_path.parent / entry["era"] / entry["sample_type"] / f"{entry['nick']}.json"
                if nick_path.exists():
                    nick_text = nick_path.read_text()
                    nick_data = json.loads(nick_text)
                    if nick_data["xsec"] != new:
                        nick_data["xsec"] = new
                        _write_json_like(nick_path, nick_text, nick_data)
            if changed:
                _write_json_like(datasets_path, text, datasets)
            logger.info(f"{datasets_path}: updated xsec of {changed} signal samples")


def signal_nicks(signals_yaml: str = str(REPO_ROOT / "analyses/smhtt/config/signals.yaml"), eras=None):
    """(nick -> (family, dbs, sample json), wanted nicks) of the Run 3 signal samples of signals.yaml (restricted to `eras`) to scan."""
    wanted = {n for era_signals in yaml.safe_load(open(signals_yaml))["signals"].items() if not eras or era_signals[0] in eras
              for nicks in era_signals[1].values() for n in nicks}
    nicks, renano = {}, set()
    for ds in (REPO_ROOT / "sample_database").glob("nanoAOD_v1[25]/datasets.json"):
        for entry in json.load(open(ds)).values():
            # Run 3 samples only: the recommendations are 13.6 TeV, the Run 2 nicks must not enter the pooled bin fractions
            if int(entry["era"][:4]) >= 2022 and (fam := family_of_nick(entry["nick"])) and entry["sample_type"] in ("ggh_htautau", "vbf_htautau", "rem_htautau", "rem_higgs"):
                nicks[entry["nick"]] = (fam, entry["dbs"], Path(ds).parent / entry["era"] / entry["sample_type"] / f"{entry['nick']}.json")
                renano.add((fam, entry["era"], bool(_RENANO.search(entry["nick"]))))
    # unfiltered nicks outside the signals are scanned only to pool the f_MC: skip 2025 (copy of 2024), non-ReNano ones where a ReNano exists
    return {n: v for n, v in nicks.items() if n in wanted or (not _FILTERED.search(n) and "ToTauTau" not in n and "/2025/" not in str(v[2])
            and not (not _RENANO.search(n) and (v[0], v[2].parent.parent.name, True) in renano))}, wanted


def dbs_files(nicks: dict, max_files: int = None, max_files_unfiltered: int = None) -> dict:
    """dbs -> (family, nanoAOD files to scan), the same files for every nick of a dataset."""
    result = {}
    for nick, (fam, dbs, jpath) in nicks.items():
        if dbs not in result:
            result[dbs] = (fam, json.load(open(jpath))["filelist"][:max_files if _FILTERED.search(nick) else max_files_unfiltered])
    return result


def _scan_key(dbs: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", dbs.strip("/"))[:60] + "_" + hashlib.md5(dbs.encode()).hexdigest()[:8]


def scan_chunk(dbs: str, start: int, stop: int, scan_dir: str) -> None:
    """Scans the files start:stop of a dataset and writes the per-bin sums of `scan_nick` to scan_dir, for condor jobs."""
    fam, files = dbs_files(signal_nicks()[0])[dbs]
    files = files[start:stop]
    sums = scan_nick(files, fam == "ggH", 1)
    os.makedirs(scan_dir, exist_ok=True)
    json.dump({"dbs": dbs, "start": start, "stop": start + len(files), "sums": {str(b): list(map(float, v)) for b, v in sums.items()}},
              open(Path(scan_dir) / f"{_scan_key(dbs)}__{start}_{stop}.json", "w"))


def load_scan(scan_dir: str, dbs: str, n_files: int) -> dict:
    """Sums the chunks of a dataset in scan_dir, which have to cover its n_files files."""
    chunks = [json.load(open(path)) for path in sorted(Path(scan_dir).glob(f"{_scan_key(dbs)}__*.json"))]
    missing = sorted(set(range(n_files)) - {i for c in chunks for i in range(c["start"], c["stop"])})
    if missing:
        raise ValueError(f"{dbs}: the scan chunks of {scan_dir} miss {len(missing)} of {n_files} files, e.g. file {missing[0]}")
    total = {}
    for chunk in chunks:
        for b, vals in chunk["sums"].items():
            total[int(b)] = np.add(total.get(int(b), np.zeros(6)), vals)
    return total


def calculate_stxs_nick_table(
    signals_yaml: str = str(REPO_ROOT / "analyses/smhtt/config/signals.yaml"),
    output_path: str = str(NICK_TABLE),
    eras=None,
    max_files: int = None,
    max_files_unfiltered: int = None,
    n_workers: int = 20,
    scan_dir: str = None,
) -> dict:
    """Per signal nick: family code, xsec*B*eps_F (pb) and per HTXS bin [norm, LHEScale R_up, R_down] for CROWN's STXSNormalization.
    The nanoAOD scan is read from the chunks of `scan_dir` (see scan_chunk) instead of being done here if given."""
    nicks, wanted = signal_nicks(signals_yaml, eras)
    selected = dbs_files(nicks, max_files, max_files_unfiltered)
    scans, by_dbs = {}, {}
    for nick, (fam, dbs, jpath) in nicks.items():
        if dbs not in by_dbs:
            files = selected[dbs][1]
            logger.info(f"{'Loading the scan of' if scan_dir else 'Scanning'} {nick} ({len(files)} files)")
            by_dbs[dbs] = load_scan(scan_dir, dbs, len(files)) if scan_dir else scan_nick(files, fam == "ggH", n_workers)
        scans[nick] = by_dbs[dbs]

    pooled, seen = {}, set()
    for nick, (fam, dbs, _) in nicks.items():
        if not _FILTERED.search(nick) and dbs not in seen:
            seen.add(dbs)
            for b, vals in scans[nick].items():
                pooled.setdefault(fam, {}).setdefault(b, np.zeros(6))
                pooled[fam][b] = pooled[fam][b] + vals
    rec = _recommendations()
    table = {}
    for nick, (fam, *_) in nicks.items():
        if nick not in wanted:
            continue
        code, procs = FAMILIES[fam]
        scan = scans[nick]
        br, eps = _br_eps(fam, nick)
        total_mc = sum(v[1] for v in pooled.get(fam, scan).values())
        sigma_nick = sum(xsec(p) for p, _ in procs) * br * eps
        bins = {}
        for process, first in procs:
            for htxs_bin, name in stxs_bins(process).items():
                ref = pooled.get(fam, scan).get(htxs_bin)
                f_mc = ref[2] / total_mc if ref is not None and ref[0] >= 10 else None
                f_rec = rec["fractions"][process][name]
                target = xsec(process) * br * eps * f_rec
                norm = target / ((f_mc or f_rec) * sigma_nick)
                s = scan.get(htxs_bin)
                r_up, r_down = (s[4] / s[3], s[5] / s[3]) if s is not None and s[3] > 0 else (1.0, 1.0)
                bins[str(htxs_bin)] = [float(norm), float(r_up), float(r_down)]
        table[nick] = {"family": code, "xsec": float(sigma_nick), "bins": bins}
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    json.dump(table, open(output_path, "w"), indent=1, sort_keys=True)
    logger.info(f"Wrote {len(table)} nicks to {output_path}")
    return table


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build the per-nick STXS normalisation table read by CROWN's build_norm_table.")
    parser.add_argument("--eras", nargs="*", default=None)
    parser.add_argument("--max-files", type=int, default=None, help="Scan only the first N files of each filtered nick.")
    parser.add_argument("--max-files-unfiltered", type=int, default=None, help="Scan only the first N files of each unfiltered nick.")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--output-file", default=str(NICK_TABLE))
    parser.add_argument("--update-sample-database", nargs="+", metavar="ROOT", help="Only write the recommended xsec of the signal samples into these sample database roots.")
    parser.add_argument("--scan-chunk", nargs=3, metavar=("DBS", "START", "STOP"), help="Only scan the files START:STOP of a dataset into --scan-dir (condor job).")
    parser.add_argument("--scan-dir", default=None, help="Directory of the scan chunks: written by --scan-chunk, read to calculate the table instead of scanning it.")
    parser.add_argument("--lhe-scale-table", action="store_true", help="Only write the LHEScaleWeight systematic table read by CROWN's STXSLheScale.")
    cli = parser.parse_args()
    if cli.lhe_scale_table:
        write_lhe_scale_table()
        raise SystemExit
    if cli.update_sample_database:
        update_sample_database(cli.update_sample_database)
        raise SystemExit
    if cli.scan_chunk:
        scan_chunk(cli.scan_chunk[0], int(cli.scan_chunk[1]), int(cli.scan_chunk[2]), cli.scan_dir)
        raise SystemExit
    calculate_stxs_nick_table(eras=cli.eras, max_files=cli.max_files, max_files_unfiltered=cli.max_files_unfiltered, n_workers=cli.workers, output_path=cli.output_file, scan_dir=cli.scan_dir)
