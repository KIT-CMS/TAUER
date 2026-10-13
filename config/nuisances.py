"""
Single source of the systematic uncertainties: shapes/produce_shapes.py books the shape variations of these entries
and datacards/systematics.py adds them to the datacards. The STXS signal uncertainties come from
analyses/<analysis>/datacards/systematics.py, the embedding ones are kept separately (Run 2 only).

`processes` are background shape keys or groups of config/processes.py, or "signal" (all signal units/processes),
"jetFakes" (the fake factor estimate, i.e. the shift is also booked in the anti-isolated region) or "qcd".
"""
from typing import NamedTuple, Tuple, Union

from config.analysis import ff_component_names

ERA_TAG = {
    "2016preVFP": "2016preVFP", "2016postVFP": "2016postVFP", "2017": "2017", "2018": "2018",
    "2022preEE": "2022", "2022postEE": "2022EE",
    "2023preBPix": "2023", "2023postBPix": "2023BPix",
    "2024": "2024", "2025": "2025", "2026": "2026",
}

ALL = ("et", "mt", "tt", "em")
LT_TT = ("et", "mt", "tt")

DMS = ("0", "1", "10", "11")
MC = ("mc_bkg", "signal")
# processes with a genuine hadronic tau whose ID/energy scale is corrected (ZL excluded, its tau is mostly a lepton)
TAU_CORRECTED = ("real_tau", "ttl", "vvl", "signal")
# processes with a light lepton reconstructed as hadronic tau
LEP_FAKE = ("lep_fake", "signal")


class Nuisance(NamedTuple):
    name: str
    processes: Tuple[str, ...]
    channels: Tuple[str, ...]
    kind: str = "shape"  # shape or lnN
    value: Union[float, Tuple[float, float]] = 1.0
    # how the shape is made: "crown" (CROWN shift of the same name),
    # "ff" (shift of the fake factor weight, anti-isolated region only) or "estimation" (made by shapes/do_estimations.py)
    source: str = "crown"


def _shapes(names, processes, channels, **kwargs):
    return [Nuisance(name, tuple(processes), tuple(channels), **kwargs) for name in names]


def nuisances(era: str, jetfakes: bool = True, qcd: bool = True, ff_ml: bool = False) -> list:
    tag = ERA_TAG[era]
    run2 = int(era[:4]) < 2022
    n = []

    # ---- Luminosity ----
    if run2:
        n += [
            Nuisance(f"lumi_13TeV_{tag}", MC, ALL, "lnN", {"2017": 1.0082, "2018": 1.0084}.get(era, 1.012)),
            Nuisance("lumi_13TeV_correlated", MC, ALL, "lnN", {"2017": 1.009, "2018": 1.020}.get(era, 1.006)),
            Nuisance("lumi_13TeV_1718", MC, ALL, "lnN", {"2017": 1.006, "2018": 1.002}.get(era, 1.0)),
        ]
    else:
        # LUM POG decorrelation scheme for 2022-2024; TODO: 2025/2026 pinned to 2024 until LUM POG provides values
        year = "2024" if era in ("2025", "2026") else era[:4]
        for i, values in enumerate(({"2022": 1.0138, "2023": 1.0017, "2024": 1.0020}, {"2023": 1.0127, "2024": 1.0068}, {"2024": 1.0144}), 1):
            if year in values:
                n.append(Nuisance(f"CMS_lumi_{i}", MC, ALL, "lnN", values[year]))

    # ---- Triggers ----
    if run2:
        n.append(Nuisance(f"CMS_eff_trigger_em_{tag}", MC, ("em",), "lnN", 1.02))
    else:
        n += _shapes([f"CMS_eff_e_trigger_{tag}", f"CMS_trig_t_etau_Medium_eff_{tag}"], MC, ("et",))
        n += _shapes([f"CMS_eff_m_trigger_{tag}"], MC, ("mt", "em"))
        n += _shapes([f"CMS_trig_t_mutau_Medium_eff_{tag}"], MC, ("mt",))
        n += _shapes([f"CMS_trig_t_ditau_Medium_eff_{tag}", f"CMS_trig_t_ditaujet_Medium_eff_{tag}", f"CMS_trig_j_ditaujet_{tag}"], MC, ("tt",))

    # ---- Electrons and muons: ID/isolation in the channels with the lepton, energy scale/resolution everywhere (vetoes) ----
    n += _shapes(["CMS_eff_e_id"], MC, ("et", "em"))
    n += _shapes(["CMS_eff_m_id_syst", f"CMS_eff_m_id_stat_{tag}", "CMS_eff_m_iso_syst", f"CMS_eff_m_iso_stat_{tag}"], MC, ("mt", "em"))
    n += _shapes(["CMS_scale_e", "CMS_res_e"], MC, ALL)
    n += _shapes([f"CMS_scale_m_stat_{tag}", "CMS_scale_m_syst", f"CMS_res_m_stat_{tag}", "CMS_res_m_syst"], MC, ALL)

    # ---- Tau ID (vsJet) ----
    if run2:
        tau_id = [f"CMS_eff_t_DeepTau2017v2p1_VSjet_DM{dm}_pT{pt}" for dm in DMS for pt in ("20to40", "40toInf")]
    elif era.startswith(("2022", "2023")):
        tau_id = [f"CMS_eff_t_DeepTau2018v2p5_VSjet_{c}_DM{dm}_{tag}" for dm in DMS for c in ("stat1", "stat2", "syst_TES")]
        tau_id += ["CMS_eff_t_DeepTau2018v2p5_VSjet_syst_alleras", f"CMS_eff_t_DeepTau2018v2p5_VSjet_syst_{tag}"]
    else:
        tau_id = [f"CMS_eff_t_DeepTau2018v2p5_VSjet_DM{dm}_pT{pt}_{tag}" for dm in DMS for pt in ("20to40", "40to60", "60toInf")]
    n += _shapes(tau_id, TAU_CORRECTED, LT_TT)

    # ---- Tau energy scale, also of the MC subtracted in the anti-isolated region ----
    if run2:
        tes = [f"CMS_scale_t_DM{dm}_genTau_pT{pt}" for dm in DMS for pt in ("20to40", "40toInf")]
    elif era == "2024":
        tes = [f"CMS_scale_t_DM{dm}_genTau_pT{pt}_{tag}" for dm in DMS for pt in ("20to40", "40to60", "60toInf")]
    else:
        tes = [f"CMS_scale_t_DM{dm}_genTau_{tag}" for dm in DMS]
    n += _shapes(tes, TAU_CORRECTED + (("jetFakes",) if jetfakes else ()), LT_TT)

    # ---- Light leptons reconstructed as taus: energy scale and vsEle/vsMu ID ----
    if run2:
        n += _shapes([f"CMS_scale_t_DM{dm}_genElectron_{r}" for dm in ("0", "1") for r in ("barrel", "endcap")], ("zl",), ("et",))
        n += _shapes(["CMS_scale_t_genMuon"], ("zl",), ("mt",))
        n += _shapes([f"CMS_fake_t_DeepTau2017v2p1_VSe_{r}" for r in ("barrel", "endcap")], ("zl",), ("et",))
        n += _shapes([f"CMS_fake_t_DeepTau2017v2p1_VSmu_wheel{w}" for w in range(1, 6)], ("zl",), ("mt",))
    else:
        n += _shapes([f"CMS_scale_t_DM{dm}_genElectron_{r}_{tag}" for dm in DMS for r in ("barrel", "endcap")], LEP_FAKE, LT_TT)
        n += _shapes([f"CMS_scale_t_DM{dm}_genMuon_{tag}" for dm in DMS], LEP_FAKE, LT_TT)
        n += _shapes([f"CMS_fake_t_DeepTau2018v2p5_VSe_DM{dm}_{r}_{tag}" for dm in DMS for r in ("barrel", "endcap")], LEP_FAKE, LT_TT)
        n += _shapes([f"CMS_fake_t_DeepTau2018v2p5_VSmu_wheel{w}_{tag}" for w in range(1, 6)], LEP_FAKE, LT_TT)

    # ---- Jets, b tagging, MET, pileup ----
    n += _shapes([f"CMS_scale_j_{s}" for s in ("Total", "Absolute", "FlavorQCD", "BBEC1", "HF", "EC2", "RelativeBal")], MC, ALL)
    n += _shapes([f"CMS_scale_j_{s}_{tag}" for s in ("Absolute", "BBEC1", "HF", "EC2", "RelativeSample")] + [f"CMS_res_j_{tag}"], MC, ALL)
    if not run2:
        n += _shapes(["CMS_btag_fixedWP_bc_correlated", f"CMS_btag_fixedWP_bc_uncorrelated_{tag}", "CMS_btag_fixedWP_light_correlated", f"CMS_btag_fixedWP_light_uncorrelated_{tag}"], MC, ALL)
    n += _shapes([f"CMS_scale_met_unclustered_energy_{tag}"], MC, ALL)
    recoil_tag = "" if run2 else f"_{tag}"
    n += _shapes([f"CMS_res_met_recoil_resolution{recoil_tag}", f"CMS_scale_met_recoil_response{recoil_tag}"], ("z", "w", "signal"), ALL)
    n += _shapes(["PileUp" if era in ("2025", "2026") else f"CMS_pileup_{tag}"], MC, ALL)

    # ---- Reweightings and background normalizations ----
    if not run2:
        n += _shapes([f"CMS_htt_zptReweight_{tag}"], ("z",), ALL)
    n += _shapes(["top_pt_reweighting"], ("ttbar",), ALL)
    # TODO: check the values for Run 3
    for name, procs, value in (("vvXsec", "vv", 1.05), ("tjXsec", "ttbar", 1.06), ("wjXsec", "w", 1.04), ("zjXsec", "z", 1.02)):
        n.append(Nuisance(f"CMS_htt_{name}", (procs,), ALL, "lnN", value))

    # ---- QCD and jet fakes ----
    if qcd and not jetfakes:
        n += [Nuisance(f"CMS_ExtrapSSOS_{tag}_{ch}", ("qcd",), (ch,), "lnN", value) for ch, value in (("et", 1.05), ("mt", 1.03), ("tt", 1.05))]
    n += _shapes([f"CMS_htt_qcd_{j}_{s}_{era}" for j in ("0jet", "1jet", "2jet") for s in ("rate", "shape", "shape2")] + ["CMS_htt_qcd_iso"], ("qcd",), ("em",), source="estimation")
    if jetfakes:
        for ch, ff_processes in (("et", (("QCD", True), ("Wjets", True), ("ttbar", False))), ("mt", (("QCD", True), ("Wjets", True), ("ttbar", False))), ("tt", (("QCD", True), ("QCD_subleading", True)))):
            n += _shapes([name for process, dr_sr in ff_processes for name in ff_component_names(process, era, ch, dr_sr=dr_sr, ml=ff_ml)], ("jetFakes",), (ch,), source="ff")
    return n
