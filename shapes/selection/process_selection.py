import logging

from common.analysis import RUN2_PRODUCTION_ERAS, TAU_VS_JET_WP
from CustomLogging import setup_logging
from ntuple_processor.utils import Selection

logger = setup_logging(logger=logging.getLogger(__name__))


def _mc_selection(name, cuts=()):
    # CROWN's friend `weight`: normalization, lumi, campaign split, pileup, Z/top pT reweighting, lepton/tau/trigger SFs and btag
    return Selection(name=name, weights=[("weight", "weight")], cuts=list(cuts))


def W_process_selection(**kwargs):
    return _mc_selection("W")


def HTT_process_selection(name, cut=None, **kwargs):
    return _mc_selection(name, [(cut, "htxs")] if cut else [])


def ZTT_embedded_process_selection(channel, era, apply_wps, **kwargs):
    # 2018 embedded ntuples use emb_idsel_wgt/emb_triggersel_wgt instead of a standard MC
    # tau-ID SF and ship no id_wgt_tau_vsJet_* branch at all.
    apply_tau_id_weight = apply_wps and era not in RUN2_PRODUCTION_ERAS

    weights = [
        ("emb_genweight", "emb_genweight"),
        ("emb_idsel_wgt_1*emb_idsel_wgt_2*emb_triggersel_wgt", "emb_selection_weight"),
    ]
    if "mt" in channel:
        if era == "2018":
            weights += [
                ("gen_match_1==4 && gen_match_2==5", "emb_veto"),
                ("iso_wgt_mu_1", "isoweight"),
                ("id_wgt_mu_1", "idweight"),
                ("(trg_wgt_single_mu24ormu27)", "trgweight"),
            ]
        else:
            weights += [
                ("gen_match_1==4 && gen_match_2==5", "emb_veto"),
                ("(trg_wgt_single_mu24)", "trgweight"),
            ]
        if apply_tau_id_weight:
            weights.append((f"((gen_match_2==5)*id_wgt_tau_vsJet_{TAU_VS_JET_WP}_2 + (gen_match_2!=5))", "taubyIsoIdWeight"))
    elif "et" in channel:
        weights += [
            ("gen_match_1==3 && gen_match_2==5", "emb_veto"),
            ("(trg_wgt_single_ele30)", "trgweight"),
        ]
        if apply_tau_id_weight:
            weights.append((f"((gen_match_2==5)*id_wgt_tau_vsJet_{TAU_VS_JET_WP}_2 + (gen_match_2!=5))", "taubyIsoIdWeight"))
    elif "tt" in channel:
        weights.append(("gen_match_1==5 && gen_match_2==5", "emb_veto"))
        if apply_tau_id_weight:
            weights.append(
                (
                    f"((gen_match_1==5)*id_wgt_tau_vsJet_{TAU_VS_JET_WP}_1 + (gen_match_1!=5)) * "
                    f"((gen_match_2==5)*id_wgt_tau_vsJet_{TAU_VS_JET_WP}_2 + (gen_match_2!=5))",
                    "taubyIsoIdWeight",
                )
            )
    elif "em" in channel:
        weights += [
            ("(gen_match_1==3 && gen_match_2==4)", "emb_gen_match"),
            ("iso_wgt_ele_1 * iso_wgt_mu_2", "isoweight"),
            ("id_wgt_ele_wp90iso_1 * id_wgt_mu_2", "idweight"),
        ]
    else:
        raise ValueError(f"Embedded process selection not implemented for channel {channel}")

    return Selection(name="EMB", weights=weights)


def _gen_category_cut(channel: str, category: str) -> str:
    """`gen_category_{category}` from CROWN's shapes_preparation friend. No
    gen_category_J for em -- no hadronic tau leg to fake as a jet."""
    if category == "J" and channel == "em":
        return "0 == 1"
    return f"(gen_category_{category} > 0.5)"


def ZTT_process_selection(channel, **kwargs):
    return _mc_selection("ZTT", [(_gen_category_cut(channel, "T"), "ztt_cut")])


def ZL_process_selection(channel, **kwargs):
    return _mc_selection("ZL", [(_gen_category_cut(channel, "L"), "zl_cut")])


def ZJ_process_selection(channel, **kwargs):
    return _mc_selection("ZJ", [(_gen_category_cut(channel, "J"), "dy_fakes")])


def TTT_process_selection(channel, era, **kwargs):
    return _mc_selection("TTT", [(_gen_category_cut(channel, "T"), "ttt_cut")])


def TTL_process_selection(channel, era, **kwargs):
    return _mc_selection("TTL", [(_gen_category_cut(channel, "L"), "ttl_cut")])


def TTJ_process_selection(channel, **kwargs):
    return _mc_selection("TTJ", [(_gen_category_cut(channel, "J"), "tt_fakes")])


def VVT_process_selection(channel, **kwargs):
    return _mc_selection("VVT", [(_gen_category_cut(channel, "T"), "vvt_cut")])


def VVJ_process_selection(channel, **kwargs):
    return _mc_selection("VVJ", [(_gen_category_cut(channel, "J"), "vv_fakes")])


def VVL_process_selection(channel, **kwargs):
    return _mc_selection("VVL", [(_gen_category_cut(channel, "L"), "vvl_cut")])


ZTT, ZL, ZJ = ZTT_process_selection, ZL_process_selection, ZJ_process_selection
TTT, TTL, TTJ = TTT_process_selection, TTL_process_selection, TTJ_process_selection
VVT, VVL, VVJ = VVT_process_selection, VVL_process_selection, VVJ_process_selection
ZTT_embedded = ZTT_embedded_process_selection
W = W_process_selection
