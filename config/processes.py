"""
Single source of the background processes: the datacard name (also the process part of the booked histogram name), the
ntuple_processor dataset key and the groups the systematics of config/systematics.py are assigned to.
"""
from typing import NamedTuple


class Process(NamedTuple):
    datacard: str  # datacard/histogram process name, e.g. ZTT
    dataset: str  # ntuple_processor dataset key, e.g. DY


BACKGROUNDS = {
    "ztt": Process("ZTT", "DY"),
    "zl": Process("ZL", "DY"),
    "zj": Process("ZJ", "DY"),
    "ttt": Process("TTT", "TT"),
    "ttl": Process("TTL", "TT"),
    "ttj": Process("TTJ", "TT"),
    "vvt": Process("VVT", "VV"),
    "vvl": Process("VVL", "VV"),
    "vvj": Process("VVJ", "VV"),
    "w": Process("W", "W"),
    "emb": Process("EMB", "EMB"),
}

# stage0 signal keys -> dataset key (the STXS units of analyses/<analysis>/common/stxs_tools.py belong to these)
SIGNAL_DATASETS = {"ggh": "ggH", "qqh": "qqH", "tth": "ttH", "vh": "VH", "vh_as_qqh": "VH"}

# process groups of the simulated backgrounds, by sample and by origin of the hadronic tau (T/L/J)
GROUPS = {
    "z": ("ztt", "zl", "zj"),
    "ttbar": ("ttt", "ttl", "ttj"),
    "vv": ("vvt", "vvl", "vvj"),
    "w": ("w",),
    "real_tau": ("ztt", "ttt", "vvt"),
    "lep_fake": ("zl", "ttl", "vvl"),
    "jet_fake": ("zj", "ttj", "vvj", "w"),
}
GROUPS["mc_bkg"] = GROUPS["z"] + GROUPS["ttbar"] + GROUPS["vv"] + GROUPS["w"]
# simulated processes subtracted from data in the anti-isolated region of the fake factor method
GROUPS["ff_subtraction"] = GROUPS["real_tau"] + GROUPS["lep_fake"]


def expand(keys) -> list:
    """Background shape keys of a mix of shape keys and groups; other keys (signal, jetFakes, qcd, data) are kept."""
    out = []
    for key in keys:
        for item in GROUPS.get(key, (key,)):
            if item not in out:
                out.append(item)
    return out


def datacard_backgrounds(channel: str, embedding: bool = False, jetfakes: bool = True) -> list:
    """Datacard background processes: the simulated ones, the jet fakes folded into jetFakes with the fake factors,
    the genuine taus replaced by EMB with embedding."""
    keys = list(GROUPS["mc_bkg"])
    if embedding:
        keys = [k for k in keys if k not in GROUPS["real_tau"]] + ["emb"]
        if channel == "em":
            keys = [k for k in keys if k not in GROUPS["jet_fake"] or k == "w"]
    names = [BACKGROUNDS[k].datacard for k in keys]
    if jetfakes:
        names = [n for n in names if n not in {BACKGROUNDS[k].datacard for k in GROUPS["jet_fake"]}] + ["jetFakes"]
    elif embedding:
        names.append("QCD")
    return names
