"""
Channel selection for the SM H→ττ analysis.
Triggers, lepton isolation, tau ID WPs, and veto cuts for
et, mt, tt, em channels in Run3 eras (2022preEE … 2025), plus
2018 (mt/mm only — see config.analysis.RUN2_PRODUCTION_ERAS, Phase 2a).

Tau ID (vsEle/vsMu) and trigger cuts for mt/et/tt, Run3 eras (2022preEE…2026):
read directly from config/cuts.yaml via get_preselection_cuts() — this is the
same call generate_tff_configs.py uses to populate the TFF submodule's
preselection_{ch}.yaml event_selection block, so the two are guaranteed
identical without needing the TauFakeFactors submodule/config present at all
for shape production (Phase 6f: TFF configs were a generated mirror of
cuts.yaml for these eras, so shapes now reads the source directly).

2018 is the one exception: it's outside RUN3_ERAS (generate_tff_configs.py
never regenerates it), so its TFF preselection_mt.yaml is genuinely
hand-maintained upstream content with real Run2-UL branch-naming differences
not mirrored in cuts.yaml — for 2018 we still read the real TFF YAML via
tff_adapter. That YAML's `had_tau_id_vs_mu` cut also omits the vsEle-WP slot
from the vsMu discriminator branch name (a bug in the YAML itself, not fixed
there since that means touching the TauFakeFactors submodule); worked around
in `_apply_wp_params` below.
"""
import logging
import re

from ntuple_processor.utils import Selection, WarnDict
from config.logging_setup_configs import setup_logging
from config.analysis import (
    PRESELECTION_MASK_BRANCH,
    RUN2_PRODUCTION_ERAS,
    SUPPORTED_ERAS,
    get_channel_selection_cuts,
    get_preselection_cuts,
)
from config.shapes.tff_adapter import get_tff_event_selection

logger = setup_logging(logger=logging.getLogger(__name__))


def _apply_wp_params(expr: str, vs_ele_wp: str) -> str:
    """Substitute the vsEle WP in tau discriminator expressions from TFF YAML.

    Handles both vsEle (`id_tau_vsEle_{WP}_{leg}`) and vsMu
    (`id_tau_vsMu_{fixedWP}_{WP}_{leg}`) patterns, replacing (or inserting)
    the vsEle-WP slot with `vs_ele_wp`.

    The vsMu branch always carries a vsEle-WP slot in the real CROWN
    ntuples — confirmed for both Run3 (`id_tau_vsMu_Tight_VVLoose_2`) and
    the Phase 2a 2018 validation production (`id_tau_vsMu_Tight_VVLoose_2` /
    `id_tau_vsMu_Tight_Tight_2`). TauFakeFactors'
    `configs/smhtt_ul/2018/preselection_mt.yaml` omits that slot
    (`id_tau_vsMu_Tight_2`) — a bug in that YAML we're not fixing there
    (out of scope: don't modify TauFakeFactors). Worked around here: the
    vsMu regex tolerates both the one-token (buggy 2018 YAML) and
    two-token (Run3 YAML) forms and always rewrites to the correct
    two-token form.
    """
    expr = re.sub(r'(id_tau_vsEle_)\w+(_\d+)', rf'\g<1>{vs_ele_wp}\g<2>', expr)
    expr = re.sub(r'id_tau_vsMu_(\w+?)(?:_\w+)?(_\d+)\b', rf'id_tau_vsMu_\g<1>_{vs_ele_wp}\g<2>', expr)
    return expr


def modify_for_ff_DR(obj: WarnDict, region: str, channel: str | None):
    """Flip the OS sign and tau-ID cuts for the fake-factor DR region."""
    if region in ("wjet", "qcd"):
        obj["os"] = "((q_1 * q_2) > 0)"   # same-sign
    elif region == "ttbar":
        pass  # keep OS, but tau-ID inversion applied per-channel below
    if channel == "mt" or channel == "et":
        obj.pop("tau_iso", None)
        obj["tau_antiiso"] = obj.get("tau_antiiso", "(id_tau_vsJet_Medium_2 < 0.5)")
    elif channel == "tt":
        obj.pop("tau_iso", None)
        obj["tau_antiiso_1"] = "(id_tau_vsJet_Medium_1 < 0.5)"
        obj["tau_antiiso_2"] = "(id_tau_vsJet_Medium_2 < 0.5)"


def channel_selection(
    channel: str,
    era: str,
    special=None,
    vs_jet_wp: str = "Tight",
    vs_ele_wp: str = "VVLoose",
    selection_option: str = "CR",
    preselected: bool = False,
    use_masks: bool = False,
    **kwargs,
) -> Selection:
    """
    Return the channel-level Selection for shape production.

    Parameters
    ----------
    preselected:
        When *True* the input ntuples have already been processed by
        ``shapes/preselect.py``, which applied the TFF event-selection cuts
        (tau ID vs-ele/vs-mu, trigger, tau-pt, lepton-pt, decay-mode).
        In that case those cuts are skipped here to avoid redundancy.
        All cuts that are *not* part of the TFF preselection — opposite-sign,
        extra-lepton vetoes, jet-veto-map, tau-vs-jet WP, lepton isolation, and
        mt cut — are always applied.
    use_masks:
        When *True* (and ``preselected`` is False) the input ntuples carry
        CROWN's precomputed ``presel_mask`` branch, so every preselection-derived
        cut — the tau decay mode, the vsEle/vsMu discriminators, the tau-pt +
        trigger cut, the jet veto map, and em's electron_eta — collapses into
        the single named cut ``Cut("presel_mask > 0.5", "presel_mask")``.
        Detected once per (era, channel) by ``shapes/produce_shapes.py`` from
        the first input file via ``config.analysis.masks_available()``;
        ``--force-legacy-cuts`` pins it to False. Old (maskless) ntuples and
        Run2 2018 (whose CROWN production predates the masks entirely) simply
        never see it set, so the tff_adapter path below is untouched.

        Deliberately scoped to the *preselection*-derived cuts only. Every
        ``channel_selection:`` cut (os, tau_iso, the three vetoes, the lepton
        isos, mt_cut and the hardcoded pt/mt cuts) stays a named string cut,
        because ``shapes/selection/variations.py`` replaces cuts BY NAME
        (``ReplaceCut("same_sign", "os", ...)``,
        ``ReplaceCut(..., "tau_iso", ...)``) and those variations must keep
        working identically on masked and unmasked inputs.

        os/ss note: swapping the ``os`` cut's *expression* to ``sel_os > 0.5``
        was considered and rejected. It would only be correct if the matching
        same-sign variations also switched to ``sel_ss > 0.5``, and those live
        as ~12 module-level constants in variations.py
        (``same_sign``, ``same_sign_em``, ``abcd_same_sign``,
        ``same_sign_anti_iso_lt``, the per-era em QCD-weight family, …) built
        at import time, with no access to a per-run ``use_masks``. Making them
        runtime-parameterised means turning every one into a factory and
        rewiring produce_shapes.py's variation registration — a large, risky
        diff for zero physics gain, since ``sel_os``/``sel_ss`` encode exactly
        ``(q_1*q_2) < 0`` / ``> 0``. So os/ss stay literal charge-product
        expressions everywhere; ``sel_os``/``sel_ss`` are still written and
        kept through the skim for TauFakeFactors' use.
    """
    if era not in SUPPORTED_ERAS:
        raise ValueError(f"Era '{era}' is not a supported era. Supported: {SUPPORTED_ERAS}")

    # Phase 5.2: these used to be hardcoded literals here, verbatim-duplicating
    # (without ever reading) config/cuts.yaml's `channel_selection:` block --
    # confirmed dead YAML by grep before this fix (see STATUS.md Phase 5.2).
    # Single-sourced now: config.analysis.get_channel_selection_cuts() reads
    # config/cuts.yaml directly, so editing the YAML is enough -- no shadow
    # copy to keep in sync here anymore.
    _cs_cuts = get_channel_selection_cuts(channel)
    cuts = WarnDict()
    cuts["extraelec_veto"] = _cs_cuts["extraelec_veto"]
    cuts["extramuon_veto"] = _cs_cuts["extramuon_veto"]
    cuts["dilepton_veto"] = _cs_cuts["dilepton_veto"]
    cuts["os"] = _cs_cuts["os"]

    # Mask path: one named cut stands in for every preselection-derived cut.
    # Only when the input has NOT already been preselected -- a preselected
    # input had those cuts applied by shapes/preselect.py (whichever path it
    # took there), so re-applying anything here would be redundant.
    #
    # Behaviour note, deliberate and worth knowing: presel_mask is the FULL
    # per-channel `preselection:` block of config/cuts.yaml, which includes
    # `had_tau_decay_mode` — a cut the legacy branch below never applied when
    # reading raw ntuples (it only picks had_tau_id_vs_ele/vs_mu/had_tau_pt/
    # lep_pt out of that same block, plus jet_veto above). So a raw-ntuple
    # run with masks is very slightly TIGHTER than the same run with
    # --force-legacy-cuts, by exactly the decay-mode requirement. That matches
    # what the preselected (--presel-dir) path has always done, i.e. the mask
    # path makes raw-ntuple and preselected runs agree where they previously
    # did not.
    _use_presel_mask = use_masks and not preselected
    if _use_presel_mask:
        logger.info(
            f"[{era}/{channel}] channel_selection: preselection via CROWN "
            f"'{PRESELECTION_MASK_BRANCH}' branch (single cut replaces the "
            f"tau-ID/trigger/tau-pt/decay-mode/jet-veto cut strings)"
        )
        cuts["presel_mask"] = f"({PRESELECTION_MASK_BRANCH} > 0.5)"
    # jet_veto is single-sourced from config/cuts.yaml's `preselection:` block
    # (config.analysis.get_preselection_cuts()) -- the same value
    # shapes/preselect.py already applies to signal samples via that function.
    # Branch is lowercase in CROWN output for both Run3 (verified against the
    # 2024 validation ntuples) and 2018 (verified against the Phase 2a
    # validation ntuples) -- "Jet_vetomap" (capital J) does not exist in
    # either and would raise an unknown-column error at RDataFrame runtime.
    # config/cuts.yaml's preselection.*.jet_veto entries were already fixed to
    # the correct lowercase branch name (see STATUS.md Blocker #1); this used
    # to carry its own separate hardcoded copy of the same fix, now removed.
    # Every Run3 channel (et/mt/tt/em) now defines jet_veto in cuts.yaml's
    # preselection: block; the default is kept only as a guard for eras/
    # channels configured without one (e.g. Run2 2018).
    # (subsumed by presel_mask on the mask path -- jet_veto is part of the
    # same preselection: block the mask encodes)
    if not _use_presel_mask:
        cuts["jet_vetomap"] = get_preselection_cuts(era, channel).get(
            "jet_veto", "(jet_vetomap < 0.5)"
        )
    # Phase 5.1 (2026-07-15) root-cause + fix: these two global cuts exist,
    # active (uncommented), in smhtt_ul's live reference channel_selection()
    # (config/shapes/channel_selection.py, applied unconditionally for every
    # channel before the per-channel branch) but were entirely missing here.
    # This was the dominant contributor to the TT-TTT/TTL/TTJ and VV-VVT/VVL/VVJ
    # residuals: a real bin-by-bin comparison of a fresh 2024/mt rerun against
    # smhtt_ul (before this fix) showed new/legacy raw ratios of 0.61-0.78 for
    # every TT/VV subprocess, not explained by the (much smaller) lumi/btag/
    # ttbar_em_weight differences alone — TauKITFlow was passing strictly more
    # events through by missing this extra pt_2 threshold and the tighter mt
    # cut. See STATUS.md Phase 5.1 for the full before/after numbers.
    cuts["pt"] = "(pt_2 > 25)"
    cuts["mt"] = "(mt_1 < 60)"

    if "DR;ff" in selection_option:
        modify_for_ff_DR(obj=cuts, region=selection_option.split(";")[-1], channel=None)

    _wps = {"VVTight", "Tight", "Medium", "Loose", "VLoose", "VVLoose", "VVVLoose"}
    if vs_ele_wp not in _wps:
        raise ValueError(f"'{vs_ele_wp}' is not a valid vsEle WP")
    if vs_jet_wp not in _wps:
        raise ValueError(f"'{vs_jet_wp}' is not a valid vsJet WP")

    if special is None or special == "TauES":
        # TauES production reuses the same channel-level cuts as the regular
        # analysis; only the categorization (config/shapes/taues_measurement_binning.py)
        # and the additional per-shift embedded datasets differ (see
        # shapes/produce_shapes.py's --special-analysis TauES wiring).
        if channel in ("mt", "et", "tt"):
            # Tau ID (vsEle/vsMu) and trigger cuts. Run3 eras read cuts.yaml
            # directly (see module docstring); 2018 reads the real TFF YAML
            # since it isn't generated from cuts.yaml.
            # When reading from preselected files these cuts are already
            # applied; on the mask path `presel_mask` above already covers
            # all three (2018/tff_adapter never takes the mask path -- that
            # production predates the masks, so masks_available() reports
            # False for it and the branch below stays exactly as it was).
            if not preselected and not _use_presel_mask:
                if era in RUN2_PRODUCTION_ERAS:
                    tff_sel = get_tff_event_selection(era, channel)
                else:
                    tff_sel = get_preselection_cuts(era, channel)
                cuts["againstElectronDiscriminator"] = (
                    f"({_apply_wp_params(tff_sel['had_tau_id_vs_ele'], vs_ele_wp)})"
                )
                cuts["againstMuonDiscriminator"] = (
                    f"({_apply_wp_params(tff_sel['had_tau_id_vs_mu'], vs_ele_wp)})"
                )
                # had_tau_pt = tau pt (+ trigger for tt); lep_pt = lepton trigger (mt/et only)
                _trg = [tff_sel["had_tau_pt"]]
                if "lep_pt" in tff_sel:
                    _trg.append(tff_sel["lep_pt"])
                cuts["trg_selection"] = " && ".join(f"({p.strip()})" for p in _trg)
            if "DR;ff" in selection_option:
                modify_for_ff_DR(obj=cuts, region=selection_option.split(";")[-1], channel=channel)
            # vsJet tau isolation — not in TFF preselection, parameterised here.
            # tau_iso's cuts.yaml value carries a literal `{vs_jet_wp}`
            # placeholder (see the YAML's own comment); substituted here at
            # the one call site that knows the runtime WP choice.
            if channel == "tt":
                cuts["tau_iso"] = _cs_cuts["tau_iso"].format(vs_jet_wp=vs_jet_wp)
            else:
                cuts["tau_iso"] = _cs_cuts["tau_iso"].format(vs_jet_wp=vs_jet_wp)
                cuts["mt_cut"] = _cs_cuts["mt_cut"]
                _iso_key = "muon_iso" if channel == "mt" else "ele_iso"
                cuts[_iso_key] = _cs_cuts[_iso_key]
            return Selection(name=channel, cuts=cuts)

        if "em" in channel:
            # Same split as mt/et/tt above: the preselection-level cuts
            # (electron acceptance + trigger leg) come from cuts.yaml's
            # preselection: block and are skipped when the input has already
            # been preselected; isolation is shape-production-only and always
            # applied, from cuts.yaml's channel_selection: block.
            # (em's presel_mask covers electron_eta + lep_pt + jet_veto -- em
            # is the one scope with no FF-region masks, but it does get the
            # common presel_mask/sel_os/sel_ss.)
            if not preselected and not _use_presel_mask:
                _presel = get_preselection_cuts(era, channel)
                cuts["electron_eta"] = f"({_presel['electron_eta']})"
                cuts["trg_selection"] = f"({_presel['lep_pt']})"
            _cs_cuts = get_channel_selection_cuts(channel, era)
            cuts["ele_iso"] = _cs_cuts["ele_iso"]
            cuts["muon_iso"] = _cs_cuts["muon_iso"]
            return Selection(name="em", cuts=cuts)

        raise ValueError(f"Channel '{channel}' is not supported (Run3: et, mt, tt, em).")
    raise NotImplementedError(f"special={special!r} not implemented for Run3 channel_selection.")
