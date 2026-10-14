from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, List, Optional, Tuple

from config.analysis import ACTIVE_ANALYSIS
from config.logging_setup_configs import setup_logging
from config.systematics import systematics
from config.processes import BACKGROUNDS, expand

_analysis_systematics = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.datacards.systematics")

if TYPE_CHECKING:
    import CombineHarvester.CombineTools.ch as ch


logger = setup_logging(logger=logging.getLogger(__name__))


class Channels:
    all = ["et", "mt", "tt", "em"]
    lt = ["et", "mt"]
    mt_tt = ["mt", "tt"]
    em_et = ["em", "et"]
    em_mt = ["em", "mt"]
    tt = ["tt"]
    em = ["em"]


class Processes:
    """Datacard process names of the signal groups (analysis specific) and of the special estimates."""
    def __init__(self, run2: bool = False, stxs_stage: str = "stage0") -> None:
        signal = _analysis_systematics.signal_processes(run2=run2, stage=stxs_stage)
        self.ggH, self.ggZH_had, self.qqH = signal["ggH"], signal["ggZH_had"], signal["qqH"]
        self.VH_had, self.VH, self.ttH = signal["VH_had"], signal["VH"], signal["ttH"]
        self.signals = self.ggH + self.ggZH_had + self.qqH + self.VH_had + self.VH + self.ttH
        self.htt = self.signals
        self.emb = ["EMB"]
        self.qcd = ["QCD"]
        self.jetFakes = ["jetFakes"]

    def resolve(self, keys) -> list:
        """Datacard names of the shape keys/groups of config/processes.py and of the special keys."""
        special = {"signal": self.signals, "jetFakes": self.jetFakes, "qcd": self.qcd, "data": []}
        return [name for key in expand(keys) for name in special.get(key, [BACKGROUNDS[key].datacard] if key in BACKGROUNDS else [])]


def add_systematics(
    cb: Optional[ch.CombineHarvester],
    era: str,
    jetfakes: bool = True,
    embedding: bool = True,
    correlate_emb: bool = True,
    stxs_stage: str = "stage0",
    qcd: bool = True,
    ff_ml: bool = False,
    shape_systematics: bool = True,
    record: Optional[List[Tuple[str, str, Tuple[str, ...], Tuple[str, ...]]]] = None,
) -> None:
    """Add the systematics of config/systematics.py plus the analysis signal and embedding ones. With cb=None only
    `record` is filled with (name, type, processes, channels)."""
    logger.debug(f"calling add_systematics {locals()}")
    channels, processes = Channels(), Processes(run2=int(era[:4]) < 2022, stxs_stage=stxs_stage)

    def add_syst(name, syst_type, procs, chans, value=1.0):
        if syst_type == "shape" and not shape_systematics:
            logger.debug(f"Skipping shape systematic {name} (shape systematics disabled)")
            return
        logger.debug(f"Adding systematic {name} of type {syst_type} to processes {procs} in channels {chans} with value/map {value}")
        if record is not None:
            record.append((name, syst_type, tuple(procs), tuple(chans)))
        if cb is not None:
            import CombineHarvester.CombineTools.ch as ch

            if isinstance(value, (float, int)):
                syst_map = ch.SystMap()(float(value))
            elif isinstance(value, tuple):
                syst_map = ch.SystMapAsymm()(*value)
            else:
                syst_map = value
            cb.cp().process(list(procs)).channel(list(chans)).AddSyst(cb, name, syst_type, syst_map)

    for syst in systematics(era, jetfakes=jetfakes, qcd=qcd, ff_ml=ff_ml):
        add_syst(syst.name, syst.kind, processes.resolve(syst.processes), syst.channels, syst.value)

    _analysis_systematics.add_signal_systematics(add_syst, processes, channels, stxs_stage)

    if embedding:
        _analysis_systematics.add_embedding_systematics(add_syst, processes, channels, era, correlate_emb, jetfakes)
