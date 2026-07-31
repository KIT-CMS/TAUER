"""
Systematic-uncertainty definitions for SM H->tautau datacards.

Relocated from SMRun2Legacy's ``python/systematics.py`` (``run3_htt`` branch),
and *renamed to match TauKITFlow's own ``shapes/selection/variations.py`` naming
convention* rather than carrying SMRun2Legacy's naming verbatim -- see
STATUS.md ("## Phase 2d") for the full reconciliation record. Summary:

- ``shapes/selection/variations.py`` is CROWN/ntuple_processor-side: it names the
  "Up"/"Down"-shifted histograms that ``shapes/produce_shapes.py`` +
  ``shapes/do_estimations.py`` write into the shape ROOT files. Those
  histogram-name templates use bare literal placeholders ``Era`` and
  ``Channel`` (no ``$`` sigil) that get substituted with the real era/channel
  strings -- there isn't yet a "convert_to_synced_shapes"-style step in
  TauKITFlow that does this substitution downstream, so this module does it
  itself, once, via ``_resolve()`` below, before ever calling ``AddSyst``.
- SMRun2Legacy's code used CombineHarvester's own ``$ERA``/``$CHANNEL``
  wildcard sigils instead, which CombineHarvester resolves per-process at
  ``AddSyst``-time. Since the histograms this module needs to find in the
  shape file are named per variations.py's convention (no ``$``), using
  CombineHarvester's wildcards here would produce systematic names that never
  match a real histogram -- so all systematic names below use ``Era``/
  ``Channel`` literal placeholders resolved via ``_resolve()``, matching
  variations.py exactly, NOT the ``$ERA``/``$CHANNEL`` CombineHarvester sigils.
- Where a systematic source has a variations.py counterpart, the *name* here
  is copied from variations.py's up-name (stripped of "Up"/"UP") so the two
  stay byte-for-byte in sync by inspection. Where variations.py splits/groups
  a source differently than SMRun2Legacy did (jet energy scale: variations.py
  uses jet_variations.py's REGROUPED 6(+5 per-era)-source scheme, not
  SMRun2Legacy's older regional-JEC grouping or a full per-individual-source
  split; b-tagging: jet_variations.py's Run3 fixed-WP scheme
  (CMS_btag_fixedWP_*), not a full-shape or per-individual-source scheme;
  trigger: tau_triggersetup.py's CMS_eff_m_trigger/CMS_eff_e_trigger/
  CMS_trig_t_ditau_cross, not per-source SMRun2Legacy names, and these are NOT
  era-decorrelated; LHE/PS scale weights: config.py now emits one postfixed
  set per STXS stage-0 Higgs production mode (_ggH/_qqH/_VH/_ttH), not one
  shared set for all signal samples; tau ID efficiency: variations.py splits
  the lt channels by tau pT bin, not by decay mode+pT the way SMRun2Legacy's
  ``split_tau_id_and_es_by_pt`` did), this module follows variations.py's
  scheme, since that's what Phase 1 established as the CMS/Combine-convention-
  correct one and it's what the shape files will actually contain.
- Purely administrative lnN uncertainties that don't correspond to an
  ntuple-level shift (lumi, cross-section priors, THU/QCDScale theory
  uncertainties, jetFakes fake-factor systematics not yet wired into
  ``do_estimations.py``) have no variations.py counterpart by construction --
  those keep SMRun2Legacy's naming, Era/Channel-resolved. jetFakes shape
  systematics are the one exception narrowed down to match what
  ``do_estimations.py`` actually produces today (a single combined
  ``CMS_ff_total_sub_syst_Channel_Era``, not SMRun2Legacy's much larger
  per-source list of jetFakes fake-factor uncertainties -- the granular list
  is retained standalone in the ``jetFakes granular list`` comment for when
  ``do_estimations.py`` grows more FF systematic sources).

Any systematic added here that has no matching histogram in the shape ROOT
file is dropped automatically (with a logged warning) by
``tools.load_systematic_shapes`` / ``tools.filter_zero_yield_systs`` -- so
listing a systematic here is safe even before its shape-production side is
fully wired up; it just won't survive into the final datacard yet.
"""
import logging

import CombineHarvester.CombineTools.ch as ch
from config.logging_setup_configs import setup_logging


logger = setup_logging(logger=logging.getLogger(__name__))


class Channels:
    def __init__(self) -> None:
        self.all = ["et", "mt", "tt", "em"]
        self.lt_tt = ["et", "mt", "tt"]
        self.mt_tt = ["mt", "tt"]
        self.et_tt = ["et", "tt"]
        self.em_et = ["em", "et"]
        self.em_mt = ["em", "mt"]
        self.em_lt = ["em", "mt", "et"]
        self.lt = ["et", "mt"]
        self.et = ["et"]
        self.mt = ["mt"]
        self.tt = ["tt"]
        self.em = ["em"]

    def __str__(self) -> str:
        _string = "Channels:\n"
        for attr in dir(self):
            if not attr.startswith('_') and attr != 'all':
                _string += f"  {attr}: {getattr(self, attr)}\n"
        return _string

    def __repr__(self) -> str:
        return self.__str__()


class Processes:
    def __init__(self) -> None:
        self.ggH = [
            "ggH_htt",
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
        self.ggZH_had = [
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
        self.qqH = [
            "qqH_htt",
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
        self.VH_had = [
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
        self.VH = [
            # "VH_htt" is the simple stage0-scheme process name (see
            # combine_datacards/processes.py::get_signals("stxs_stage0")) --
            # matches shapes/produce_shapes.py's "vh" category, which is
            # WminusH/WplusH/ZH restricted to leptonic V decay (HTXS_stage_0
            # in {30, 40}, see shapes/selection/process_selection.py). The
            # remaining entries below are the finer STXS-submeasurement names
            # for a not-yet-produced scheme (kept for forward compatibility,
            # see module docstring).
            "VH_htt",
            "WH_lep_htt", "ZH_lep_htt", "ggZH_lep_htt", "WH_htt", "ZH_htt",
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
        # "ttH_htt" used to be folded into self.VH (wrong -- ttH is its own
        # STXS stage-0 production mode, and shapes/produce_shapes.py books it
        # as its own "tth" category, distinct from "vh"); it now has its own
        # dedicated group, matching combine_datacards/processes.py's
        # get_signals("stxs_stage0").
        self.ttH = ["ttH_htt"]
        self.ggHToWW = ["ggH_hww"]
        self.qqHToWW = ["qqH_hww"]
        self.signals = self.ggH + self.ggZH_had + self.qqH + self.VH_had + self.VH + self.ttH

        self.htt = self.ggH + self.ggZH_had + self.qqH + self.VH_had + self.VH + self.ttH
        self.hww = self.ggHToWW + self.qqHToWW + ["WH_hww", "ZH_hww"]

        self.z = ["ZTT", "ZL", "ZJ"]
        self.ttbar = ["TTT", "TTL", "TTJ", "TT"]
        self.vv = ["VVT", "VVJ", "VVL", "VV", "ST"]
        self.w = ["W"]
        self.real_tau_bkg_mc = ["ZTT", "TTT", "TTL", "VVT", "VVL"]
        self.jetFakes_bkg_mc = ["W", "TTJ", "ZJ", "VVJ"]
        self.qcd = ["QCD"]
        self.emb = ["EMB"]
        self.jetFakes = ["jetFakes"]

        self.mc_bkg = self.z + self.ttbar + self.vv + self.w
        self.mc = self.htt + self.hww + self.mc_bkg
        self.real_taus_mc = self.htt + self.real_tau_bkg_mc
        self.tes_affected_processes = self.signals + self.real_tau_bkg_mc + self.jetFakes

    def __str__(self) -> str:
        _string = "Processes:\n"
        for attr in dir(self):
            if not attr.startswith('_') and attr != 'all':
                _string += f"  {attr}: {getattr(self, attr)}\n"
        return _string

    def __repr__(self) -> str:
        return self.__str__()


# CMS tau decay-mode codes (0=1prong, 1=1prong1pizero, 10=3prong, 11=3prong1pizero)
# used by variations.py's tt-channel tau-ID naming ("dm0","dm1","dm10","dm11").
# SMRun2Legacy's own decay-mode label set, kept for the (still dm-named, not yet
# reconciled -- see module docstring) tt-channel tau-ES loop below.
tau_decaymodes = {"1prong0pizero", "1prong1pizero", "3prong0pizero", "3prong1pizero"}
DM_LABEL_TO_CODE = {
    "1prong0pizero": "dm0",
    "1prong1pizero": "dm1",
    "3prong0pizero": "dm10",
    "3prong1pizero": "dm11",
}
# variations.py's coarse (no pT-split) tauES groups (tau_es_3prong etc.): the
# "3prong" group covers CMS DM 10 (3prong0pizero); "3prong1pizero" is DM 11.
DM_LABEL_TO_TAUES_GROUP = {
    "1prong0pizero": "1prong",
    "1prong1pizero": "1prong1pizero",
    "3prong0pizero": "3prong",
    "3prong1pizero": "3prong1pizero",
}


def _resolve(name: str, era: str, channel: str = None) -> str:
    """
    Substitute variations.py's literal 'Era'/'Channel' placeholders with the
    real era/channel strings. See module docstring for why this -- not
    CombineHarvester's own $ERA/$CHANNEL sigils -- is the correct thing to do
    here: it's what makes the systematic name match the histogram names that
    shapes/produce_shapes.py + shapes/do_estimations.py actually write.
    """
    resolved = name.replace("Era", era)
    if channel is not None:
        resolved = resolved.replace("Channel", channel)
    return resolved


def add_systematics(
    cb: ch.CombineHarvester,
    era: str,
    jetfakes: bool = True,
    embedding: bool = True,
    split_tau_id_and_es_by_pt: bool = True,
    use_ml_ff_scheme: bool = True,
    correlate_emb: bool = True,
    regional_jec: bool = False,
    ggh_wg1: bool = True,
    qqh_wg1: bool = True,
    shape_systematics: bool = True,
) -> None:
    logger.debug(f"calling add_systematics {locals()}")

    channels, processes = Channels(), Processes()

    logger.debug(f"Defined channels: {channels}")
    logger.debug(f"Defined processes: {processes}")

    def add_syst(name, syst_type, procs, chans, value=1.0):
        if syst_type == "shape" and not shape_systematics:
            logger.debug(f"Skipping shape systematic {name} (shape systematics disabled)")
            return

        if isinstance(value, (float, int)):
            syst_map = ch.SystMap()(float(value))
        else:
            syst_map = value

        resolved_name = _resolve(name, era)
        logger.debug(f"Adding systematic {resolved_name} of type {syst_type} to processes {procs} in channels {chans} with value/map {value}")
        cb.cp().process(list(procs)).channel(list(chans)).AddSyst(cb, resolved_name, syst_type, syst_map)

    def add_syst_per_channel(name_template, syst_type, procs, chans, value=1.0):
        """Like add_syst, but resolves the 'Channel' placeholder per channel
        (needed for systematics whose variations.py name is channel-dependent,
        e.g. CMS_eff_trigger_Channel_Era)."""
        for chan in chans:
            add_syst(_resolve(name_template, era, chan).replace("Era", era), syst_type, procs, [chan], value)

    # ---- Lumi (no variations.py counterpart -- lnN-only, no ntuple shift) ----
    # TODO: Run3 entries below reuse the Run2 2018 value as a placeholder
    # (https://twiki.cern.ch/twiki/bin/view/CMS/TWikiLUM requires CERN SSO and
    # couldn't be fetched) -- replace with the official Run3 numbers once available.
    lumi_unc = {
        "2016": 1.012, "2016preVFP": 1.012, "2016postVFP": 1.012,
        "2017": 1.0082, "2018": 1.0084,
        "2022preEE": 1.0084, "2022postEE": 1.0084,
        "2023preBPix": 1.0084, "2023postBPix": 1.0084,
        "2024": 1.0084, "2025": 1.0084, "2026": 1.0084,
    }
    lumi_unc_corr = {
        "2016": 1.006, "2016preVFP": 1.006, "2016postVFP": 1.006,
        "2017": 1.009, "2018": 1.020,
        "2022preEE": 1.020, "2022postEE": 1.020,
        "2023preBPix": 1.020, "2023postBPix": 1.020,
        "2024": 1.020, "2025": 1.020, "2026": 1.020,
    }
    lumi_unc_1718 = {"2016": 1.0, "2017": 1.006, "2018": 1.002}

    if int(era[:4]) < 2022:
        add_syst("lumi_13TeV_Run" + era, "lnN", processes.mc, channels.all, lumi_unc.get(era, 1.0))
        add_syst("lumi_13TeV_correlated", "lnN", processes.mc, channels.all, lumi_unc_corr.get(era, 1.0))
        add_syst("lumi_13TeV_1718", "lnN", processes.mc, channels.all, lumi_unc_1718.get(era, 1.0))
    else:
        add_syst("lumi_13.6TeV_Run" + era, "lnN", processes.mc, channels.all, lumi_unc.get(era, 1.0))
        add_syst("lumi_13.6TeV_correlated", "lnN", processes.mc, channels.all, lumi_unc_corr.get(era, 1.0))

    # ---- Prefiring (variations.py: "CMS_prefiring{shift}", era-correlated -- matches) ----
    if era != "2018":
        add_syst("CMS_prefiring", "shape", processes.mc, channels.all)

    # ---- Trigger: variations.py now books CROWN's tau_triggersetup.py shift
    # names directly -- CMS_eff_m_trigger (mt), CMS_eff_e_trigger (et),
    # CMS_trig_t_ditau_cross (tt); these are NOT era-decorrelated in
    # tau_triggersetup.py, so no "Era" placeholder (unlike most other
    # systematics in this file). tau_triggersetup.py has no shift at all for
    # the em channel, so that stays a flat lnN estimate as before. ----
    add_syst("CMS_eff_e_trigger", "shape", processes.mc, channels.et)
    add_syst("CMS_eff_m_trigger", "shape", processes.mc, channels.mt)
    add_syst("CMS_trig_t_ditau_cross", "shape", processes.mc, channels.tt)
    add_syst("CMS_eff_trigger_em_Era", "lnN", processes.mc, channels.em, 1.02)

    if embedding:
        # No embedding-side shape systematic exists for et/mt/tt trigger
        # efficiency in tau_triggersetup.py (the branches that used to be
        # referenced here, singleElectronTriggerSFUp/singleMuonTriggerSFUp,
        # are explicitly MC-only -- exclude_samples includes "embedding" --
        # and there is no ditau-cross-trigger embedding shift at all; see
        # shapes/selection/variations.py). Flat lnN kept for em only.
        add_syst("CMS_eff_trigger_emb_em_Era", "lnN", processes.emb, channels.em, 1.02)

    # ---- Tau-ID WP (lnN, no variations.py shape counterpart) ----
    if correlate_emb:
        add_syst("CMS_eff_t_wp_Run" + era, "lnN", processes.htt + processes.emb + processes.real_tau_bkg_mc, channels.mt_tt, 1.03)
    else:
        add_syst("CMS_eff_t_wp_Run" + era, "lnN", processes.htt + processes.real_tau_bkg_mc, channels.mt_tt, 1.03)
        add_syst("CMS_eff_t_emb_wp_Run" + era, "lnN", processes.emb, channels.mt_tt, 1.03)

    # ---- Lepton ID (lnN, no variations.py shape counterpart at this granularity) ----
    add_syst("CMS_eff_e", "lnN", processes.mc, channels.em_et, 1.02)
    add_syst("CMS_eff_m", "lnN", processes.mc, channels.em_mt, 1.02)
    if embedding:
        if correlate_emb:
            add_syst("CMS_eff_e", "lnN", processes.emb, channels.em_et, 1.01)
            add_syst("CMS_eff_m", "lnN", processes.emb, channels.em_mt, 1.01)
            add_syst("CMS_eff_e_emb", "lnN", processes.emb, channels.em_et, 1.017)
            add_syst("CMS_eff_m_emb", "lnN", processes.emb, channels.em_mt, 1.017)
        else:
            add_syst("CMS_eff_e_emb", "lnN", processes.emb, channels.em_et, 1.02)
            add_syst("CMS_eff_m_emb", "lnN", processes.emb, channels.em_mt, 1.02)

    # ---- Electron ES (variations.py: CMS_scale_e{shift}, CMS_res_e{shift} -- matches) ----
    add_syst("CMS_scale_e", "shape", processes.mc, channels.em_et)
    add_syst("CMS_res_e", "shape", processes.mc, channels.em_et)
    add_syst("CMS_scale_e_emb", "shape", processes.emb, channels.em_et)

    # ---- Tau-ID efficiency, lt channels: variations.py splits by tau-pT bin
    # (30-35, 35-40, 40-500, 500-1000, 1000-Inf), NOT by decay mode+pT the way
    # SMRun2Legacy's split_tau_id_and_es_by_pt did -- follow variations.py. ----
    for pt_bin in ["30-35", "35-40", "40-500", "500-1000", "1000-Inf"]:
        name = f"CMS_eff_t_{pt_bin}_Era"
        add_syst(name, "shape", processes.real_taus_mc, channels.lt)
        if embedding:
            if pt_bin == "1000-Inf":
                continue  # emb_tau_id_eff_lt only goes up to 40-Inf, see variations.py
            emb_pt_bin = "40-Inf" if pt_bin == "40-500" else pt_bin
            if correlate_emb:
                add_syst(name, "shape", processes.emb, channels.lt)
            add_syst(f"CMS_eff_t_emb_{emb_pt_bin}_Era", "shape", processes.emb, channels.lt)

    # ---- Tau-ID efficiency, tt channel: variations.py uses CMS DM codes
    # (dm0, dm1, dm10, dm11), not SMRun2Legacy's decay-mode label strings. ----
    for dm_label, dm_code in DM_LABEL_TO_CODE.items():
        add_syst(f"CMS_eff_t_{dm_code}_Era", "shape", processes.real_taus_mc, channels.tt)
        if embedding:
            add_syst(f"CMS_eff_t_emb_{dm_code}_Era", "shape", processes.emb, channels.tt)
    add_syst("CMS_eff_t_$CHANNEL_wp_Run" + era, "lnN", processes.real_taus_mc, channels.tt, 1.014)
    add_syst("CMS_eff_t_emb_wp_Run" + era, "lnN", processes.emb, channels.tt, 1.012)
    add_syst("CMS_eff_t_Run" + era, "lnN", {"W", "ZJ", "TTJ", "VVJ"}, channels.tt, 1.06)

    # ---- Tau ES: variations.py uses coarse groups (3prong, 3prong1pizero,
    # 1prong, 1prong1pizero) with NO pT split -- SMRun2Legacy's
    # split_tau_id_and_es_by_pt therefore has no counterpart and is not used
    # for naming (kept as a no-op argument for CLI compatibility). ----
    for dm_label, taues_group in DM_LABEL_TO_TAUES_GROUP.items():
        tes_name = f"CMS_scale_t_{taues_group}_Era"
        add_syst(tes_name, "shape", processes.real_taus_mc, channels.lt)
        if embedding:
            if correlate_emb:
                add_syst(tes_name, "shape", processes.emb, channels.lt)
            add_syst(f"CMS_scale_t_emb_{taues_group}_Era", "shape", processes.emb, channels.lt)
        if jetfakes:
            add_syst(tes_name, "shape", processes.jetFakes, channels.lt)
            if embedding:
                add_syst(f"CMS_scale_t_emb_{taues_group}_Era", "shape", processes.jetFakes, channels.lt)

    # tt-channel tau ES: no variations.py counterpart yet (variations.py's tau ES
    # groups are lt-only) -- keep SMRun2Legacy's dm-loop naming, Era-resolved.
    for dm_label in tau_decaymodes:
        add_syst(f"CMS_eff_t_dm_{dm_label}_Run" + era, "shape", processes.real_taus_mc, channels.tt)
        if embedding:
            add_syst(f"CMS_eff_t_dm_{dm_label}_Run" + era, "shape", processes.emb, channels.tt, 0.5)

    # ---- Jet Energy Scale/Resolution + fixed-WP b-tag SF: variations.py's
    # jet_energy_scale(era)/jet_energy_resolution(era)/btag_fixedWP(era) --
    # jet_variations.py's REGROUPED (Run3-only, unconditionally on for this
    # analysis) scheme: 6 fully-era-correlated JES sources, 5 more
    # per-era-decorrelated ones, JER, and 4 fixed-WP b-tag components. The
    # old 27-source per-individual-JES-source list and the legacy Run2
    # full-shape / "btagging_2024" b-tag name sets matched neither
    # jet_variations.py's actual output nor anything shapes/produce_shapes.py
    # books, and are removed.
    #
    # CROWN embeds its OWN era tag (not the raw `era` string) into the
    # per-era-decorrelated names -- e.g. "2022postEE" -> "2022EE" -- so this
    # uses a local era_tag lookup rather than the generic Era-placeholder
    # _resolve() the rest of this file relies on.
    _JES_ERA_MAP = {
        "2018": "2018",
        "2022preEE": "2022", "2022postEE": "2022EE",
        "2023preBPix": "2023", "2023postBPix": "2023BPix",
        "2024": "2024", "2025": "2025", "2026": "2026",
    }
    era_tag = _JES_ERA_MAP.get(era)
    if era_tag is not None:
        for src in ["Total", "Absolute", "FlavorQCD", "BBEC1", "HF", "EC2", "RelativeBal"]:
            add_syst(f"CMS_scale_j_{src}", "shape", processes.mc, channels.all)
        for src in ["Absolute", "BBEC1", "HF", "EC2", "RelativeSample"]:
            add_syst(f"CMS_scale_j_{src}_{era_tag}", "shape", processes.mc, channels.all)
        add_syst(f"CMS_res_j_{era_tag}", "shape", processes.mc, channels.all)
        # Fixed-WP b-tag scheme (jet_variations.py) is Run3-only; the Run2
        # full-shape scheme it replaces for 2018 isn't booked in
        # shapes/produce_shapes.py (2018 shape production is background-only).
        if int(era[:4]) >= 2022:
            add_syst("CMS_btag_fixedWP_bc_correlated", "shape", processes.mc, channels.all)
            add_syst(f"CMS_btag_fixedWP_bc_uncorrelated_{era_tag}", "shape", processes.mc, channels.all)
            add_syst("CMS_btag_fixedWP_light_correlated", "shape", processes.mc, channels.all)
            add_syst(f"CMS_btag_fixedWP_light_uncorrelated_{era_tag}", "shape", processes.mc, channels.all)
    # Note: the 2018-only HEM15/16 shift (CMS_scale_j_HEMIssue_2018) is not
    # booked in shapes/produce_shapes.py either, so it's not added here.

    # ---- MET energy scale and recoil (variations.py: matches exactly) ----
    add_syst("CMS_scale_met_unclustered_Era", "shape", processes.htt + processes.hww + processes.z + processes.ttbar + processes.w + processes.vv, channels.all)
    add_syst("CMS_htt_boson_scale_met_Era", "shape", processes.htt + processes.hww + processes.z + processes.w, channels.all)
    add_syst("CMS_htt_boson_res_met_Era", "shape", processes.htt + processes.hww + processes.z + processes.w, channels.all)

    # ---- Background normalizations (lnN, no variations.py shape counterpart) ----
    add_syst("CMS_htt_vvXsec", "lnN", processes.vv, channels.all, 1.05)
    add_syst("CMS_htt_tjXsec", "lnN", processes.ttbar, channels.all, 1.06)
    add_syst("CMS_htt_wjXsec", "lnN", processes.w, channels.all, 1.04)
    add_syst("CMS_htt_zjXsec", "lnN", processes.z, channels.all, 1.02)

    add_syst("CMS_ExtrapSSOS_Channel_Run" + era, "lnN", processes.qcd, channels.et, 1.05)
    add_syst_per_channel("CMS_ExtrapSSOS_Channel_Run" + era, "lnN", processes.qcd, channels.mt, 1.03)
    add_syst_per_channel("CMS_ExtrapABCD_Channel_Run" + era, "lnN", processes.qcd, channels.tt, 1.03)

    for src in {"0jet", "1jet", "2jet"}:
        for src2 in {"rate", "shape", "shape2"}:
            add_syst(f"CMS_htt_qcd_{src}_{src2}_Era", "shape", processes.qcd, channels.em)
    add_syst("CMS_htt_qcd_iso", "shape", processes.qcd, channels.em)

    # ---- Drell-Yan / ttbar shape reweighting (variations.py: no counterpart --
    # these are theory shape uncertainties on the reweighting itself) ----
    if era == "2016":
        add_syst("CMS_htt_dyShape_Era", "shape", processes.z, channels.all, 0.10)
    else:
        add_syst("CMS_htt_dyShape", "shape", processes.z, channels.all, 0.10)
    add_syst("CMS_htt_ttbarShape", "shape", processes.ttbar, channels.all)

    # ---- Electron/muon to tau fakes (ZL) energy scale: variations.py's
    # ele_fake_es_1prong(1pizero) is eta-binned (barrel/endcap), coarser than
    # SMRun2Legacy's WH1..5 mu-fake bins -- follow variations.py for et,
    # keep SMRun2Legacy's mt mu-fake naming (variations.py's mu_fake_es_inc
    # is a single inclusive CMS_ZLShape_mt_Era, matches directly). ----
    add_syst("CMS_ZLShape_mt_Era", "shape", {"ZL"}, channels.mt)
    add_syst("CMS_ZLShape_et_1prong_barrel_Era", "shape", {"ZL"}, channels.et)
    add_syst("CMS_ZLShape_et_1prong_endcap_Era", "shape", {"ZL"}, channels.et)
    add_syst("CMS_ZLShape_et_1prong1pizero_barrel_Era", "shape", {"ZL"}, channels.et)
    add_syst("CMS_ZLShape_et_1prong1pizero_endcap_Era", "shape", {"ZL"}, channels.et)

    # ---- Pileup (variations.py: CMS_PileUp{shift}, era-correlated -- matches) ----
    add_syst("CMS_PileUp", "shape", processes.mc, channels.all)

    # ---- Jet->tau fakes (variations.py: CMS_htt_fake_j_Era, AddWeight-based -- matches) ----
    add_syst("CMS_htt_fake_j_Era", "shape", processes.jetFakes_bkg_mc, channels.lt_tt)

    # ---- Embedded events (lnN/shape, no variations.py counterpart) ----
    add_syst("CMS_htt_doublemutrg_Run" + era, "lnN", processes.emb, channels.all, 1.04)
    add_syst("CMS_htt_emb_ttbar_Run" + era, "shape", processes.emb, channels.all)

    # ---- jetFakes uncertainties: TauKITFlow's shapes/do_estimations.py only
    # wires up a single combined fake-factor shape systematic today
    # (CMS_ff_total_sub_syst_Channel_Era, per grep) -- not SMRun2Legacy's full
    # per-source (QCD/Wjets/ttbar x DR_SR_correction/non_closure/fractions/...)
    # list. Add what's actually produced; the granular per-source list is left
    # here (commented) for when do_estimations.py grows more FF systematics. ----
    if jetfakes:
        add_syst_per_channel("CMS_ff_total_sub_syst_Channel_Era", "shape", processes.jetFakes, channels.lt)
        # Granular SMRun2Legacy list (not yet produced by do_estimations.py):
        # for unc in [
        #     *[f"ff_{p}" for p in ["QCD", "Wjets"]],
        #     *[f"ff_{p}Stat" for p in ["QCD", "Wjets", "ttbar"]],
        #     *[f"fractions_{p}" for p in ["QCD", "Wjets", "ttbar"]],
        #     *[f"fractions_{p}Stat" for p in ["QCD", "Wjets", "ttbar"]],
        #     *[f"{p}_DR_SR_correction" for p in ["QCD"]],
        #     *[f"{p}_DR_SR_correctionStat" for p in ["QCD", "Wjets"]],
        #     *[f"{p}_non_closure_CorrStat1Sigma" for p in ["QCD", "Wjets", "ttbar"]],
        #     *[f"{p}_non_closure_CorrSystBandAsym" for p in ["QCD", "Wjets", "ttbar"]],
        #     *[f"{p}_non_closure_CorrSystMCShift" for p in ["QCD", "Wjets"]],
        #     *[f"{p}Normalization" for p in ["ff_QCD", "ff_Wjets", "ff_ttbar"]],
        # ]:
        #     add_syst_per_channel(f"CMS_{unc}_Channel_Era", "shape", processes.jetFakes, channels.lt)

    # ---- Theory uncertainties (lnN/shape, no variations.py counterpart --
    # these are LO/QCDScale/PDF theory priors, inherently era-independent) ----
    add_syst("BR_htt_THU", "lnN", processes.htt, channels.all, 1.0117)
    add_syst("BR_htt_PU_mq", "lnN", processes.htt, channels.all, 1.0099)
    add_syst("BR_htt_PU_alphas", "lnN", processes.htt, channels.all, 1.0061)
    add_syst("BR_hww_THU", "lnN", processes.hww, channels.all, 1.0098)
    add_syst("BR_hww_PU_mq", "lnN", processes.hww, channels.all, 1.0097)
    add_syst("BR_hww_PU_alphas", "lnN", processes.hww, channels.all, 1.0063)

    if ggh_wg1:
        for src in {"Mig01", "Mig12", "Mu", "PT60", "PT120", "Res", "qqh2j", "qqh3j", "qmtop"}:
            add_syst(f"THU_ggH_{src}", "shape", processes.ggH, channels.all)
    else:
        add_syst("QCDScale_ggH", "lnN", processes.ggH + processes.ggHToWW, channels.all, 1.039)

    if qqh_wg1:
        for src in {"TOT", "PTH200", "Mjj60", "Mjj120", "Mjj350", "Mjj700", "Mjj1000", "Mjj1500", "25", "JET01"}:
            add_syst(f"THU_qqH_{src}", "shape", processes.qqH, channels.all)
    else:
        add_syst("QCDScale_qqH", "lnN", processes.qqH + processes.qqHToWW, channels.all, 1.005)

    # variations.py: LHE_alphaS_{postfix}{shift}, LHE_pdf_{postfix}{shift},
    # LHE_scale_muF_norm_{postfix}{shift}, LHE_scale_muR_norm_{postfix}{shift},
    # PS_scale_Fsr_norm_{postfix}{shift}, PS_scale_Isr_norm_{postfix}{shift}
    # for postfix in {ggH, qqH, VH, ttH} -- postfixed per STXS stage-0 Higgs
    # production mode, since config.py's "LHE Scale Weight variations" block
    # now emits one set of branches per mode (uncorrelated nuisances across
    # modes) rather than one shared set for all signal samples.
    for postfix, procs in (
        ("ggH", processes.ggH),
        ("qqH", processes.qqH),
        ("VH", processes.VH),
        ("ttH", processes.ttH),
    ):
        add_syst(f"LHE_alphaS_{postfix}", "shape", procs, channels.all)
        add_syst(f"LHE_pdf_{postfix}", "shape", procs, channels.all)
        add_syst(f"LHE_scale_muF_norm_{postfix}", "shape", procs, channels.all)
        add_syst(f"LHE_scale_muR_norm_{postfix}", "shape", procs, channels.all)
        add_syst(f"PS_scale_Fsr_norm_{postfix}", "shape", procs, channels.all)
        add_syst(f"PS_scale_Isr_norm_{postfix}", "shape", procs, channels.all)

    for src in {"muF_", "muR_"}:
        add_syst(f"ggH_scale_0jet_{src}", "shape", processes.ggH, channels.all)
        add_syst(f"ggH_scale_1jet_lowpt_{src}", "shape", processes.ggH, channels.all)
        add_syst(f"ggH_scale_2jet_lowpt_{src}", "shape", processes.ggH, channels.all)
        add_syst(f"ggH_scale_highpt_{src}", "shape", processes.ggH, channels.all)
        add_syst(f"ggH_scale_qqh_{src}", "shape", processes.ggH, channels.all)
        add_syst(f"ggH_scale_very_highpt_{src}", "shape", processes.ggH, channels.all)

        add_syst(f"qqh_scale_0jet_{src}", "shape", processes.qqH, channels.all)
        add_syst(f"qqh_scale_1jet_{src}", "shape", processes.qqH, channels.all)
        add_syst(f"qqh_scale_highmjj_highpt_{src}", "shape", processes.qqH, channels.all)
        add_syst(f"qqh_scale_highmjj_lowpt_{src}", "shape", processes.qqH, channels.all)
        add_syst(f"qqh_scale_lowmjj_{src}", "shape", processes.qqH, channels.all)
