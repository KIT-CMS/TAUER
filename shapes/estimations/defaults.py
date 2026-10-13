from config.processes import BACKGROUNDS

# datacard name -> dataset key / process part of the histogram name, plus the NLO DY/W samples
_dataset_map = {"data": "data", **{p.datacard: p.dataset for p in BACKGROUNDS.values()},
                "ZTT_NLO": "DYNLO", "ZL_NLO": "DYNLO", "ZJ_NLO": "DYNLO", "W_NLO": "WNLO"}
_process_map = {"data": "data", **{p.datacard: p.datacard for p in BACKGROUNDS.values()},
                "ZTT_NLO": "ZTT", "ZL_NLO": "ZL", "ZJ_NLO": "ZJ", "W_NLO": "W"}

_name_string = "{dataset}#{channel}{process}{selection}#{variation}#{variable}"
