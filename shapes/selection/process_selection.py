import functools
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Tuple, Union

import yaml

from common.helper_collection import calculate_stxs_N_and_negative_fractions
from config.logging_setup_configs import LogContext, setup_logging
from ntuple_processor.utils import Selection

logger = setup_logging(logger=logging.getLogger(__name__))


"""Base processes

List of base processes, mostly containing only weights:
    - triggerweight
    - triggerweight_emb
    - tau_by_iso_id_weight
    - ele_hlt_Z_vtx_weight
    - ele_reco_weight
    - aiso_muon_correction
    - lumi_weight
    - MC_base_process_selection
    - DY_base_process_selection
    - TT_process_selection
    - VV_process_selection
    - W_process_selection
    - HTT_base_process_selection
    - HTT_process_selection
    - HWW_process_selection
"""


def triggerweight(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    weight = ("1.0", "triggerweight")

    # General definitions of weights valid for all eras and channels
    if "mt" in channel:
        weight = ("mtau_triggerweight_ic", "triggerweight")
    elif "et" in channel:
        weight = ("etau_triggerweight_ic", "triggerweight")
    elif "tt" in channel:
        weight = ("tautau_triggerweight_ic", "triggerweight")
    elif "em" in channel:
        ElMuData = "(trigger_23_data_Weight_2*trigger_12_data_Weight_1*(trg_muonelectron_mu23ele12==1)+trigger_23_data_Weight_1*trigger_8_data_Weight_2*(trg_muonelectron_mu8ele23==1) - trigger_23_data_Weight_2*trigger_23_data_Weight_1*(trg_muonelectron_mu8ele23==1 && trg_muonelectron_mu23ele12==1))"
        ElMuEmb = ElMuData.replace("data", "mc")
        ElMu = "(" + ElMuData + ")/(" + ElMuEmb + ")"
        weight = (ElMu, "triggerweight")

    # In previous software only used in 2017 and 2018. Before usage in 2016 check if the weight is valid.
    elif "mm" in channel:
        weight = (
            "singleTriggerDataEfficiencyWeightKIT_1/singleTriggerMCEfficiencyWeightKIT_1",
            "trigger_lepton_sf",
        )

    return weight


def lumi_weight(era, **kwargs):
    from config.analysis import get_luminosity

    lumi = get_luminosity(era)
    return ("{} * 1000.0".format(lumi), "lumi")


def prefiring_weight(era, **kwargs):
    return ("1.0", "prefireWeight")


def MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    wps_dict = [

        "VVTight",
        "VVTight",
        "Tight",
        "Medium",
        "Loose",
        "VLoose",
        "VVLoose",
        "VVVLoose",
    ]

    if vs_ele_wp not in wps_dict:
        print("This vs electron working point doen't exist. Please specify the correct vsEle discriminator ")
        raise ValueError("Given vs electron working point {} not defined.".format(vs_ele_wp))
    if vs_jet_wp not in wps_dict:
        print("This vs jet working point doen't exist. Please specify the correct vsJet discriminator ")
        raise ValueError("Given vs jet working point {} not defined.".format(vs_jet_wp))

    if channel == "em":
        isoweight = ("iso_wgt_mu_2", "isoweight") #iso_wgt_ele_1 * 
        idweight = ("id_wgt_ele_wp90iso_1 * id_wgt_mu_2", "idweight")
        tauidweight = None
        vsmu_weight = None
        vsele_weight = None
        trgweight = trgweight = ("(pt_1>26)*(trg_wgt_single_mu24)", "trgweight")
    elif channel == "et":
        isoweight = None # ("iso_wgt_ele_1", "isoweight") only for embedding
        idweight = ("id_wgt_ele_wp90iso_1", "idweight")
        tauidweight = (
            f"((gen_match_2==5)*id_wgt_tau_vsJet_{vs_jet_wp}_2 + (gen_match_2!=5))",
            "taubyIsoIdWeight",
        )
        vsmu_weight = (f"id_wgt_tau_vsMu_VLoose_{vs_ele_wp}_2", "vsmuweight")
        vsele_weight = (f"id_wgt_tau_vsEle_{vs_ele_wp}_2", "vseleweight")
        trgweight = ("(pt_1>32)*(trg_wgt_single_ele30)", "trgweight")
    elif channel == "mt":
        isoweight = ("iso_wgt_mu_1", "isoweight")
        idweight = ("id_wgt_mu_1", "idweight")
        tauidweight = (
            f"((gen_match_2==5)*id_wgt_tau_vsJet_{vs_jet_wp}_2 + (gen_match_2!=5))",
            "taubyIsoIdWeight",
        )
        tauidweight = None
        vsmu_weight = (f"id_wgt_tau_vsMu_Tight_{vs_ele_wp}_2", "vsmuweight")
        vsele_weight = (f"id_wgt_tau_vsEle_{vs_ele_wp}_2", "vseleweight")
        if era == "2018":
            # 2018 CROWN branches ship the OR-of-both-single-muon-triggers
            # weight precomputed (trg_wgt_single_mu24ormu27); no extra pt cut
            # needed. Confirmed present in the Phase 2a validation ntuples.
            trgweight = ("(trg_wgt_single_mu24ormu27)", "trgweight")
        else:
            trgweight = ("(pt_1>26)*(trg_wgt_single_mu24)", "trgweight")
    elif channel == "tt":
        isoweight = None
        idweight = None
        tauidweight = (
            f"((gen_match_1==5)*id_wgt_tau_vsJet_{vs_jet_wp}_1 + (gen_match_1!=5)) * ((gen_match_2==5)*id_wgt_tau_vsJet_{vs_jet_wp}_2 + (gen_match_2!=5))",
            "taubyIsoIdWeight",
        )
        vsmu_weight = (
            f"((gen_match_1==5)*id_wgt_tau_vsMu_VLoose_{vs_ele_wp}_1 + (gen_match_1!=5)) * ((gen_match_2==5)*id_wgt_tau_vsMu_VLoose_{vs_ele_wp}_1 + (gen_match_2!=5))",
            "vsmuweight",
        )
        vsele_weight = (
            f"((gen_match_1==5)*id_wgt_tau_vsEle_{vs_ele_wp}_1 + (gen_match_1!=5)) * ((gen_match_2==5)*id_wgt_tau_vsEle_{vs_ele_wp}_2 + (gen_match_2!=5))",
            "vseleweight",
        )
        if era in ["2024", "2025"]:
            trgweight = (
                "(trg_wgt_doubletau30_leg1 * trg_wgt_doubletau30_leg2 * (pt_1 > 35) * (pt_2 > 35))", "trgweight"
            )
        else:
            trgweight = (
            "(trg_wgt_doubletau35_leg1 * trg_wgt_doubletau35_leg2 * (pt_1 > 40) * (pt_2 > 40))", "trgweight"
        )
    else:
        raise ValueError("Given channel {} not defined.".format(channel))

    if preselected:
        # When reading from preselected files, presel_weight already encodes:
        # lumi × gen × SF(vsEle) × SF(vsMu) × SF(lep-id/iso) × Z/Top pt reweighting.
        # Only pileup, trigger SF, tau-vsJet SF, and btag weight are still needed here.
        MC_base_process_weights = [
            ("presel_weight", "presel_weight"),
            ("puweight", "puweight"),
            tauidweight,
            trgweight,
        ]
    else:
        MC_base_process_weights = [
            ("puweight", "puweight"),
            isoweight,
            idweight,
            tauidweight,
            vsmu_weight,
            vsele_weight,
            trgweight,
            lumi_weight(era),
            prefiring_weight(era),
        ]
    if channel not in ("mm", "mt"):
        # btag weight is not part of the mt/mm base selection (no b-tag
        # requirement there; it's applied at category level via an nbtag
        # cut instead). Matches smhtt_ul's convention. Previously appended
        # unconditionally for all channels here — silently correct only by
        # coincidence for eras whose CROWN production happens to ship a
        # `btag_weight` branch; the 2018 validation production used for
        # Phase 2a does not ship one, which surfaced this bug.
        MC_base_process_weights.append(("btag_weight", "btagWeight"))
    return Selection(
        name="MC base",
        weights=[weight for weight in MC_base_process_weights if weight is not None],
    )


def DY_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    DY_process_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    if not preselected:
        DY_process_weights.extend(
            [
                ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
                (
                    """(
                        crossSectionPerEventWeight * (
                            (1.0 / negative_events_fraction) * (
                                ((genWeight < 0) * (-1)) +
                                ((genWeight >= 0) * 1)
                            )
                        )
                    )""",
                    "crossSectionPerEventWeight",
                ),
            ]
        )
        DY_process_weights.append(("zPtReweightWeight", "zPtReweightWeight"))
    return Selection(name="DY", weights=DY_process_weights)


def DY_NLO_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    DY_process_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    if not preselected:
        DY_process_weights.extend(
            [
                ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
                (
                    """(
                        (1.0 / negative_events_fraction) * (
                            ((genWeight < 0) * (-1)) +
                            ((genWeight >= 0) * 1)
                        )
                    ) * crossSectionPerEventWeight
                    """,
                    "crossSectionPerEventWeight",
                ),
                # dy_stitching_weight(era),  # TODO add stitching weight
            ]
        )
        DY_process_weights.append(("zPtReweightWeight", "zPtReweightWeight"))
    return Selection(name="DYNLO", weights=DY_process_weights)


def ttbar_em_weight(channel, era, **kwargs):
    """
    Applies a data/MC correction for ttbar events based on the em channel measurement
    in the m_vis > 100 region. The ratio is computed from the em channel and applied
    uniformly to all ttbar events across all channels and regions.
    
    This weight should be used for ttbar process selection to account for
    mismodeling of ttbar.
    
    Calculation:
    - TT includes: TTT + TTL (excludes TTJ which is in fake factors)
    - Background: DY + W + VV + QCD (excludes all Higgs processes)
    - Weight = (data - background) / TT
    """
    # Get the data/MC ratio from em channel for m_vis > 100
    # Calculated as: (data - all_backgrounds) / TT_MC in em channel
    
    if era == "2022preEE":
        ratio_em = "0.850809"  # ± 0.006696
    elif era == "2022postEE":
        ratio_em = "0.927774"  # ± 0.003925
    elif era == "2023preBPix":
        ratio_em = "0.967221"  # ± 0.004604
    elif era == "2023postBPix":
        ratio_em = "0.898871"  # ± 0.006258
    elif era == "2024":
        ratio_em = "0.926025"  # ± 0.002382
    elif era == "2025":
        ratio_em = "0.928433"  # ± 0.002396
    else:
        ratio_em = "1.0"
    
    # Apply the correction uniformly to all ttbar events in all regions
    # This works for all channels (et, mt, tt, em)
    weight_expr = ratio_em
    
    return (weight_expr, "ttbar_em_weight")


def TT_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    TT_process_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    if not preselected:
        TT_process_weights.extend(
            [
                ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
                (
                    "(( 1.0 / negative_events_fraction) * (((genWeight<0) * -1) + ((genWeight > 0 * 1)))) * crossSectionPerEventWeight",
                    "crossSectionPerEventWeight",
                ),
                ("topPtReweightWeight", "topPtReweightWeight"),
            ]
        )
    return Selection(name="TT", weights=TT_process_weights)


def VV_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    VV_process_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    if not preselected:
        VV_process_weights.extend(
            [
                ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
                (
                    "(( 1.0 / negative_events_fraction) * (((genWeight<0) * -1) + ((genWeight > 0 * 1)))) * crossSectionPerEventWeight",
                    "crossSectionPerEventWeight",
                ),
            ]
        )
    return Selection(name="VV", weights=VV_process_weights)


def W_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    W_process_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    if not preselected:
        W_process_weights.extend(
            [
                ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
                (
                    "(( 1.0 / negative_events_fraction) * (((genWeight<0) * -1) + ((genWeight > 0 * 1)))) * crossSectionPerEventWeight",
                    "crossSectionPerEventWeight",
                ),
            ]
        )
    return Selection(name="W", weights=W_process_weights)


def HTT_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    return Selection(
        name="HTT_base", weights=MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    )


def HTT_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    HTT_weights = HTT_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    if not preselected:
        HTT_weights = HTT_weights + [
            ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
            (
                "(( 1.0 / negative_events_fraction) * (((genWeight<0) * -1) + ((genWeight > 0 * 1)))) * crossSectionPerEventWeight",
                "crossSectionPerEventWeight",
            ),
        ]
    return Selection(name="HTT", weights=HTT_weights)


# This could eventually be used for all HWW estimations if necessary. At the moment this is not possible due to wrong cross section weights in 2018.
# If the additional processes are required new functions would need to be implemented.
def HWW_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    HWW_process_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    if not preselected:
        HWW_process_weights.extend(
            [
                ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
                (
                    "(( 1.0 / negative_events_fraction) * (((genWeight<0) * -1) + ((genWeight > 0 * 1)))) * crossSectionPerEventWeight",
                    "crossSectionPerEventWeight",
                ),
            ]
        )
    return Selection(name="HWW", weights=HWW_process_weights)


def HWW_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=False, **kwargs):
    HWW_base_process_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp, preselected=preselected).weights
    if not preselected:
        HWW_base_process_weights = HWW_base_process_weights + [
            ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
            (
                "(( 1.0 / negative_events_fraction) * (((genWeight<0) * -1) + ((genWeight > 0 * 1)))) * crossSectionPerEventWeight",
                "crossSectionPerEventWeight",
            ),
        ]
    return Selection(name="HTT", weights=HWW_base_process_weights)


"""Built-on-top processes

List of other processes meant to be put on top of base processes:
    - DY_process_selection
    - DY_nlo_process_selection
    - ZTT_process_selection
    - ZTT_nlo_process_selection
    - ZTT_embedded_process_selection
    - ZL_process_selection
    - ZL_nlo_process_selection
    - ZJ_process_selection
    - ZJ_nlo_process_selection
    - TTT_process_selection
    - TTL_process_selection
    - TTJ_process_selection
    - VVT_process_selection
    - VVJ_process_selection
    - VVL_process_selection
    - VH_process_selection
    - WH_process_selection
    - ZH_process_selection
    - ttH_process_selection
    - ggH125_process_selection
    - qqH125_process_selection
    - ggHWW_process_selection
    - qqHWW_process_selection
    - ZHWW_process_selection
    - WHWW_process_selection
    - SUSYqqH_process_selection
    - SUSYbbH_process_selection
"""


def ZTT_process_selection(channel, **kwargs):
    tt_cut = __get_ZTT_cut(channel)
    return Selection(name="ZTT", cuts=[(f"({tt_cut})", "ztt_cut")])


def ZTT_nlo_process_selection(channel, **kwargs):
    tt_cut = __get_ZTT_cut(channel)
    return Selection(name="ZTT", cuts=[(f"({tt_cut})", "ztt_cut")])


def __get_ZTT_cut(channel, **kwargs):
    if "mt" in channel:
        return "(gen_match_1==4 && gen_match_2==5)"
    elif "et" in channel:
        return "(gen_match_1==3 && gen_match_2==5)"
    elif "tt" in channel:
        return "(gen_match_1==5 && gen_match_2==5)"
    elif "em" in channel:
        return "(gen_match_1==3 && gen_match_2==4)"


def ZTT_embedded_process_selection(channel, era, apply_wps, vs_jet_wp, vs_ele_wp=None, **kwargs):
    # Generator-level embedding weight + muon/tau selection-efficiency weight
    # every embedded sample ships regardless of channel/era. Previously
    # missing here (replaced by a placeholder "(0.25)" scale term) — real gap
    # found while extending to 2018/embedding: without these, embedded
    # background normalization is wrong for every channel, not just mt.
    # Confirmed present in the Phase 2a 2018 TauEmbedding-MuTauFinalState
    # validation ntuples (emb_genweight, emb_idsel_wgt_1, emb_idsel_wgt_2,
    # emb_triggersel_wgt).
    ztt_embedded_weights = [
        ("emb_genweight", "emb_genweight"),
        ("emb_idsel_wgt_1*emb_idsel_wgt_2*emb_triggersel_wgt", "emb_selection_weight"),
    ]
    if "mt" in channel:
        if era == "2018":
            ztt_embedded_weights.extend(
                [
                    ("gen_match_1==4 && gen_match_2==5", "emb_veto"),
                    ("iso_wgt_mu_1", "isoweight"),
                    ("id_wgt_mu_1", "idweight"),
                    ("(trg_wgt_single_mu24ormu27)", "trgweight"),
                ]
            )
        else:
            ztt_embedded_weights.extend(
                [
                    ("gen_match_1==4 && gen_match_2==5", "emb_veto"),
                    ("(trg_wgt_single_mu24)", "trgweight"),
                ]
            )
        if apply_wps:
            ztt_embedded_weights.append(
                (f"((gen_match_2==5)*id_wgt_tau_vsJet_{vs_jet_wp}_2 + (gen_match_2!=5))", "taubyIsoIdWeight")
            )
    elif "et" in channel:
        ztt_embedded_weights.extend(
            [
                ("gen_match_1==3 && gen_match_2==5", "emb_veto"),
                ("(trg_wgt_single_ele30)", "trgweight"),
            ]
        )
    elif "tt" in channel:
        ztt_embedded_weights.extend(
            [
                ("gen_match_1==5 && gen_match_2==5", "emb_veto"),
            ]
        )
        if apply_wps:
            ztt_embedded_weights.extend(
                [
                    (
                        f"((gen_match_1==5)*id_wgt_tau_vsJet_{vs_jet_wp}_1 + (gen_match_1!=5)) * ((gen_match_2==5)*id_wgt_tau_vsJet_{vs_jet_wp}_2 + (gen_match_2!=5))",
                    )
                ]
            )
    elif "em" in channel:
        ztt_embedded_weights.extend(
            [
                ("(gen_match_1==3 && gen_match_2==4)", "emb_gen_match"),
                ("iso_wgt_ele_1 * iso_wgt_mu_2", "isoweight"),
                ("id_wgt_ele_wp90iso_1 * id_wgt_mu_2", "idweight"),
            ]
        )
    else:
        raise ValueError(f"Embedded process selection not implemented for channel {channel}")

    ztt_embedded_cuts = []
    return Selection(
        name="Embedded",
        cuts=ztt_embedded_cuts,
        weights=ztt_embedded_weights,
    )


def ZL_process_selection(channel, **kwargs):
    veto = __get_ZL_cut(channel)
    return Selection(
        name="ZL",
        cuts=[("{}".format(veto[0]), "dy_emb_veto"), ("{}".format(veto[1]), "ff_veto")],
    )


def ZL_nlo_process_selection(channel, **kwargs):
    veto = __get_ZL_cut(channel)
    return Selection(
        name="ZL",
        cuts=[("{}".format(veto[0]), "dy_emb_veto"), ("{}".format(veto[1]), "ff_veto")],
    )


def __get_ZL_cut(channel, **kwargs):
    emb_veto = ""
    ff_veto = ""
    if "mt" in channel:
        emb_veto = "(!(gen_match_1==4 && gen_match_2==5))"
        ff_veto = "(!(gen_match_2 == 6))"
    elif "et" in channel:
        emb_veto = "!(gen_match_1==3 && gen_match_2==5)"
        ff_veto = "!(gen_match_2 == 6)"
    elif "tt" in channel:
        emb_veto = "!(gen_match_1==5 && gen_match_2==5)"
        ff_veto = "!(gen_match_1 == 6 || gen_match_2 == 6)"
    elif "em" in channel:
        emb_veto = "!(gen_match_1==3 && gen_match_2==4)"
        ff_veto = "(1.0)"
    return (emb_veto, ff_veto)


def ZJ_process_selection(channel, **kwargs):
    return Selection(name="ZJ", cuts=[(__get_ZJ_cut(channel), "dy_fakes")])


def ZJ_nlo_process_selection(channel, **kwargs):
    return Selection(name="ZJ", cuts=[(__get_ZJ_cut(channel), "dy_fakes")])


def __get_ZJ_cut(channel, **kwargs):
    if "mt" in channel or "et" in channel:
        return "(gen_match_2 == 6)"
    elif "tt" in channel:
        return "(gen_match_1 == 6 || gen_match_2 == 6)"
    elif "em" in channel:
        return "0 == 1"
    else:
        return ""


def TTT_process_selection(channel, era, **kwargs):
    tt_cut = ""
    if "mt" in channel:
        tt_cut = "(gen_match_1==4 && gen_match_2==5)"
    elif "et" in channel:
        tt_cut = "gen_match_1==3 && gen_match_2==5"
    elif "tt" in channel:
        tt_cut = "gen_match_1==5 && gen_match_2==5"
    elif "em" in channel:
        tt_cut = "gen_match_1==3 && gen_match_2==4"
    weights = [ttbar_em_weight(channel, era)]
    return Selection(name="TTT", cuts=[(f"({tt_cut})", "ttt_cut")], weights=weights)


def TTL_process_selection(channel, era, **kwargs):
    emb_veto = ""
    ff_veto = ""
    if "mt" in channel:
        emb_veto = "(!(gen_match_1==4 && gen_match_2==5))"
        ff_veto = "(!(gen_match_2 == 6))"
    elif "et" in channel:
        emb_veto = "!(gen_match_1==3 && gen_match_2==5)"
        ff_veto = "!(gen_match_2 == 6)"
    elif "tt" in channel:
        emb_veto = "!(gen_match_1==5 && gen_match_2==5)"
        ff_veto = "!(gen_match_1 == 6 || gen_match_2 == 6)"
    elif "em" in channel:
        emb_veto = "!(gen_match_1==3 && gen_match_2==4)"
        ff_veto = "(1.0)"
    weights = [ttbar_em_weight(channel, era)]
    return Selection(
        name="TTL",
        cuts=[(f"({emb_veto})", "tt_emb_veto"), (f"({ff_veto})", "ff_veto")],
        weights=weights,
    )


def TTJ_process_selection(channel, **kwargs):
    ct = ""
    if "mt" in channel or "et" in channel:
        ct = "(gen_match_2 == 6)"
    elif "tt" in channel:
        ct = "(gen_match_1 == 6 || gen_match_2 == 6)"
    elif "em" in channel:
        ct = "0 == 1"
    return Selection(name="TTJ", cuts=[(f"({ct})", "tt_fakes")])


def VVT_process_selection(channel, **kwargs):
    tt_cut = ""
    if "mt" in channel:
        tt_cut = "(gen_match_1==4 && gen_match_2==5)"
    elif "et" in channel:
        tt_cut = "gen_match_1==3 && gen_match_2==5"
    elif "tt" in channel:
        tt_cut = "gen_match_1==5 && gen_match_2==5"
    elif "em" in channel:
        tt_cut = "gen_match_1==3 && gen_match_2==4"
    return Selection(name="VVT", cuts=[(f"({tt_cut})", "vvt_cut")])


def VVJ_process_selection(channel, **kwargs):
    ct = ""
    if "mt" in channel or "et" in channel:
        ct = "(gen_match_2 == 6)"
    elif "tt" in channel:
        ct = "(gen_match_1 == 6 || gen_match_2 == 6)"
    elif "em" in channel:
        ct = "0.0 == 1.0"
    return Selection(name="VVJ", cuts=[(f"({ct})", "vv_fakes")])


def VVL_process_selection(channel, **kwargs):
    emb_veto = ""
    ff_veto = ""
    if "mt" in channel:
        emb_veto = "(!(gen_match_1==4 && gen_match_2==5))"
        ff_veto = "(!(gen_match_2 == 6))"
    elif "et" in channel:
        emb_veto = "!(gen_match_1==3 && gen_match_2==5)"
        ff_veto = "!(gen_match_2 == 6)"
    elif "tt" in channel:
        emb_veto = "!(gen_match_1==5 && gen_match_2==5)"
        ff_veto = "!(gen_match_1 == 6 || gen_match_2 == 6)"
    elif "em" in channel:
        emb_veto = "!(gen_match_1==3 && gen_match_2==4)"
        ff_veto = "(1.0)"
    return Selection(
        name="VVL",
        cuts=[(f"({emb_veto})", "tt_emb_veto"), (f"({ff_veto})", "ff_veto")],
    )


def VH_process_selection(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    return Selection(
        name="VH125",
        weights=HTT_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights,
        cuts=[
            (
                "(HTXS_stage1_2_cat_pTjet30GeV>=300)&&(HTXS_stage1_2_cat_pTjet30GeV<=505)",
                "htxs_match",
            )
        ],
    )


def WH_process_selection(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    return Selection(
        name="WH125",
        weights=HTT_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights + [
            ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
            (
                "(abs(crossSectionPerEventWeight - 0.052685) < 0.001)*0.051607+"
                "(abs(crossSectionPerEventWeight - 0.03342) < 0.001)*0.032728576",
                "crossSectionPerEventWeight",
            ),
        ],
        cuts=[
            (
                "(HTXS_stage1_2_cat_pTjet30GeV>=300)&&(HTXS_stage1_2_cat_pTjet30GeV<=305)",
                "htxs_match",
            )
        ],
    )


def ZH_process_selection(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    return Selection(
        name="ZH125",
        weights=HTT_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights + [
            ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
            (
                "(abs(crossSectionPerEventWeight - 0.04774) < 0.001)*0.04683+"
                "(abs(crossSectionPerEventWeight - 0.0007771) < 0.00001)*0.0007666+"
                "(abs(crossSectionPerEventWeight - 0.0015391) < 0.0001)*0.00151848",
                "crossSectionPerEventWeight",
            ),
        ],
        cuts=[
            (
                "(HTXS_stage1_2_cat_pTjet30GeV>=400)&&(HTXS_stage1_2_cat_pTjet30GeV<=405)",
                "htxs_match",
            )
        ],
    )


def ttH_process_selection(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    ttH_weights = HTT_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights
    return Selection(name="ttH125", weights=ttH_weights)


def ggHWW_process_selection(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    ggHWW_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights + [
        ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
        ("1.1019558", "crossSectionPerEventWeight"),
    ]
    return Selection(name="ggHWW125", weights=ggHWW_weights)


def qqHWW_process_selection(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    qqHWW_weights = MC_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights + [
        ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
        ("0.0857883", "crossSectionPerEventWeight"),
    ]
    return Selection(name="qqHWW125", weights=qqHWW_weights)


def WHWW_process_selection(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    WHWW_weights = HWW_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights
    return Selection(name="WHWW125", weights=WHWW_weights)


def ZHWW_process_selection(channel, era, vs_jet_wp, vs_ele_wp, **kwargs):
    ZHWW_weights = HWW_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights
    return Selection(name="ZHWW125", weights=ZHWW_weights)


@dataclass(kw_only=True)
class _Bin:
    xsec: float
    N_events: List[int]
    negative_fractions: List[float]

    @property
    def calculate(self):
        return self.xsec / sum(_N_event * _negative_fraction for _N_event, _negative_fraction in zip(self.N_events, self.negative_fractions))


def _get_stxs_bin_or_range(*bins):
    if len(bins) == 1:
        return f"(HTXS_stage1_2_cat_pTjet30GeV == {bins[0]})"
    elif len(bins) == 2:
        return f"((HTXS_stage1_2_cat_pTjet30GeV >= {bins[0]}) && (HTXS_stage1_2_cat_pTjet30GeV <= {bins[1]}))"


def _get_stxs_stitching_weight(
    era,
    process,
    full_recreation=True,
    stage="1p2",
    granularity="fine",
    nanoAOD_version="v12",
    **kwargs,
):
    if full_recreation:
        specific_era = ("2022preEE", "2022postEE", "2023preBPix", "2023postBPix", "2024", "2025")
        specific_process = ("ggh_htautau", "vbf_htautau")  # (process,),
    else:
        specific_era = (era,)
        specific_process = (process,)

    file = pathlib.Path(__file__).parent / "STXS_stitching_details.yaml"
    try:
        with open(file, "r") as f:
            info = yaml.safe_load(f)[process]
            _ = info[era]
    except (FileNotFoundError, KeyError):
        info = calculate_stxs_N_and_negative_fractions(
            database_path=file.parent.parent.parent / "TauFakeFactors" / "datasets" / f"nanoAOD_{nanoAOD_version}",
            output_path=file,
            specific_era=specific_era,
            specific_process=specific_process,
            stage=stage,
            granularity=granularity,
        )[process]

    bins = {
        b: _Bin(
            xsec=info["xsec_inclusive"] * info[era]["xsec_fractions"][b],
            N_events=info[era]["N_events"][b],
            negative_fractions=info[era]["negative_fractions"][b],
        )
        for b in info[era]["xsec_fractions"]
    }
    sign = "(((genWeight < 0) * (-1)) + ((genWeight >= 0) * (1)))"
    category_wise_reweighting = " + ".join(
        [
            f"(({_get_stxs_bin_or_range(b)}) * ({bins[b].calculate}))"
            for b in bins
        ]
    )

    return (f"(({sign}) * ({category_wise_reweighting}))", f"{process}_stitching_weight")


def get_stxs_bin_selection(process, *bins):
    _bin = f"bin{bins[0]}" if len(bins) == 1 else f"bin{bins[0]}to{bins[-1]}"
    with LogContext(logger).suppress_logging():
        def stxs_bin_selection(**kwargs):
            return Selection(name=f"{process}_{_bin}_selection", cuts=[(_get_stxs_bin_or_range(*bins), f"{process}_{_bin}_selection")])
        stxs_bin_selection.__name__ = f"{process}_{_bin}_selection"
    return stxs_bin_selection


def ggh_stitching_weight(era, **kwargs):
    return _get_stxs_stitching_weight(era=era, process="ggh_htautau", **kwargs)


def qqh_stitching_weight(era, **kwargs):
    return _get_stxs_stitching_weight(era=era, process="vbf_htautau", **kwargs)


def ggH125_process_selection(channel, era, vs_jet_wp, vs_ele_wp, weight_stitching_ggH125=False, **kwargs):
    ggH125_weights = HTT_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights
    if weight_stitching_ggH125:
        ggH125_weights.append(ggh_stitching_weight(era))
    else:
        ggH125_weights.extend(
            [
                ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
                (
                    "(( 1.0 / negative_events_fraction) * (((genWeight<0) * -1) + ((genWeight > 0 * 1)))) * crossSectionPerEventWeight",
                    "crossSectionPerEventWeight",
                ),
            ]
        )
    ggH125_weights.append(("ggh_NNLO_weight", "gghNNLO"))

    ggH125_cuts = [
        (
            "(HTXS_stage1_2_cat_pTjet30GeV>=100)&&(HTXS_stage1_2_cat_pTjet30GeV<=116)",
            "htxs",
        )
    ]
    return Selection(name="ggH125", weights=ggH125_weights, cuts=ggH125_cuts)


def qqH125_process_selection(channel, era, vs_jet_wp, vs_ele_wp, weight_stitching_qqH125=False, **kwargs):
    qqH125_weights = HTT_base_process_selection(channel, era, vs_jet_wp, vs_ele_wp).weights
    if weight_stitching_qqH125:
        qqH125_weights.append(qqh_stitching_weight(era))
    else:
        qqH125_weights.extend(
            [
                ("numberGeneratedEventsWeight", "numberGeneratedEventsWeight"),
                (
                    "(( 1.0 / negative_events_fraction) * (((genWeight<0) * -1) + ((genWeight > 0 * 1)))) * crossSectionPerEventWeight",
                    "crossSectionPerEventWeight",
                ),
            ]
        )
    qqH125_cuts = [
        (
            "(HTXS_stage1_2_cat_pTjet30GeV>=200)&&(HTXS_stage1_2_cat_pTjet30GeV<=210)",
            "qqH125",
        )
    ]
    return Selection(name="qqH125", weights=qqH125_weights, cuts=qqH125_cuts)


def FF_training_process_selection(channel, era, **kwargs):
    cuts = []
    weights = []
    if channel == "et" or channel == "mt":
        cuts = [
            (f"id_tau_vsJet_{vs_jet_wp}_2<0.5&&id_tau_vsJet_{vs_jet_wp}_2>0.5", "tau_anti_iso"),
        ]
        weights = [("fake_factor", "fake_factor")]
    elif channel == "tt":
        Cut(
            f"""(
                    (
                        (id_tau_vsJet_Medium_1 < 0.5) &&
                        (id_tau_vsJet_Medium_2 > 0.5) &&
                        (id_tau_vsJet_VVVLoose_1 > 0.5)

                    ) ||
                    (
                        (id_tau_vsJet_Medium_1 > 0.5) &&
                        (id_tau_vsJet_Medium_2 < 0.5) &&
                        (id_tau_vsJet_VVVLoose_2 > 0.5)
                    )
                )""",
            "tau_anti_iso"
        ),
        Weight(
            f"""(
                (0.5) * (
                    ({RuntimeVariables.FF_name_tt_1} * (id_tau_vsJet_Medium_1 < 0.5)) +
                    ({RuntimeVariables.FF_name_tt_2} * (id_tau_vsJet_Medium_2 < 0.5))
                )
            )""",
            "fake_factor",
        ),
        cuts = [
            (f"""(
                    (
                        (id_tau_vsJet_Medium_1 < 0.5) &&
                        (id_tau_vsJet_Medium_2 > 0.5) &&
                        (id_tau_vsJet_VVVLoose_1 > 0.5)

                    ) ||
                    (
                        (id_tau_vsJet_Medium_1 > 0.5) &&
                        (id_tau_vsJet_Medium_2 < 0.5) &&
                        (id_tau_vsJet_VVVLoose_2 > 0.5)
                    )
                )""",
            "tau_anti_iso"),
        ]
        weights = [f"""(
                (0.5) * (
                    ({RuntimeVariables.FF_name_tt_1} * (id_tau_vsJet_Medium_1 < 0.5)) +
                    ({RuntimeVariables.FF_name_tt_2} * (id_tau_vsJet_Medium_2 < 0.5))
                )
            )""",
            "fake_factor",]
    elif channel == "em":
        raise NotImplementedError("FF training not implemented for em")
    else:
        raise ValueError("Invalid channel: {}".format(channel))
    print("FF training cuts:", cuts)
    print("FF training weights:", weights)
    return Selection(name="jetFakes", cuts=cuts, weights=weights)


class _SelectionChain(list):
    def __init__(self, functions: Union[Callable, None] = None) -> None:
        super().__init__(functions or [])
        names = [f.__name__ for f in self if hasattr(f, "__name__")]
        assert len(names) == len(functions), "All functions in the chain must have a __name__ attribute."
        self.__name__ = "_".join(names)

    def wrap_next(self, next_selection: Callable) -> '_SelectionChain':
        new_chain = _SelectionChain(self)
        new_chain.append(next_selection)
        if hasattr(next_selection, "__name__"):
            new_chain.__name__ = f"{self.__name__}_{next_selection.__name__}"
        return new_chain


def make_chainable_process_selection(base_selection: Callable) -> Callable:
    """
    Wrap a process‐selection function to allow chaining additional selections.

    This decorator takes a base_selection function (returning a Selection or tuple of Selections)
    and returns a callable `wrapper` that behaves identically to base_selection, but
    exposes a `.wrap_next(next_selection)` method. Using `.wrap_next`, you can create a new
    chainable function that, when invoked, returns a tuple of all linked Selections.

    Parameters
    ----------
    base_selection : Callable[..., Selection | Tuple[Selection, ...]]
        A function that returns a Selection or tuple of Selections for a given process.

    Returns
    -------
    Callable[..., Selection | Tuple[Selection, ...]]
        A wrapped function with an added `.wrap_next(next_selection)` method. Calling
        the wrapper yields the same result as base_selection. Calling
        `wrapper.wrap_next(next_fn)` returns a new chainable function that first calls
        the original base_selection, then next_fn, and aggregates their results.

    Examples
    --------
    >>> DY = make_chainable_process_selection(DY_process_selection)
    >>> # Call the base selection function
    >>> result1 = DY(channel="mt", era="2018", vs_jet_wp="Tight", vs_ele_wp="VLoose")
    >>> # result1 is a Selection object for DY process
    >>> # Chain the ZTT selection on top of DY
    >>> DY.TT = DY.wrap_next(ZTT_process_selection)
    >>> result2 = DY.TT(channel="mt", era="2018", vs_jet_wp="Tight", vs_ele_wp="VLoose")
    >>> # result2 is a tuple: (DY_selection, ZTT_selection)
    >>> # Chain a third selection (e.g. decay‐mode filtering if we would have such a function)
    >>> DY.TT.DM = DY.TT.wrap_next(decaymode_process_selection)
    >>> result3 = DY.TT.DM(channel="mt", era="2018", vs_jet_wp="Tight", vs_ele_wp="VLoose")
    >>> # result3 is a tuple: (DY_selection, ZTT_selection, DM_selection)
    """
    @functools.wraps(base_selection)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return base_selection(*args, **kwargs)

    def wrap_next(next_selection: Callable) -> _SelectionChain:
        return _SelectionChain([base_selection, next_selection])

    wrapper.wrap_next = wrap_next
    return wrapper


# --- Process selection aliases ---

# DY
DY = make_chainable_process_selection(DY_process_selection)
ZTT, ZL, ZJ = ZTT_process_selection, ZL_process_selection, ZJ_process_selection
DY.TT, DY.L, DY.J = DY.wrap_next(ZTT), DY.wrap_next(ZL), DY.wrap_next(ZJ)

# DY_NLO
DY_NLO = make_chainable_process_selection(DY_NLO_process_selection)
ZTT_nlo, ZL_nlo, ZJ_nlo = ZTT_nlo_process_selection, ZL_nlo_process_selection, ZJ_nlo_process_selection
DY_NLO.TT, DY_NLO.L, DY_NLO.J = DY_NLO.wrap_next(ZTT_nlo), DY_NLO.wrap_next(ZL_nlo), DY_NLO.wrap_next(ZJ_nlo)

# TT
TT = make_chainable_process_selection(TT_process_selection)
TTT, TTL, TTJ = TTT_process_selection, TTL_process_selection, TTJ_process_selection
TT.T, TT.L, TT.J = TT.wrap_next(TTT), TT.wrap_next(TTL), TT.wrap_next(TTJ)

# VV
VV = make_chainable_process_selection(VV_process_selection)
VVT, VVL, VVJ = VVT_process_selection, VVL_process_selection, VVJ_process_selection
VV.J, VV.L, VV.T = VV.wrap_next(VVJ), VV.wrap_next(VVL), VV.wrap_next(VVT)

# qqH125
qqH125 = make_chainable_process_selection(qqH125_process_selection)
for b in range(200, 211):
    exec(f"qqH125_{b} = get_stxs_bin_selection('vbf_htautau', {b})")
    exec(f"qqH125.bin{b} = qqH125.wrap_next(qqH125_{b})")

# ggH125
ggH125 = make_chainable_process_selection(ggH125_process_selection)
for b in range(100, 117):
    exec(f"ggH125_{b} = get_stxs_bin_selection('ggh_htautau', {b})")
    exec(f"ggH125.bin{b} = ggH125.wrap_next(ggH125_{b})")

# Individual and miscellaneous
ZTT_embedded = ZTT_embedded_process_selection
W = W_process_selection
HWW = HWW_process_selection
VH = VH_process_selection
WH = WH_process_selection
ZH = ZH_process_selection
ttH = ttH_process_selection
HTT = HTT_process_selection
ggHWW = ggHWW_process_selection
MC_base = MC_base_process_selection
HTT_base = HTT_base_process_selection
HWW_base = HWW_base_process_selection
qqHWW = qqHWW_process_selection
WHWW = WHWW_process_selection
ZHWW = ZHWW_process_selection
FF_training = FF_training_process_selection
