import re
from functools import lru_cache
from pathlib import Path

import yaml

MASS = "125"
CADI_LINE = "HIG26018"  # CMS_<analysisID>_ prefix of bins and analysis-specific nuisances (CAT naming conventions)
PHYSICS_MODEL = "HiggsAnalysis.CombinedLimit.PhysicsModel:multiSignalModel"
# signal theory nuisances, frozen with the signal in b-only fits (GoF) so nothing signal-like is fitted to data
THEORY_NUISANCES = f"rgx{{BR_.*}},rgx{{THU_.*}},rgx{{pdf_alphas_.*}},rgx{{pdf_Higgs_.*}},rgx{{ps_.*}},rgx{{CMS_{CADI_LINE}_QCDscale_.*}}"

# POIs of the multiSignalModel per STXS stage: POI -> (regex of the `<PROCESS>_<STXS_BIN>` it scales, range). STXS bins are
# merged here, never in the datacard (FittingProcedures.md). stage1p2: one POI per NN signal class of the training
# (common/training_stxs_classes.yaml), FWDH in none, so it stays at the SM.
_QQH = "(VBF|WPLUSH2HQQ|WMINUSH2HQQ|ZH2HQQ)"
_STAGE0_POIS = {
    "r_ggH": ("GG2H_.*", 0, 5), "r_qqH": (f"{_QQH}_.*", 0, 5),
    "r_VH": ("(WPLUSH2HLNU|WMINUSH2HLNU|ZH2HLEPLEP)_.*", -5, 10), "r_ttH": ("TTH_.*", -5, 10),
}
_TRAINING_CLASSES = Path(__file__).resolve().parents[3] / "common/training_stxs_classes.yaml"
_MODE = {"ggh": "ggH", "qqh": "qqH", "vh": "VH", "tth": "ttH"}


@lru_cache(maxsize=None)
def poi_scheme(stage: str = "stage0") -> dict:
    if stage == "stage0":
        return _STAGE0_POIS
    from analyses.smhtt.common.stxs_tools import _PROCESS_KEY, _name_info

    classes = {ch: [(c["mode"], tuple(c["bins"])) for c in cs] for ch, cs in yaml.safe_load(_TRAINING_CLASSES.read_text()).items()}
    if len(set(map(tuple, classes.values()))) != 1:
        raise ValueError(f"the channels of {_TRAINING_CLASSES} have different classes: one POI scheme needs common ones")
    info = _name_info()
    return {f"r_{_MODE[mode]}_bin{'_'.join(map(str, bins))}":
            ("|".join(n for n, (_, process, htxs_bin) in info.items() if _PROCESS_KEY(process) == mode and htxs_bin in bins), -5, 10)
            for mode, bins in next(iter(classes.values()))}


# normalisation NPs of the inclusive process cross sections and branching fraction (TheorySystematics.md)
_INCLUSIVE_NORMALISATION = re.compile(r"THU_.*_(Mu|Yield|inc)|pdf_Higgs_.*|alphaS_.*|BR_.*")


def _poi_of_signals(stage: str) -> dict:
    """{datacard signal process: POI}; a process belongs to the POI matching all its `<PROCESS>_<STXS_BIN>` members."""
    from analyses.smhtt.common.stxs_tools import group_members
    from analyses.smhtt.datacards.systematics import datacard_signal

    result = {}
    for group, members in group_members(stage).items():
        pois = [poi for poi, (pattern, _, _) in poi_scheme(stage).items() if any(re.fullmatch(pattern, m) for m in members)]
        if len(pois) > 1 or pois and not all(re.fullmatch(poi_scheme(stage)[pois[0]][0], m) for m in members):
            raise ValueError(f"{group} ({members}) is split over the POIs {pois} of the {stage} scheme")
        if pois:
            result[datacard_signal(group, stage)] = pois[0]
    return result


def physics_model_options(stage: str = "stage0") -> list:
    """multiSignalModel --PO maps (matched on "<bin>/<process>") of the stage's POI scheme."""
    by_poi = {}
    for process, poi in _poi_of_signals(stage).items():
        by_poi.setdefault(poi, []).append(re.escape(process))
    return [arg for poi, (_, low, high) in poi_scheme(stage).items() if poi in by_poi
            for arg in ("--PO", f'"map=^.*/({"|".join(by_poi[poi])})$:{poi}[1,{low},{high}]"')]


def frozen_theory_nuisances(stage: str = "stage0") -> list:
    """Normalisation NPs frozen in the cross-section fits (FittingProcedures.md): the inclusive ones, and the migration ones
    except those crossing a boundary merged into one POI, i.e. acting unevenly on the bins of one process within a POI."""
    from analyses.smhtt.common.stxs_tools import _name_info, group_members, thu_lnN, thu_values
    from common.analysis import legacy_nuisance_name

    values, info = thu_values(), _name_info()
    members = {poi: [m for m in info if re.fullmatch(pattern, m)] for poi, (pattern, _, _) in poi_scheme(stage).items()}
    booked = {np_name for ms in group_members(stage).values() for np_name in thu_lnN(ms)}
    profiled = set()
    for ms in members.values():
        for process in {info[m][1] for m in ms}:
            same = [values.get(m, {}) for m in ms if info[m][1] == process]
            profiled |= {n for n in set().union(*same) if len({tuple(round(x, 4) for x in v.get(n, (1.0, 1.0))) for v in same}) > 1}
    frozen = {legacy_nuisance_name(n) for n in set().union(*values.values()) if _INCLUSIVE_NORMALISATION.fullmatch(n) or n not in profiled}
    return sorted((frozen & booked) | {"BR_htt"})

# TODO remove with the reprocessed ntuples: htt_261012 has the muon trigger total and the e->tau ES per barrel/endcap only
LEGACY_NTUPLE_SHIFTS = True

_ERA = r"(2022|2022EE|2023|2023BPix|2024|2025)"
_TAU = "DeepTau2018v2p5"
# older names -> datacard names (first matching regex), for ntuples and shapes made before CROWN booked the datacard names
# (htt_261012), and the names of the Higgs-group recommendation files; see common.analysis.legacy_nuisance_name
NUISANCE_RENAMING = [
    (r"CMS_fake_t_((QCD|Wjets|ttbar)_.*)", rf"CMS_{CADI_LINE}_fake_t_\1"),
    (r"CMS_htt_zptReweight_(.*)", rf"CMS_{CADI_LINE}_zptReweight_\1"),
    (r"CMS_(scale_met_recoil_response|res_met_recoil_resolution)_(.*)", rf"CMS_{CADI_LINE}_\1_\2"),
    (r"CMS_LHEScaleWeight_(.*)", rf"CMS_{CADI_LINE}_QCDscale_\1_ACCEPT"),
    (r"CMS_lumi_1", "lumi_13p6TeV_222324"),
    (r"CMS_lumi_2", "lumi_13p6TeV_2324"),
    (r"CMS_lumi_3", "lumi_13p6TeV_2024"),
    (r"PileUp", "CMS_pileup_2025"),
    (r"CMS_htt_zjXsec", "cross_section_V"),
    (r"CMS_htt_tjXsec", "cross_section_ttbar"),
    (r"CMS_htt_vvXsec", "cross_section_VV"),
    (r"alphaS_(ggH|qqH|VH|ttH)", r"pdf_alphas_\1"),
    (r"CMS_(scale|res)_e", r"CMS_\1_e_13p6TeV"),
    (r"CMS_eff_e_id", r"CMS_eff_e_id_13p6TeV"),
    (rf"CMS_eff_t_{_TAU}_VSjet_(stat[12])_DM(\d+)_{_ERA}", rf"CMS_eff_t_{_TAU}_VSjet_dm_\1_DM\2_\3"),
    (rf"CMS_eff_t_{_TAU}_VSjet_syst_TES_DM(\d+)_{_ERA}", rf"CMS_eff_t_{_TAU}_VSjet_dm_syst_DM\1_\2"),
    (rf"CMS_eff_t_{_TAU}_VSjet_syst_(alleras|{_ERA[1:-1]})", rf"CMS_eff_t_{_TAU}_VSjet_dm_syst_\1"),
    (rf"CMS_eff_t_{_TAU}_VSjet_DM(\d+)_pT20to40_{_ERA}", rf"CMS_eff_t_{_TAU}_VSjet_dm_DM\1_pt_bin1_\2"),
    (rf"CMS_eff_t_{_TAU}_VSjet_DM(\d+)_pT40to60_{_ERA}", rf"CMS_eff_t_{_TAU}_VSjet_dm_DM\1_pt_bin2_\2"),
    (rf"CMS_eff_t_{_TAU}_VSjet_DM(\d+)_pT60toInf_{_ERA}", rf"CMS_eff_t_{_TAU}_VSjet_dm_DM\1_pt_bin3_\2"),
    (rf"CMS_fake_t_{_TAU}_VSe_DM(\d+)_barrel_{_ERA}", rf"CMS_fake_t_{_TAU}_VSe_DM\1_eta_bin1_\2"),
    (rf"CMS_fake_t_{_TAU}_VSe_DM(\d+)_endcap_{_ERA}", rf"CMS_fake_t_{_TAU}_VSe_DM\1_eta_bin2_\2"),
    (rf"CMS_fake_t_{_TAU}_VSmu_wheel(\d)_{_ERA}", rf"CMS_fake_t_{_TAU}_VSmu_eta_bin\1_\2"),
    (rf"CMS_scale_t_DM(\d+)_genMuon_{_ERA}", rf"CMS_scale_t_{_TAU}_DM\1_genMuon"),
    (r"CMS_scale_t_DM(\d+)_(gen.*)", rf"CMS_scale_t_{_TAU}_DM\1_\2"),
    (rf"CMS_trig_j_ditaujet_{_ERA}", rf"CMS_{CADI_LINE}_trig_j_ditaujet_\1"),
]
