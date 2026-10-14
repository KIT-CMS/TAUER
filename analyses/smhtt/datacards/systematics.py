from analyses.smhtt.common import stxs_tools
from config.systematics import ERA_TAG


def datacard_signal(name: str, stage: str) -> str:
    """Datacard process name: legacy `<mode>_htt` for stage0, `<PROCESS>_<STXS_BIN>__13p6TeV__htt` for stage1p2."""
    return f"{name}_htt" if stage == "stage0" else f"{name}__13p6TeV__htt"


def get_signals(stxs_stage: str = "stage0") -> list:
    if stxs_stage not in ("stage0", "stage1p2"):
        raise ValueError(f"Unknown STXS stage: {stxs_stage}")
    return [datacard_signal(name, stxs_stage) for name in stxs_tools.group_members(stxs_stage)]


DM_LABEL_TO_CODE = {
    "1prong0pizero": "dm0",
    "1prong1pizero": "dm1",
    "3prong0pizero": "dm10",
    "3prong1pizero": "dm11",
}
DM_LABEL_TO_TAUES_GROUP = {
    "1prong0pizero": "1prong",
    "1prong1pizero": "1prong1pizero",
    "3prong0pizero": "3prong",
    "3prong1pizero": "3prong1pizero",
}


def add_embedding_systematics(add_syst, processes, channels, era: str, correlate_emb: bool, jetfakes: bool) -> None:
    era_tag = ERA_TAG[era]
    add_syst(f"CMS_eff_trigger_emb_em_{era_tag}", "lnN", processes.emb, channels.em, 1.02)
    add_syst(f"CMS_eff_t_emb_wp_{era_tag}", "lnN", processes.emb, channels.mt_tt, 1.03)
    add_syst("CMS_scale_e_emb", "shape", processes.emb, channels.em_et)

    if correlate_emb:
        add_syst("CMS_eff_e", "lnN", processes.emb, channels.em_et, 1.01)
        add_syst("CMS_eff_m", "lnN", processes.emb, channels.em_mt, 1.01)
        add_syst("CMS_eff_e_emb", "lnN", processes.emb, channels.em_et, 1.017)
        add_syst("CMS_eff_m_emb", "lnN", processes.emb, channels.em_mt, 1.017)
    else:
        add_syst("CMS_eff_e_emb", "lnN", processes.emb, channels.em_et, 1.02)
        add_syst("CMS_eff_m_emb", "lnN", processes.emb, channels.em_mt, 1.02)

    for pt_bin in ["30-35", "35-40", "40-500", "500-1000", "1000-Inf"]:
        if pt_bin == "1000-Inf":
            continue
        emb_pt_bin = "40-Inf" if pt_bin == "40-500" else pt_bin
        add_syst(f"CMS_eff_t_emb_{emb_pt_bin}_{era_tag}", "shape", processes.emb, channels.lt)
    for dm_code in DM_LABEL_TO_CODE.values():
        add_syst(f"CMS_eff_t_emb_{dm_code}_{era_tag}", "shape", processes.emb, channels.tt)

    for taues_group in DM_LABEL_TO_TAUES_GROUP.values():
        if correlate_emb:
            add_syst(f"CMS_scale_t_{taues_group}_{era_tag}", "shape", processes.emb, channels.lt)
        add_syst(f"CMS_scale_t_emb_{taues_group}_{era_tag}", "shape", processes.emb, channels.lt)
        if jetfakes:
            add_syst(f"CMS_scale_t_emb_{taues_group}_{era_tag}", "shape", processes.jetFakes, channels.lt)

    add_syst(f"CMS_htt_doublemutrg_{era_tag}", "lnN", processes.emb, channels.all, 1.04)
    add_syst(f"CMS_htt_emb_ttbar_{era_tag}", "shape", processes.emb, channels.all)


def signal_processes(run2: bool = False, stage: str = "stage0") -> dict:
    if not run2 and stage == "stage1p2":
        groups = {}
        for unit in stxs_tools.signal_units(stage).values():
            groups.setdefault(unit["group"], []).append(datacard_signal(unit["members"][0], stage))
        return {"ggH": groups["ggH"], "ggZH_had": [], "qqH": groups["qqH"], "VH_had": [], "VH": groups["VH"], "ttH": groups["ttH"]}
    ggH = ["ggH_htt"]
    qqH = ["qqH_htt"]
    VH = ["VH_htt", "WH_htt", "ZH_htt"]
    ttH = ["ttH_htt"]
    ggZH_had: list = []
    VH_had: list = []

    if run2:
        ggH += [
            "ggH_FWDH_htt",
            "ggH_PTH_200_300_htt", "ggH_PTH_300_450_htt", "ggH_PTH_450_650_htt", "ggH_PTH_GT650_htt",
            "ggH_0J_PTH_0_10_htt", "ggH_0J_PTH_GT10_htt",
            "ggH_1J_PTH_0_60_htt", "ggH_1J_PTH_60_120_htt", "ggH_1J_PTH_120_200_htt",
            "ggH_GE2J_MJJ_0_350_PTH_0_60_htt", "ggH_GE2J_MJJ_0_350_PTH_60_120_htt",
            "ggH_GE2J_MJJ_0_350_PTH_120_200_htt",
            "ggH_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25_htt", "ggH_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25_htt",
            "ggH_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25_htt", "ggH_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25_htt",
            "ggH125-ggh_htautau_bin101to104_selection", "ggH125-ggh_htautau_bin105to106_selection",
            "ggH125-ggh_htautau_bin107to109_selection", "ggH125-ggh_htautau_bin110to116_selection",
            "ggH125-ggh_htautau_bin101to104_selection125", "ggH125-ggh_htautau_bin105to106_selection125",
            "ggH125-ggh_htautau_bin107to109_selection125", "ggH125-ggh_htautau_bin110to116_selection125",
        ]
        ggZH_had = [
            "ggZH_had_htt",
            "ggZH_had_FWDH_htt",
            "ggZH_had_PTH_200_300_htt", "ggZH_had_PTH_300_450_htt", "ggZH_had_PTH_450_650_htt", "ggZH_had_PTH_GT650_htt",
            "ggZH_had_0J_PTH_0_10_htt", "ggZH_had_0J_PTH_GT10_htt",
            "ggZH_had_1J_PTH_0_60_htt", "ggZH_had_1J_PTH_60_120_htt", "ggZH_had_1J_PTH_120_200_htt",
            "ggZH_had_GE2J_MJJ_0_350_PTH_0_60_htt", "ggZH_had_GE2J_MJJ_0_350_PTH_60_120_htt",
            "ggZH_had_GE2J_MJJ_0_350_PTH_120_200_htt",
            "ggZH_had_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25_htt", "ggZH_had_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25_htt",
            "ggZH_had_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25_htt", "ggZH_had_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25_htt",
        ]
        qqH += [
            "qqH_FWDH_htt", "qqH_0J_htt", "qqH_1J_htt",
            "qqH_GE2J_MJJ_0_60_htt", "qqH_GE2J_MJJ_60_120_htt", "qqH_GE2J_MJJ_120_350_htt",
            "qqH_GE2J_MJJ_GT350_PTH_GT200_htt",
            "qqH_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25_htt", "qqH_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25_htt",
            "qqH_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25_htt", "qqH_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25_htt",
            "qqH125-qqh_htautau_bin201to210_selection",
            "qqH125-qqh_htautau_bin201to202_selection", "qqH125-qqh_htautau_bin203to210_selection",
            "qqH125-qqh_htautau_bin201to210_selection125",
            "qqH125-qqh_htautau_bin201to202_selection125", "qqH125-qqh_htautau_bin203to210_selection125",
        ]
        VH_had = [
            "WH_had_htt", "ZH_had_htt",
            "WH_had_FWDH_htt", "WH_had_0J_htt", "WH_had_1J_htt",
            "WH_had_GE2J_MJJ_0_60_htt", "WH_had_GE2J_MJJ_60_120_htt", "WH_had_GE2J_MJJ_120_350_htt",
            "WH_had_GE2J_MJJ_GT350_PTH_GT200_htt",
            "WH_had_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25_htt", "WH_had_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25_htt",
            "WH_had_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25_htt", "WH_had_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25_htt",
            "ZH_had_FWDH_htt", "ZH_had_0J_htt", "ZH_had_1J_htt",
            "ZH_had_GE2J_MJJ_0_60_htt", "ZH_had_GE2J_MJJ_60_120_htt", "ZH_had_GE2J_MJJ_120_350_htt",
            "ZH_had_GE2J_MJJ_GT350_PTH_GT200_htt",
            "ZH_had_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25_htt", "ZH_had_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25_htt",
            "ZH_had_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25_htt", "ZH_had_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25_htt",
        ]
        VH += [
            "WH_lep_htt", "ZH_lep_htt", "ggZH_lep_htt",
            "WH_lep_FWDH_htt",
            "WH_lep_PTV_0_75_htt", "WH_lep_PTV_75_150_htt",
            "WH_lep_PTV_150_250_0J_htt", "WH_lep_PTV_150_250_GE1J_htt", "WH_lep_PTV_GT250_htt",
            "ZH_lep_FWDH_htt",
            "ZH_lep_PTV_0_75_htt", "ZH_lep_PTV_75_150_htt",
            "ZH_lep_PTV_150_250_0J_htt", "ZH_lep_PTV_150_250_GE1J_htt", "ZH_lep_PTV_GT250_htt",
            "ggZH_lep_FWDH_htt",
            "ggZH_lep_PTV_0_75_htt", "ggZH_lep_PTV_75_150_htt",
            "ggZH_lep_PTV_150_250_0J_htt", "ggZH_lep_PTV_150_250_GE1J_htt", "ggZH_lep_PTV_GT250_htt",
        ]

    return {"ggH": ggH, "ggZH_had": ggZH_had, "qqH": qqH, "VH_had": VH_had, "VH": VH, "ttH": ttH}


def add_signal_systematics(add_syst, processes, channels, stage: str = "stage0") -> None:
    add_syst("BR_htt", "lnN", processes.htt, channels.all, 1.016)
    for group, members in stxs_tools.group_members(stage).items():
        procs = [datacard_signal(group, stage)]
        for np_name, (down, up) in stxs_tools.thu_lnN(members).items():
            add_syst(np_name, "lnN", procs, channels.all, up if down == up else (down, up))
        for np_name in stxs_tools.lhe_scale_systematics(members):
            add_syst(np_name, "shape", procs, channels.all)
