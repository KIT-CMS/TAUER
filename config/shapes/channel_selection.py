"""
Channel selection for the SM H→ττ analysis.
Triggers, lepton isolation, tau ID WPs, and veto cuts for
et, mt, tt, em channels in Run3 eras (2022preEE … 2025), plus
2018 (mt/mm only — see config.analysis.RUN2_PRODUCTION_ERAS, Phase 2a).

Tau ID (vsEle/vsMu) and trigger cuts for mt/et/tt are read from
TauFakeFactors preselection YAMLs via tff_adapter, so they stay
in sync with the FF measurement selection automatically. The TFF
submodule already ships a configs/smhtt_ul/2018 preselection set
whose event_selection block for mt matches the real 2018 CROWN
branch names (verified against the Phase 2a validation ntuples),
with one exception worked around in `_apply_wp_params` below: that
YAML's `had_tau_id_vs_mu` cut omits the vsEle-WP slot from the vsMu
discriminator branch name (a bug in the YAML itself, not fixed
there since that means touching the TauFakeFactors submodule).
"""
import logging
import re

from ntuple_processor.utils import Selection, WarnDict
from config.logging_setup_configs import setup_logging
from config.analysis import SUPPORTED_ERAS
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
    """
    if era not in SUPPORTED_ERAS:
        raise ValueError(f"Era '{era}' is not a supported era. Supported: {SUPPORTED_ERAS}")

    cuts = WarnDict()
    cuts["extraelec_veto"] = "(extraelec_veto < 0.5)"
    cuts["extramuon_veto"] = "(extramuon_veto < 0.5)"
    cuts["dilepton_veto"] = "(dilepton_veto < 0.5)"
    cuts["os"] = "((q_1 * q_2) < 0)"
    # Branch is lowercase in CROWN output for both Run3 (verified against the
    # 2024 validation ntuples) and 2018 (verified against the Phase 2a
    # validation ntuples) — "Jet_vetomap" (capital J) does not exist in
    # either and would raise an unknown-column error at RDataFrame runtime.
    # Pre-existing bug found while extending to 2018, fixed here for both.
    cuts["jet_vetomap"] = "(jet_vetomap < 0.5)"

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
            # Tau ID (vsEle/vsMu) and trigger are read from TFF preselection YAML,
            # keeping them in sync with the FF measurement selection per era.
            # When reading from preselected files these cuts are already applied.
            if not preselected:
                tff_sel = get_tff_event_selection(era, channel)
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
            # vsJet tau isolation — not in TFF preselection, parameterised here
            if channel == "tt":
                cuts["tau_iso"] = (
                    f"(id_tau_vsJet_{vs_jet_wp}_1 > 0.5) && "
                    f"(id_tau_vsJet_{vs_jet_wp}_2 > 0.5)"
                )
            else:
                cuts["tau_iso"] = f"(id_tau_vsJet_{vs_jet_wp}_2 > 0.5)"
                cuts["mt_cut"] = "(mt_1 < 70)"
                cuts["muon_iso" if channel == "mt" else "ele_iso"] = "(iso_1 < 0.15)"
            return Selection(name=channel, cuts=cuts)

        if "em" in channel:
            cuts["ele_iso"] = "(iso_1 < 0.15)"
            cuts["muon_iso"] = "(iso_2 < 0.15)"
            cuts["electron_eta"] = "(abs(eta_1) < 2.5)"
            cuts["trg_selection"] = """(
                (pt_2 > 26) &&
                (
                    (pt_1 > 25) &&
                    (
                        (trg_single_mu24 > 0.5)
                    )
                )
            )"""
            return Selection(name="em", cuts=cuts)

        raise ValueError(f"Channel '{channel}' is not supported (Run3: et, mt, tt, em).")
    raise NotImplementedError(f"special={special!r} not implemented for Run3 channel_selection.")
