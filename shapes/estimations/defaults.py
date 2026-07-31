_dataset_map = {
    "data": "data",
    "ZTT": "DY",
    "ZL": "DY",
    "ZJ": "DY",
    "ZTT_NLO": "DYNLO",
    "ZL_NLO": "DYNLO",
    "ZJ_NLO": "DYNLO",
    "TTT": "TT",
    "TTL": "TT",
    "TTJ": "TT",
    "VVT": "VV",
    "VVL": "VV",
    "VVJ": "VV",
    "EMB": "EMB",
    "W": "W",
    "W_NLO": "WNLO",
    "qqH125": "qqH",
    "VH_as_qqH125": "VH",
}

_process_map = {
    "data": "data",
    "ZTT": "DY-ZTT",
    "ZL": "DY-ZL",
    "ZJ": "DY-ZJ",
    "ZTT_NLO": "DYNLO-ZTT",
    "ZL_NLO": "DYNLO-ZL",
    "ZJ_NLO": "DYNLO-ZJ",
    "TTT": "TT-TTT",
    "TTL": "TT-TTL",
    "TTJ": "TT-TTJ",
    "VVT": "VV-VVT",
    "VVL": "VV-VVL",
    "VVJ": "VV-VVJ",
    "EMB": "Embedded",
    "W": "W",
    "W_NLO": "W",
    "qqH125": "qqH125",
    # Same real selection-chain label ("qqH125") as the plain qqH125 process
    # above -- these two are distinguished by "dataset" (qqH vs VH), not by
    # this field, since both are literally selection.qqH125 applied to
    # different physical CROWN samples. See shapes/produce_shapes.py.
    "VH_as_qqH125": "qqH125",
}

_name_string = "{dataset}#{channel}{process}{selection}#{variation}#{variable}"
