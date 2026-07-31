import inspect
import logging
from itertools import product
from typing import Any, Callable

from config.logging_setup_configs import setup_logging
from shapes.selection.process_selection import _get_stxs_bin_or_range
from ntuple_processor.utils import Cut, Weight
from ntuple_processor.variations import (
    AddWeight,
    RemoveWeight,
    ReplaceCut,
    ReplaceCutAndAddWeight,
    ReplaceMultipleCuts,
    ReplaceVariable,
    ReplaceVariableReplaceCutAndAddWeight,
    ReplaceWeight,
    SquareWeight,
)

logger = setup_logging(logger=logging.getLogger(__name__))

SHIFT_DIRECTIONS = ("Up", "Down")

FF_OPTIONS = {
    "none": {"lt": None, "tt_1": None, "tt_2": None},
    "fake_factor": {
        "lt": "fake_factor_2",
        "tt_1": "fake_factor_1",
        "tt_2": "fake_factor_2",
    },
    "fake_factor_with_bias_corr": {
        "lt": """(
                    (
                        raw_qcd_fake_factor_2 *
                        qcd_fake_factor_fraction_2 *
                        qcd_correction_wo_DR_SR_2
                    ) +
                    (
                        raw_wjets_fake_factor_2 *
                        wjets_fake_factor_fraction_2 *
                        wjets_correction_wo_DR_SR_2
                    ) +
                    (
                        raw_ttbar_fake_factor_2 *
                        ttbar_fake_factor_fraction_2 *
                        ttbar_correction_wo_DR_SR_2
                    )
                )"""
    },
    "fake_factor_with_DR_SR_corr": {
        "lt": """(
                    (
                        raw_qcd_fake_factor_2 *
                        qcd_fake_factor_fraction_2 *
                        qcd_DR_SR_correction_2
                    ) +
                    (
                        raw_wjets_fake_factor_2 *
                        wjets_fake_factor_fraction_2 *
                        wjets_DR_SR_correction_2
                    ) +
                    (
                        raw_ttbar_fake_factor_2 *
                        ttbar_fake_factor_fraction_2
                    )
                )""",
    },
    "fake_factor_with_DR_SR_and_bias_corr": {
        "lt": """(
                    (
                        raw_qcd_fake_factor_2 *
                        qcd_fake_factor_fraction_2 *
                        qcd_fake_factor_correction_2
                    ) +
                    (
                        raw_wjets_fake_factor_2 *
                        wjets_fake_factor_fraction_2 *
                        wjets_fake_factor_correction_2
                    ) +
                    (
                        raw_ttbar_fake_factor_2 *
                        ttbar_fake_factor_fraction_2 *
                        ttbar_fake_factor_correction_2
                    )
                )""",
    },
    # --------------------------------------------------------------------------------------
    "raw_fake_factor": {
        "lt": "raw_fake_factor_2",
        "tt_1": "raw_fake_factor_1",
        "tt_2": "raw_fake_factor_2",
    },
    # --------------------------------------------------------------------------------------
    "raw_qcd_fake_factor_with_fraction": {
        "lt": "(raw_qcd_fake_factor_2 * qcd_fake_factor_fraction_2)",
    },
    "raw_qcd_fake_factor": {
        "lt": "raw_qcd_fake_factor_2",
    },
    "raw_qcd_fake_factor_with_bias_corr": {
        "lt": "(raw_qcd_fake_factor_2 * qcd_correction_wo_DR_SR_2)",
    },
    "raw_qcd_fake_factor_with_DR_SR_corr": {
        "lt": "(raw_qcd_fake_factor_2 * qcd_DR_SR_correction_2)",
    },
    "raw_qcd_fake_factor_with_DR_SR_and_bias_corr": {
        "lt": "(raw_qcd_fake_factor_2 * qcd_correction_wo_DR_SR_2 * qcd_DR_SR_correction_2)",
    },
    # --------------------------------------------------------------------------------------
    "raw_wjets_fake_factor_with_fraction": {
        "lt": "(raw_wjets_fake_factor_2 * wjets_fake_factor_fraction_2)",
    },
    "raw_wjets_fake_factor": {
        "lt": "raw_wjets_fake_factor_2",
    },
    "raw_wjets_fake_factor_with_bias_corr": {
        "lt": "(raw_wjets_fake_factor_2 * wjets_correction_wo_DR_SR_2)",
    },
    "raw_wjets_fake_factor_with_DR_SR_corr": {
        "lt": "(raw_wjets_fake_factor_2 * wjets_DR_SR_correction_2)",
    },
    "raw_wjets_fake_factor_with_DR_SR_and_bias_corr": {
        "lt": "(raw_wjets_fake_factor_2 * wjets_correction_wo_DR_SR_2 * wjets_DR_SR_correction_2)",
    },
    # --------------------------------------------------------------------------------------
    "raw_ttbar_fake_factor_with_fraction": {
        "lt": "(raw_ttbar_fake_factor_2 * ttbar_fake_factor_fraction_2)",
    },
    "raw_ttbar_fake_factor": {
        "lt": "raw_ttbar_fake_factor_2",
    },
    "raw_ttbar_fake_factor_with_bias_corr": {
        "lt": "(raw_ttbar_fake_factor_2 * ttbar_correction_wo_DR_SR_2)",
    },
    "raw_ttbar_fake_factor_with_DR_SR_corr": {
        "lt": "(raw_ttbar_fake_factor_2 * 1.0)",
    },
    "raw_ttbar_fake_factor_with_DR_SR_and_bias_corr": {
        "lt": "(raw_ttbar_fake_factor_2 * ttbar_correction_wo_DR_SR_2 * 1.0)",
    },
    # --------------------------------------------------------------------------------------
}

__FF_OPTION_info__ = """
    Different implementation of accessing full (FF_OPTIONS["fake_factor"]) and raw fake factors
    (FF_OPTIONS["raw_fake_factor"]) and their individual combinations with different corrections
    this can be set to a default value in RuntimeVariables or via set_ff_type function.

    In case of usage: This is mainly intendet to investigate individual contributions of the fake factors
    and their corrections to the SR in the DR region. Make sure that the corresponding components
    that are specified are also present in the produced ntuples!

    possible options based on https://github.com/KIT-CMS/TauAnalysis-CROWN/commit/d73463bfdf5a7023b6b032a0c2d05b00f88e4150
      - "fake_factor_2"
      - "qcd_DR_SR_correction_2"
      - "qcd_correction_wo_DR_SR_2"
      - "qcd_fake_factor_2"
      - "qcd_fake_factor_correction_2"
      - "qcd_fake_factor_fraction_2"
      - "raw_fake_factor_2"
      - "raw_qcd_fake_factor_2"
      - "raw_ttbar_fake_factor_2"
      - "raw_wjets_fake_factor_2"
      - "ttbar_DR_SR_correction_2"
      - "ttbar_correction_wo_DR_SR_2"
      - "ttbar_fake_factor_2"
      - "ttbar_fake_factor_correction_2"
      - "ttbar_fake_factor_fraction_2"
      - "wjets_DR_SR_correction_2"
      - "wjets_correction_wo_DR_SR_2"
      - "wjets_fake_factor_2"
      - "wjets_fake_factor_correction_2"
      - "wjets_fake_factor_fraction_2"
"""


def set_jet_wp(jet_wp):
    logger.info(f"Setting jet wp option to {jet_wp}")
    RuntimeVariables.vs_jet_wp = jet_wp

def set_ff_type(ff_type):
    if ff_type not in FF_OPTIONS:
        logger.error(f"Fake factor option {ff_type} not found in FF_OPTIONS.")
        raise KeyError(f"Fake factor option {ff_type} not found in FF_OPTIONS.")

    logger.info(f"Setting fake factor option to {ff_type}= {FF_OPTIONS[ff_type]}")
    RuntimeVariables.FF_name_lt = FF_OPTIONS[ff_type]["lt"]
    # Only "none"/"fake_factor"/"raw_fake_factor" define "tt_1"/"tt_2" in
    # FF_OPTIONS -- the other options are lt-only diagnostic variants for
    # investigating individual fake-factor components/corrections (raw/bias-
    # corrected/DR-SR-corrected pieces) and were never given a tt-channel
    # equivalent. Previously this did `FF_OPTIONS[ff_type]["tt_1"]`
    # unconditionally, which raised a bare KeyError for those options instead
    # of leaving tt_1/tt_2 alone as the (until now inaccurate) warning below
    # claimed -- checked here instead, so the fallback the message describes
    # actually happens.
    if "tt_1" in FF_OPTIONS[ff_type] and "tt_2" in FF_OPTIONS[ff_type]:
        RuntimeVariables.FF_name_tt_1 = FF_OPTIONS[ff_type]["tt_1"]
        RuntimeVariables.FF_name_tt_2 = FF_OPTIONS[ff_type]["tt_2"]
    else:
        logger.warning(
            f"Fake factor option {ff_type!r} only defines an 'lt' fake factor "
            "(no 'tt_1'/'tt_2' entry in FF_OPTIONS) -- it is one of the lt-only "
            "diagnostic variants for investigating individual fake-factor "
            "components/corrections. Leaving the tt channel's fake factor "
            f"unchanged (tt_1={RuntimeVariables.FF_name_tt_1!r}, "
            f"tt_2={RuntimeVariables.FF_name_tt_2!r}); set ff_type to 'none', "
            "'fake_factor', or 'raw_fake_factor' if the tt channel's fake "
            "factor needs to change too."
        )


class RuntimeVariables(object):
    """
    A singleton-like container class holding several variables that can be adjusted in time.

    Attributes:
        FF_name_lt (str): Fake factor name for the "lt" channel.
        FF_name_tt_1 (str): Fake factor name for the first "tt" channel.
        FF_name_tt_2 (str): Fake factor name for the second "tt" channel.

    Usage:
        >>> used = Used()
        >>> print(used.FF_name_lt)

    Note:
        This class implements a singleton-like pattern by returning the same instance
        on every instantiation.
    """
    FF_name_lt = FF_OPTIONS["fake_factor"]["lt"]
    FF_name_tt_1 = FF_OPTIONS["fake_factor"]["tt_1"]
    FF_name_tt_2 = FF_OPTIONS["fake_factor"]["tt_2"]
    vs_jet_wp = ""

    def __new__(cls) -> "RuntimeVariables":
        if not hasattr(cls, "instance"):
            cls.instance = super(RuntimeVariables, cls).__new__(cls)
            return cls.instance


class LazyVariable:
    """
    A lazy evaluation wrapper for variables whose underlying value may change over time.

    This class accepts a factory callable that produces the actual instance to use.
    Any attribute access or string representation is delegated to the instance returned
    by the factory at call time, ensuring that modifications to the underlying variable
    are reflected immediately.

    Usage:
        >>> def my_factory() -> SomeClass:
        ...     return SomeClass()
        >>> lazy_var = LazyVariable(my_factory)
        >>> # Any attribute access on lazy_var is delegated to the instance returned by my_factory.
        >>> value = lazy_var.some_attribute
    """

    def __init__(self, factory: Callable[[], Any]) -> None:
        """
        Initializes a LazyVariable with a factory callable.

        Args:
            factory (Callable[[], Any]): A callable that returns the actual variable instance.
        """
        self.factory: Callable[[], Any] = factory
        try:
            caller = inspect.stack()[1]
            logger.debug(f"LazyVariable created at {caller.filename}:{caller.lineno} with {inspect.getsource(factory)}")
        except NameError:  # logger or inspect not defined
            pass

    def __getattr__(self, name: str) -> Any:
        """
        Delegates attribute access to the instance returned by the factory.

        Args:
            name (str): The name of the attribute to access.

        Returns:
            Any: The attribute value from the instantiated object.
        """
        instance = self.factory()
        try:
            caller = inspect.stack()[1]
            logger.debug(f"LazyVariable __getattr__: '{name}' called from {caller.filename}:{caller.lineno}, returning {instance}")
        except NameError:  # logger or inspect not defined
            pass
        return getattr(instance, name)

    def __repr__(self) -> str:
        """
        Returns the official string representation of the LazyVariable.

        Returns:
            str: The string representation of the object returned by the factory.
        """
        result = repr(self.factory())
        try:
            caller = inspect.stack()[1]
            logger.debug(f"LazyVariable __repr__: called from {caller.filename}:{caller.lineno}, returning {result}")
        except NameError:  # logger or inspect not defined
            pass
        return result

    def __str__(self) -> str:
        """
        Returns the informal string representation of the LazyVariable.

        Returns:
            str: The string representation of the object returned by the factory.
        """
        result = str(self.factory())
        try:
            caller = inspect.stack()[1]
            logger.debug(f"LazyVariable __str__: called from {caller.filename}:{caller.lineno}, returning {result}")
        except NameError:  # logger or inspect not defined
            pass
        return result


#  Variations needed for the various jet background estimations.
# TODO: In order to properly use this variation friend trees with the correct weights need to be created.
same_sign = ReplaceCut("same_sign", "os", Cut("q_1*q_2>0", "ss"))
same_sign_em = ReplaceCut(
    "same_sign",
    "os",
    Cut("q_1*q_2>0", "ss"),
    #Weight("em_qcd_osss_binned_Weight", "qcd_weight"),
)
abcd_method = [
    ReplaceCut("abcd_same_sign", "os", Cut("q_1*q_2>0", "ss")),
    ReplaceCut(
        "abcd_anti_iso",
        "tau_iso",
        Cut(
            f"(id_tau_vsJet_Medium_1>0.5 && id_tau_vsJet_Medium_2<0.5 && id_tau_vsJet_VVVLoose_2>0.5)",
            "tau_anti_iso",
        ),
    ),
    ReplaceMultipleCuts(
        "abcd_same_sign_anti_iso",
        ["os", "tau_iso"],
        [
            Cut("q_1*q_2>0", "ss"),
            Cut(
                f"(id_tau_vsJet_Medium_1>0.5 && id_tau_vsJet_Medium_2<0.5 && id_tau_vsJet_VVVLoose_2>0.5)",
                "tau_anti_iso",
            ),
        ],
    ),
]
same_sign_anti_iso_lt = ReplaceMultipleCuts(
    "same_sign_anti_iso",
    ["os", "tau_iso"],
    [
        Cut("q_1*q_2>0", "ss"),
        Cut(f"(id_tau_vsJet_Medium_2<0.5 && id_tau_vsJet_VVVLoose_2>0.5)", "tau_anti_iso"),
    ]
)
anti_iso_lt = LazyVariable(  # requieres LazyVariation since Used.FF_name_lt may be defined later
    lambda: ReplaceCutAndAddWeight(
        "anti_iso",
        "tau_iso",
        Cut(f"(id_tau_vsJet_Medium_2<0.5 && id_tau_vsJet_VVVLoose_2>0.5)", "tau_anti_iso"),
        Weight(RuntimeVariables.FF_name_lt, "fake_factor"),
    )
)
anti_iso_tt = LazyVariable(  # requieres LazyVariation since Used.FF_name_lt may be defined later
    lambda: ReplaceCutAndAddWeight(
        "anti_iso",
        "tau_iso",
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
    )
)

# Pileup reweighting. CROWN registers f"CMS_pileup_{shift_era_tag}" -- era-tagged,
# same convention as recoil/met_unclustered above.
def pileup_reweighting(era):
    era_tag = JES_ERA_MAP[era]
    return [
        ReplaceVariable(f"CMS_pileup_{era_tag}Up", f"CMS_pileup_{era_tag}Up"),
        ReplaceVariable(f"CMS_pileup_{era_tag}Down", f"CMS_pileup_{era_tag}Down"),
    ]

# Energy scales.
#
# CROWN's genuine-tau MC energy scale ("Tau energy scale shifts" block, MC
# non-dyjets/ewk path) is DM-indexed and its era regime changes the branch
# suffix structure entirely (the registered shift name IS the suffix, same
# convention as jet_energy_scale/recoil/etc above):
#   era < 2022:        CMS_scale_t_DM{dm}_genTau_pT{pt}{Up,Down}, pt in [20to40, 40toInf]
#   2022 <= era < 2024: CMS_scale_t_DM{dm}_genTau_{era_tag}{Up,Down}            (no pt split)
#   era >= 2024:        CMS_scale_t_DM{dm}_genTau_pT{pt}_{era_tag}{Up,Down}, pt in [20to40, 40to60, 60toInf]
# dm: 0=1prong0pizero, 1=1prong1pizero, 10=3prong0pizero, 11=3prong1pizero.
def _tau_es_group(dm, era):
    era_num = int(era[:4])
    if era_num < 2022:
        return [
            ReplaceVariable(f"CMS_scale_t_DM{dm}_genTau_pT{pt}{shift}", f"CMS_scale_t_DM{dm}_genTau_pT{pt}{shift}")
            for pt in ["20to40", "40toInf"]
            for shift in SHIFT_DIRECTIONS
        ]
    era_tag = JES_ERA_MAP[era]
    if era_num < 2024:
        return [
            ReplaceVariable(f"CMS_scale_t_DM{dm}_genTau_{era_tag}{shift}", f"CMS_scale_t_DM{dm}_genTau_{era_tag}{shift}")
            for shift in SHIFT_DIRECTIONS
        ]
    return [
        ReplaceVariable(f"CMS_scale_t_DM{dm}_genTau_pT{pt}_{era_tag}{shift}", f"CMS_scale_t_DM{dm}_genTau_pT{pt}_{era_tag}{shift}")
        for pt in ["20to40", "40to60", "60toInf"]
        for shift in SHIFT_DIRECTIONS
    ]


def tau_es_1prong(era):
    return _tau_es_group("0", era)


def tau_es_1prong1pizero(era):
    return _tau_es_group("1", era)


def tau_es_3prong(era):
    return _tau_es_group("10", era)


def tau_es_3prong1pizero(era):
    return _tau_es_group("11", era)


def tau_energy_scale(era):
    return tau_es_1prong(era) + tau_es_1prong1pizero(era) + tau_es_3prong(era) + tau_es_3prong1pizero(era)


# Embedding tau ES: CROWN registers f"tauEs{dm}{var}" (name IS the branch
# suffix, no era tag -- the add_shift loop in tau_embedding_settings.py's
# vsJet ID/ES block, ~line 1405-1408, isn't era-gated) for et/mt only, where
# dm is the decay-mode string used below and `var` comes from the active
# ES_ID_SCHEME.pt_binning (scripts/SpecialSetups.py). NOTE: the actual scheme
# selection (`configuration.ES_ID_SCHEME = ES_ID_SCHEME(scheme=...)`) is not
# set anywhere in analysis_configurations/tau in this checkout, so this uses
# the dataclass's documented default ("dm_pt_binned" -> pt_binning =
# ["20to40", "40toInf"]) -- NOT independently verified against the actual
# active scheme. This is currently dead code (not booked in produce_shapes.py);
# if/when it gets booked, confirm the active scheme first.
def _emb_tau_es_group(dm):
    return [
        ReplaceVariable(f"CMS_scale_t_emb_{dm}_{pt}{shift}", f"tauEs{dm}{pt}{shift}")
        for pt in ["20to40", "40toInf"]
        for shift in SHIFT_DIRECTIONS
    ]


emb_tau_es_3prong = _emb_tau_es_group("3prong0pizero")
emb_tau_es_3prong1pizero = _emb_tau_es_group("3prong1pizero")
emb_tau_es_1prong = _emb_tau_es_group("1prong0pizero")
emb_tau_es_1prong1pizero = _emb_tau_es_group("1prong1pizero")

# Jet Energy Scale / Resolution + fixed-WP b-tag SF variations.
#
# Branch names are read as-is from the CROWN ntuples (not renamed) -- see
# jet_variations.py's add_jetVariations(). For Run3 (the only eras this
# analysis produces signals for -- see config/analysis.py:RUN3_ERAS),
# JES_CONFIG.REGROUPED is unconditionally True, so CROWN only ever emits the
# 6 regrouped JES sources (+ their per-era-decorrelated siblings for
# Absolute/BBEC1/HF/EC2/RelativeSample) and the fixed-WP b-tag scheme -- the
# old per-individual-source list (SinglePionECAL, AbsoluteMPFBias, ...) and
# full-shape b-tag names (CMS_btag_b_HF, CMS_btag_j_LF, ...) below never
# matched any branch CROWN actually produces here; that was the Run2
# non-regrouped scheme. The registered shift name IS the branch suffix (see
# CROWNWrapper.get_adjusted_add_shift_SystematicShift), so name and variation
# are identical here -- no separate branch-name derivation needed.
JES_ERA_MAP = {
    "2018": "2018",
    "2022preEE": "2022",
    "2022postEE": "2022EE",
    "2023preBPix": "2023",
    "2023postBPix": "2023BPix",
    "2024": "2024",
    "2025": "2025",
    "2026": "2026",
}
# btag_fixedWP(era) below is Run3-only: jet_variations.py gates on
# `int(era[:4]) < 2022` and uses a different (full-shape btagging_SF, not
# fixed-WP btaggingWP_SF) scheme for 2018 -- not implemented here since
# 2018 shape production only covers backgrounds (see
# config/analysis.py:RUN2_PRODUCTION_ERAS docstring), no signal categories.
BTAG_FIXEDWP_ERAS = frozenset(JES_ERA_MAP) - {"2018"}

_JES_FULLY_CORRELATED_SOURCES = ["Total", "Absolute", "FlavorQCD", "BBEC1", "HF", "EC2", "RelativeBal"]
_JES_PER_ERA_SOURCES = ["Absolute", "BBEC1", "HF", "EC2", "RelativeSample"]


def jet_energy_scale(era):
    era_tag = JES_ERA_MAP[era]
    names = (
        [f"CMS_scale_j_{source}" for source in _JES_FULLY_CORRELATED_SOURCES]
        + [f"CMS_scale_j_{source}_{era_tag}" for source in _JES_PER_ERA_SOURCES]
    )
    return [
        ReplaceVariable(f"{name}{shift}", f"{name}{shift}")
        for shift in SHIFT_DIRECTIONS
        for name in names
    ]


def jet_energy_resolution(era):
    era_tag = JES_ERA_MAP[era]
    return [
        ReplaceVariable(f"CMS_res_j_{era_tag}{shift}", f"CMS_res_j_{era_tag}{shift}")
        for shift in SHIFT_DIRECTIONS
    ]


def btag_fixedWP(era):
    era_tag = JES_ERA_MAP[era]
    names = [
        "CMS_btag_fixedWP_bc_correlated",
        f"CMS_btag_fixedWP_bc_uncorrelated_{era_tag}",
        "CMS_btag_fixedWP_light_correlated",
        f"CMS_btag_fixedWP_light_uncorrelated_{era_tag}",
    ]
    return [
        ReplaceVariable(f"{name}{shift}", f"{name}{shift}")
        for shift in SHIFT_DIRECTIONS
        for name in names
    ]


# CMS_scale_j_HEMIssue_2018 (2018-only HEM15/16 issue shift, jet_variations.py
# line ~85) is not implemented here: 2018 shape production is background-only
# (see config/analysis.py:RUN2_PRODUCTION_ERAS docstring), so there is no
# process to book it onto yet.

# LHE/PS variations.
#
# Branch names below are read as-is from the CROWN ntuples (not renamed) --
# see analysis_configurations/tau/config.py's "LHE Scale Weight variations"
# block. CROWN produces a postfixed set per STXS stage-0 Higgs production
# mode (_ggH/_qqH/_VH/_ttH), since the underlying LHE_Scale_weight/PS_weight/
# LHE_PDF_weight/LHE_alphaS_weight branches are shared but the theory
# variations are treated as uncorrelated nuisances per production mode.
# _ggH and _qqH datasets are unambiguous (ggh_htautau/vbf_htautau sample
# types); the WminusH/WplusH/ZH/TTH datasets all share the "rem_htautau"
# sample type in CROWN, so CROWN emits both _VH and _ttH branches for them --
# only the postfix matching the process being booked below is ever read.
def _lhe_scale_norm_muR(postfix):
    return [
        AddWeight(f"LHE_scale_muR_norm_{postfix}Up", Weight(f"(lhe_scale_weight__QCDscale_ren_{postfix}Up)", "muR2p0_muF1p0_weight")),
        AddWeight(f"LHE_scale_muR_norm_{postfix}Down", Weight(f"(lhe_scale_weight__QCDscale_ren_{postfix}Down)", "muR0p5_muF1p0_weight")),
    ]


def _lhe_scale_norm_muF(postfix):
    return [
        AddWeight(f"LHE_scale_muF_norm_{postfix}Up", Weight(f"(lhe_scale_weight__QCDscale_fac_{postfix}Up)", "muR1p0_muF2p0_weight")),
        AddWeight(f"LHE_scale_muF_norm_{postfix}Down", Weight(f"(lhe_scale_weight__QCDscale_fac_{postfix}Down)", "muR1p0_muF0p5_weight")),
    ]


def _ps_scale_norm_fsr(postfix):
    return [
        AddWeight(f"PS_scale_Fsr_norm_{postfix}Up", Weight(f"(ps_weight__ps_fsr_{postfix}Up)", "FsR2p0_weight")),
        AddWeight(f"PS_scale_Fsr_norm_{postfix}Down", Weight(f"(ps_weight__ps_fsr_{postfix}Down)", "FsR0p5_weight")),
    ]


def _ps_scale_norm_isr(postfix):
    return [
        AddWeight(f"PS_scale_Isr_norm_{postfix}Up", Weight(f"(ps_weight__ps_isr_{postfix}Up)", "IsR2p0_weight")),
        AddWeight(f"PS_scale_Isr_norm_{postfix}Down", Weight(f"(ps_weight__ps_isr_{postfix}Down)", "IsR0p5_weight")),
    ]


def _lhe_pdf(postfix):
    return [
        AddWeight(f"LHE_pdf_{postfix}Up", Weight(f"(lhe_pdf_weight__pdf_Higgs_{postfix}Up)", "lhe_pdf_up_weight")),
        AddWeight(f"LHE_pdf_{postfix}Down", Weight(f"(lhe_pdf_weight__pdf_Higgs_{postfix}Down)", "lhe_pdf_down_weight")),
    ]


def _lhe_alphaS(postfix):
    return [
        AddWeight(f"LHE_alphaS_{postfix}Up", Weight(f"(lhe_alphaS_weight__pdf_alphas_{postfix}Up)", "lhe_alphaS_up_weight")),
        AddWeight(f"LHE_alphaS_{postfix}Down", Weight(f"(lhe_alphaS_weight__pdf_alphas_{postfix}Down)", "lhe_alphaS_down_weight")),
    ]

# MET variations.
#
# CROWN registers these as two standalone SystematicShiftByQuantity shifts
# named f"CMS_scale_met_unclustered_energyUp_{shift_era_tag}" / "...Down..."
# (see analysis_configurations/tau/variations.py's "MET Shifts" block) -- the
# registered shift name IS the branch suffix, era-tagged like recoil above.
def met_unclustered(era):
    era_tag = JES_ERA_MAP[era]
    return [
        ReplaceVariable(f"CMS_scale_met_unclustered_energyUp_{era_tag}", f"CMS_scale_met_unclustered_energyUp_{era_tag}"),
        ReplaceVariable(f"CMS_scale_met_unclustered_energyDown_{era_tag}", f"CMS_scale_met_unclustered_energyDown_{era_tag}"),
    ]

# Recoil correction uncertainties.
#
# For era >= 2022, CROWN's ApplyRecoilUncertainty shift is registered as
# f"CMS_scale_met_recoil_response_{shift_era_tag}" /
# f"CMS_res_met_recoil_resolution_{shift_era_tag}" (see analysis_configurations/
# tau/variations.py's "MET Recoil Shifts" block) -- the registered shift name
# IS the branch suffix, same convention as jet_energy_scale/jet_energy_resolution
# above, so name and variation must match and be era-tagged. The old hardcoded
# "metRecoilResolutionUp"/"metRecoilResponseUp" branch names don't exist in the
# ntuple for these eras and raise NameError in ntuple_processor.variations.
def recoil_resolution(era):
    era_tag = JES_ERA_MAP[era]
    return [
        ReplaceVariable(f"CMS_res_met_recoil_resolution_{era_tag}{shift}", f"CMS_res_met_recoil_resolution_{era_tag}{shift}")
        for shift in SHIFT_DIRECTIONS
    ]


def recoil_response(era):
    era_tag = JES_ERA_MAP[era]
    return [
        ReplaceVariable(f"CMS_scale_met_recoil_response_{era_tag}{shift}", f"CMS_scale_met_recoil_response_{era_tag}{shift}")
        for shift in SHIFT_DIRECTIONS
    ]

# B-tagging scale-factor uncertainties: see btag_fixedWP(era) above. The
# "btagging" full-shape-scheme list formerly here matched CROWN's Run2
# btagging_SF names (e.g. CMS_btag_fullShape_hf), not this analysis's Run3
# fixed-WP scheme (btaggingWP_SF/CMS_btag_fixedWP_*), and was never booked;
# removed in favour of btag_fixedWP(era). A separate "btagging_2024" list
# (CMS_btag_fsr/hdamp/isr/jer/jes/mass/stat/tune -- ttbar-modeling sources
# for a b-tag *efficiency* measurement, unrelated to jet_variations.py's SF
# shifts) was also removed: it didn't correspond to any shift in
# jet_variations.py and was never booked either.

# Eta binned uncertainty
ele_fake_es_1prong = [
    ReplaceVariable(name, variation)
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"CMS_ZLShape_et_1prong_barrel_Era{shift}", f"tauEleFakeEs1prongBarrel{shift}"),
        (f"CMS_ZLShape_et_1prong_endcap_Era{shift}", f"tauEleFakeEs1prongEndcap{shift}"),
    ]
]
ele_fake_es_1prong1pizero = [
    ReplaceVariable(name, variation)
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"CMS_ZLShape_et_1prong1pizero_barrel_Era{shift}", f"tauEleFakeEs1prong1pizeroBarrel{shift}"),
        (f"CMS_ZLShape_et_1prong1pizero_endcap_Era{shift}", f"tauEleFakeEs1prong1pizeroEndcap{shift}"),
    ]
]
ele_fake_es = ele_fake_es_1prong + ele_fake_es_1prong1pizero

# Electron ES Resolution. CROWN registers name="CMS_res_e"/"CMS_scale_e"
# (no era tag, both eras) -- the branch suffix is the shift name, not the old
# "eleEsReso"/"eleEsScale" strings.
ele_es_res = [ReplaceVariable(f"CMS_res_e{shift}", f"CMS_res_e{shift}") for shift in SHIFT_DIRECTIONS]
ele_es_scale = [ReplaceVariable(f"CMS_scale_e{shift}", f"CMS_scale_e{shift}") for shift in SHIFT_DIRECTIONS]

# Mu Fake uncertainties (mt only, booked on zl).
#
# CROWN (MC, "Tau energy scale shifts" block, dyjets/electroweak_boson-only
# branch, mt scope):
#   era < 2022: CMS_scale_t_genMuon{Up,Down}                          (no DM split)
#   era >= 2022: CMS_scale_t_DM{dm}_genMuon_{era_tag}{Up,Down}, dm in [0,1,10,11]
def mu_fake_es_inc(era):
    era_num = int(era[:4])
    if era_num < 2022:
        return [
            ReplaceVariable(f"CMS_scale_t_genMuon{shift}", f"CMS_scale_t_genMuon{shift}")
            for shift in SHIFT_DIRECTIONS
        ]
    era_tag = JES_ERA_MAP[era]
    return [
        ReplaceVariable(f"CMS_scale_t_DM{dm}_genMuon_{era_tag}{shift}", f"CMS_scale_t_DM{dm}_genMuon_{era_tag}{shift}")
        for dm in ["0", "1", "10", "11"]
        for shift in SHIFT_DIRECTIONS
    ]

# Efficiency corrections.
# Tau ID efficiency (MC vsJet SF, et/mt scope).
#
# CROWN ("TauID scale factor shifts" block, et/mt path):
#   era < 2022:        CMS_eff_t_DeepTau2017v2p1_VSjet_DM{dm}_pT{pt}{Up,Down}, dm in [0,1,10,11], pt in [20to40, 40toInf]
#   2022 <= era < 2024: CMS_eff_t_DeepTau2018v2p5_VSjet_DM{dm}_{era_tag}{Up,Down}, dm in [0,1,10,11]  (no pt split)
#   era >= 2024:        CMS_eff_t_DeepTau2018v2p5_VSjet_DM{dm}_pT{pt}_{era_tag}{Up,Down}, dm in [0,1,10,11], pt in [20to40, 40to60, 60toInf]
def tau_id_eff_lt(era):
    era_num = int(era[:4])
    dms = ["0", "1", "10", "11"]
    if era_num < 2022:
        return [
            ReplaceVariable(f"CMS_eff_t_DeepTau2017v2p1_VSjet_DM{dm}_pT{pt}{shift}", f"CMS_eff_t_DeepTau2017v2p1_VSjet_DM{dm}_pT{pt}{shift}")
            for dm in dms
            for pt in ["20to40", "40toInf"]
            for shift in SHIFT_DIRECTIONS
        ]
    era_tag = JES_ERA_MAP[era]
    if era_num < 2024:
        return [
            ReplaceVariable(f"CMS_eff_t_DeepTau2018v2p5_VSjet_DM{dm}_{era_tag}{shift}", f"CMS_eff_t_DeepTau2018v2p5_VSjet_DM{dm}_{era_tag}{shift}")
            for dm in dms
            for shift in SHIFT_DIRECTIONS
        ]
    return [
        ReplaceVariable(f"CMS_eff_t_DeepTau2018v2p5_VSjet_DM{dm}_pT{pt}_{era_tag}{shift}", f"CMS_eff_t_DeepTau2018v2p5_VSjet_DM{dm}_pT{pt}_{era_tag}{shift}")
        for dm in dms
        for pt in ["20to40", "40to60", "60toInf"]
        for shift in SHIFT_DIRECTIONS
    ]
# Embedding vsJet ID SF (et/mt). CROWN registers f"vsJetTau{dm}{var}" (name IS
# the branch suffix, no era tag -- tau_embedding_settings.py's vsJet ID SF
# add_shift loop, ~line 1401-1403), DM-indexed with the same pt_binning
# uncertainty noted on _emb_tau_es_group above (assumed dm_pt_binned default:
# pt_binning=["20to40","40toInf"]) -- NOT independently verified against the
# active scheme. Previously this was flat pt-only-binned ("vsJetTau30to35" etc,
# no DM component at all), which doesn't match CROWN's DM+pt structure.
_EMB_TAU_ID_EFF_LT_DMS = ["1prong0pizero", "1prong1pizero", "3prong0pizero", "3prong1pizero"]

emb_tau_id_eff_lt = [
    ReplaceVariable(f"CMS_eff_t_emb_{dm}_{pt}{shift}", f"vsJetTau{dm}{pt}{shift}")
    for dm in _EMB_TAU_ID_EFF_LT_DMS
    for pt in ["20to40", "40toInf"]
    for shift in SHIFT_DIRECTIONS
]

# tauid variations used for correlation with mc ones -- same branch, shared
# (non-"_emb") nuisance name so MC and embedding are fit as one parameter.
emb_tau_id_eff_lt_corr = [
    ReplaceVariable(f"CMS_eff_t_{dm}_{pt}{shift}", f"vsJetTau{dm}{pt}{shift}")
    for dm in _EMB_TAU_ID_EFF_LT_DMS
    for pt in ["20to40", "40toInf"]
    for shift in SHIFT_DIRECTIONS
]
tau_id_eff_tt = [
    ReplaceVariable(name, variation)
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"CMS_eff_t_dm0_Era{shift}", f"vsJetTauDM0{shift}"),
        (f"CMS_eff_t_dm1_Era{shift}", f"vsJetTauDM1{shift}"),
        (f"CMS_eff_t_dm10_Era{shift}", f"vsJetTauDM10{shift}"),
        (f"CMS_eff_t_dm11_Era{shift}", f"vsJetTauDM11{shift}"),
    ]
]
emb_tau_id_eff_tt = [
    ReplaceVariable(name, variation)
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"CMS_eff_t_emb_dm0_Era{shift}", f"vsJetTauDM0{shift}"),
        (f"CMS_eff_t_emb_dm1_Era{shift}", f"vsJetTauDM1{shift}"),
        (f"CMS_eff_t_emb_dm10_Era{shift}", f"vsJetTauDM10{shift}"),
        (f"CMS_eff_t_emb_dm11_Era{shift}", f"vsJetTauDM11{shift}"),
    ]
]

# Jet to tau fake rate.
jet_to_tau_fake = [
    AddWeight(
        "CMS_htt_fake_j_EraUp",
        Weight("max(1.0-pt_2*0.002, 0.6)", "jetToTauFake_weight"),
    ),
    AddWeight(
        "CMS_htt_fake_j_EraDown",
        Weight("min(1.0+pt_2*0.002, 1.4)", "jetToTauFake_weight"),
    ),
]

# vsEle ID
zll_et_fake_rate = [
    ReplaceVariable(name, variation)
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"CMS_fake_e_BA_Era{shift}", f"vsEleBarrel{shift}"),
        (f"CMS_fake_e_EC_Era{shift}", f"vsEleEndcap{shift}"),
    ]
]

# vsMu ID
zll_mt_fake_rate = [
    ReplaceVariable(f"CMS_fake_m_WH{region}_Era{shift}", f"vsMuWheel{region}{shift}")
    for shift in SHIFT_DIRECTIONS
    for region in ["1", "2", "3", "4", "5"]
]

# Trigger efficiency uncertainties.
#
# Branch names are read as-is from the CROWN ntuples (not renamed) -- see
# tau_triggersetup.py's "trigger shifts" blocks. Note CROWN's suffix casing
# here is upper-case UP/DOWN (from `_variation.upper()` on "up"/"down"), NOT
# the Up/Down convention used elsewhere in CROWN -- this is intentional on
# CROWN's side, not a typo to "fix" here.
#
# mt/et vary the single-lepton trigger SF only (mc_weights.yaml's
# single_trigger term -- there is no cross-trigger term in the nominal mt/et
# weight, so CMS_trig_mutau_cross/CMS_trig_etau_cross would have no effect
# and are intentionally not booked here); tt varies the combined ditau
# cross-trigger SF (both legs in one shift, matching double_trigger).
trigger_eff_mt = [
    ReplaceVariable("CMS_eff_m_triggerUP", "CMS_eff_m_triggerUP"),
    ReplaceVariable("CMS_eff_m_triggerDOWN", "CMS_eff_m_triggerDOWN"),
]

# et
trigger_eff_et = [
    ReplaceVariable("CMS_eff_e_triggerUP", "CMS_eff_e_triggerUP"),
    ReplaceVariable("CMS_eff_e_triggerDOWN", "CMS_eff_e_triggerDOWN"),
]

# tt
trigger_eff_tt = [
    ReplaceVariable("CMS_trig_t_ditau_crossUP", "CMS_trig_t_ditau_crossUP"),
    ReplaceVariable("CMS_trig_t_ditau_crossDOWN", "CMS_trig_t_ditau_crossDOWN"),
]
# The "_emb" variants formerly here (trigger_eff_mt_emb/et_emb/tt_emb) are
# removed: mt_emb/et_emb pointed at singleMuonTriggerSFUp/
# singleElectronTriggerSFUp, which tau_triggersetup.py explicitly computes
# with exclude_samples=["data","embedding","embedding_mc"] -- i.e. that
# branch does not exist for embedded samples at all, so booking it onto embS
# would crash ("Variation not found"), and tt_emb had no matching CROWN
# branch whatsoever. None of the three were ever booked.

# Embedding specific variations.
emb_e_es = [  # TODO Embedding electron scale, check if right
    ReplaceVariable(name, variation)
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"CMS_scale_e_barrel_emb{shift}", f"eleEsBarrel{shift}"),
        (f"CMS_scale_e_endcap_emb{shift}", f"eleEsEndcap{shift}"),
    ]
]

# TODO add embeddedDecayModeWeight?

# Prefiring
prefiring = [
    ReplaceWeight(
        f"CMS_prefiring{shift}",
        "prefireWeight",
        Weight(f"prefiring_wgt__prefiring{shift}", "prefireWeight"),
    )
    for shift in SHIFT_DIRECTIONS
]

# Z pT reweighting.
#
# CROWN only registers a zpt shift for era >= 2022 ("Z pt DY uncertainties"
# block: event.ZPtReweighting, single shift f"CMS_htt_zptReweight_{era_tag}",
# plain Up/Down -- no 9-parameter split). For era < 2022, CROWN uses
# event.ZPtReweighting_Run2 (producers/event.py's ZPtReweighting_Run2),
# which outputs a single nominal ZPtMassReweightWeight branch with no
# systematic-shift variants at all -- the old 9-component
# "CMS_htt_dyShape_*_1..9" -> "zPtReweightWeight*1..9" scheme this used to be
# doesn't correspond to anything CROWN currently produces for either era
# regime. Booking zpt() for era < 2022 must be gated out in produce_shapes.py.
def zpt(era):
    era_num = int(era[:4])
    if era_num < 2022:
        raise ValueError(
            f"CROWN defines no zpt systematic shift for era {era!r} (Run2 -- "
            "ZPtReweighting_Run2 has no shift variants); gate this booking by era."
        )
    era_tag = JES_ERA_MAP[era]
    return [
        ReplaceVariable(f"CMS_htt_zptReweight_{era_tag}Up", f"CMS_htt_zptReweight_{era_tag}Up"),
        ReplaceVariable(f"CMS_htt_zptReweight_{era_tag}Down", f"CMS_htt_zptReweight_{era_tag}Down"),
    ]

# Top pT reweighting
top_pt = [
    SquareWeight("CMS_htt_ttbarShapeUp", "topPtReweightWeight"),
    RemoveWeight("CMS_htt_ttbarShapeDown", "topPtReweightWeight"),
]

# FF variations
# Variations on the jet backgrounds estimated with the fake factor method.
ff_variations_lt = [
    ReplaceCutAndAddWeight(
        f"anti_iso_CMS_{syst}{shift}_Channel_Era",
        "tau_iso",
        Cut(f"id_tau_vsJet_Medium_2 < 0.5", "tau_anti_iso"),
        Weight(f"{RuntimeVariables.FF_name_lt}__{syst}{shift}", "fake_factor"),
    )
    for shift in SHIFT_DIRECTIONS
    for syst in [
        'QCDFFunc',
        'QCDFFmcSubUnc',
        'WjetsFFunc',
        'WjetsFFmcSubUnc',
        'ttbarFFunc',
        'process_fractionsfracQCDUnc',
        'process_fractionsfracWjetsUnc',
        'process_fractionsfracTTbarUnc'
        'QCD_non_closure_mass_2_Corr',
        'QCD_non_closure_deltaR_ditaupair_Corr',
        'QCD_non_closure_iso_1_Corr',
        'QCD_non_closure_tau_decaymode_2_Corr',
        'QCD_DR_SR_Corr',  # TODO: Add them when actually applying this correction!
        'Wjets_non_closure_mass_2_Corr',
        'Wjets_non_closure_deltaR_ditaupair_Corr',
        'Wjets_non_closure_iso_1_Corr',
        'Wjets_non_closure_tau_decaymode_2_Corr',
        'Wjets_DR_SR_Corr',  # TODO: Add them when actually applying this correction!
        'ttbar_non_closure_mass_2_Corr',
        'ttbar_non_closure_deltaR_ditaupair_Corr',
        'ttbar_non_closure_iso_1_Corr',
        'ttbar_non_closure_tau_decaymode_2_Corr'
    ]
]

# TODO: Check if variations are applied

# Propagation of tau ES systematics on jetFakes process
# lt channel
ff_variations_tau_es_lt = [
    LazyVariable(  # requieres LazyVariation since Used.FF_name_lt may be defined later
        lambda: ReplaceVariableReplaceCutAndAddWeight(
            name,
            variation,
            "tau_iso",
            Cut(f"id_tau_vsJet_Medium_2__{variation} < 0.5 && id_tau_vsJet_VLoose_2__{variation} > 0.5", "tau_anti_iso"),
            Weight(f"{RuntimeVariables.FF_name_lt}__{variation}", "fake_factor"),
        )
    )
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"anti_iso_CMS_scale_t_1prong_Era{shift}", f"tauEs1prong0pizero{shift}"),
        (f"anti_iso_CMS_scale_t_1prong1pizero_Era{shift}", f"tauEs1prong1pizero{shift}"),
        (f"anti_iso_CMS_scale_t_3prong_Era{shift}", f"tauEs3prong0pizero{shift}"),
        (f"anti_iso_CMS_scale_t_3prong1pizero_Era{shift}", f"tauEs3prong1pizero{shift}"),
    ]
]

# lt for emb only for correlation
ff_variations_tau_es_emb_lt = [
    LazyVariable(  # requieres LazyVariation since Used.FF_name_lt may be defined later
        lambda: ReplaceVariableReplaceCutAndAddWeight(
            name,
            variation,
            "tau_iso",
            Cut(f"id_tau_vsJet_Medium_2__{variation} < 0.5 && id_tau_vsJet_VLoose_2__{variation} > 0.5", "tau_anti_iso"),
            Weight(f"{RuntimeVariables.FF_name_lt}__{variation}", "fake_factor"),
        )
    )
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"anti_iso_CMS_scale_t_emb_1prong_Era{shift}", f"tauEs1prong0pizero{shift}"),
        (f"anti_iso_CMS_scale_t_emb_1prong1pizero_Era{shift}", f"tauEs1prong1pizero{shift}"),
        (f"anti_iso_CMS_scale_t_emb_3prong_Era{shift}", f"tauEs3prong0pizero{shift}"),
        (f"anti_iso_CMS_scale_t_emb_3prong1pizero_Era{shift}", f"tauEs3prong1pizero{shift}"),
    ]
]

# # tt channel
# Variations on the jet backgrounds estimated with the fake factor method.
ff_variations_tt = [
    ReplaceCutAndAddWeight(
        f"anti_iso_CMS_{syst}{shift}_Channel_Era",
        "tau_iso",
        Cut(f"id_tau_vsJet_Medium_2 < 0.5", "tau_anti_iso"),
        Weight(f"{RuntimeVariables.FF_name_lt}__{syst}{shift}", "fake_factor"),
    )
    for shift in SHIFT_DIRECTIONS
    for syst in [
        'QCDFFunc',
        'QCDFFmcSubUnc',
        'process_fractionsfracQCDUnc',
        'QCD_non_closure_pt_2_Corr',
        'QCD_DR_SR_Corr', 
        'QCD_subleadingFFunc',
        'QCD_subleadingFFmcSubUnc',
        'process_fractions_subleadingfracQCDUnc',
        'QCD_subleading_non_closure_pt_1_Corr',
        'QCD_subleading_DR_SR_Corr',  
    ]
]

ff_variations_tau_es_tt = [
    LazyVariable(  # requieres LazyVariation since Used.FF_name_tt may be defined later
        lambda: ReplaceVariableReplaceCutAndAddWeight(
            name,
            variation,
            "tau_iso",
            Cut(
                f"""(
                        (
                            (id_tau_vsJet_Medium_1__{variation} < 0.5) &&
                            (id_tau_vsJet_Medium_2__{variation} > 0.5) &&
                            (id_tau_vsJet_VVVLoose_1__{variation} > 0.5)
                        ) ||
                        (
                            (id_tau_vsJet_Medium_1__{variation} > 0.5) &&
                            (id_tau_vsJet_Medium_2__{variation} < 0.5) &&
                            (id_tau_vsJet_VVVLoose_2__{variation} > 0.5)
                        )
                    )""",
                "tau_anti_iso"
            ),
            Weight(
                f"""(
                    (0.5) * (
                        ({RuntimeVariables.FF_name_tt_1}__{variation} * (id_tau_vsJet_Medium_1__{variation} < 0.5)) +
                        ({RuntimeVariables.FF_name_tt_2}__{variation} * (id_tau_vsJet_Medium_2__{variation} < 0.5))
                    )
                )""",
                "fake_factor",
            ),
        )
    )
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"anti_iso_CMS_scale_t_1prong_Era{shift}", f"tauEs1prong0pizero{shift}"),
        (f"anti_iso_CMS_scale_t_1prong1pizero_Era{shift}", f"tauEs1prong1pizero{shift}"),
        (f"anti_iso_CMS_scale_t_3prong_Era{shift}", f"tauEs3prong0pizero{shift}"),
        (f"anti_iso_CMS_scale_t_3prong1pizero_Era{shift}", f"tauEs3prong1pizero{shift}"),
    ]
]

# tt channel emb process
ff_variations_tau_es_emb_tt = [
    LazyVariable(  # requieres LazyVariation since Used.FF_name_tt may be defined later
        lambda: ReplaceVariableReplaceCutAndAddWeight(
            name,
            variation,
            "tau_iso",
            Cut(
                f"""(
                        (
                            (id_tau_vsJet_Medium_1__{variation} < 0.5) &&
                            (id_tau_vsJet_Medium_2__{variation} > 0.5) &&
                            (id_tau_vsJet_VVVLoose_1__{variation} > 0.5)
                        ) ||
                        (
                            (id_tau_vsJet_Medium_1__{variation} > 0.5) &&
                            (id_tau_vsJet_Medium_2__{variation} < 0.5) &&
                            (id_tau_vsJet_VVVLoose_2__{variation} > 0.5)
                        )
                    )""",
                "tau_anti_iso"
            ),
            Weight(
                f"""(
                    (0.5) * (
                        ({RuntimeVariables.FF_name_tt_1}__{variation} * (id_tau_vsJet_Medium_1__{variation} < 0.5)) +
                        ({RuntimeVariables.FF_name_tt_2}__{variation} * (id_tau_vsJet_Medium_2__{variation} < 0.5))
                    )
                )""",
                "fake_factor",
            ),
        )
    )
    for shift in SHIFT_DIRECTIONS
    for name, variation in [
        (f"anti_iso_CMS_scale_t_emb_1prong_Era{shift}", f"tauEs1prong0pizero{shift}"),
        (f"anti_iso_CMS_scale_t_emb_1prong1pizero_Era{shift}", f"tauEs1prong1pizero{shift}"),
        (f"anti_iso_CMS_scale_t_emb_3prong_Era{shift}", f"tauEs3prong0pizero{shift}"),
        (f"anti_iso_CMS_scale_t_emb_3prong1pizero_Era{shift}", f"tauEs3prong1pizero{shift}"),
    ]
]

# qcd variations
qcd_variations_em = [  # TODO: Check if the name is correct and if it is still applicable, redo otherwise
    ReplaceCutAndAddWeight(name, "os", Cut("q_1*q_2>0", "ss"), Weight(weight, "qcd_weight"))
    for shift in SHIFT_DIRECTIONS
    for name, weight in [
        (f"same_sign_CMS_htt_qcd_0jet_rate_Era{shift}", f"em_qcd_osss_stat_0jet_rate{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_0jet_shape_Era{shift}", f"em_qcd_osss_stat_0jet_shape{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_0jet_shape2_Era{shift}", f"em_qcd_osss_stat_0jet_shape2{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_1jet_rate_Era{shift}", f"em_qcd_osss_stat_1jet_rate{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_1jet_shape_Era{shift}", f"em_qcd_osss_stat_1jet_shape{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_1jet_shape2_Era{shift}", f"em_qcd_osss_stat_1jet_shape2{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_2jet_rate_Era{shift}", f"em_qcd_osss_stat_2jet_rate{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_2jet_shape_Era{shift}", f"em_qcd_osss_stat_2jet_shape{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_2jet_shape2_Era{shift}", f"em_qcd_osss_stat_2jet_shape2{shift.lower()}_Weight"),
        (f"same_sign_CMS_htt_qcd_iso_Era{shift}", f"em_qcd_extrap_{shift.lower()}_Weight"),
        (f"{shift}", f"{shift.lower()}_Weight"),
    ]
]

# Signal uncertainties
ggH_htxs = {
    "ggH125": _get_stxs_bin_or_range(100, 117),
    "ggH_GG2H_FWDH125": _get_stxs_bin_or_range(100),
    "ggH_GG2H_PTH_200_300125": _get_stxs_bin_or_range(101),
    "ggH_GG2H_PTH_300_450125": _get_stxs_bin_or_range(102),
    "ggH_GG2H_PTH_450_650125": _get_stxs_bin_or_range(103),
    "ggH_GG2H_PTH_GT650125": _get_stxs_bin_or_range(104),
    "ggH_GG2H_0J_PTH_0_10125": _get_stxs_bin_or_range(105),
    "ggH_GG2H_0J_PTH_GT10125": _get_stxs_bin_or_range(106),
    "ggH_GG2H_1J_PTH_0_60125": _get_stxs_bin_or_range(107),
    "ggH_GG2H_1J_PTH_60_120125": _get_stxs_bin_or_range(108),
    "ggH_GG2H_1J_PTH_120_200125": _get_stxs_bin_or_range(109),
    "ggH_GG2H_GE2J_MJJ_0_350_PTH_0_60125": _get_stxs_bin_or_range(110),
    "ggH_GG2H_GE2J_MJJ_0_350_PTH_60_120125": _get_stxs_bin_or_range(111),
    "ggH_GG2H_GE2J_MJJ_0_350_PTH_120_200125": _get_stxs_bin_or_range(112),
    "ggH_GG2H_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25125": _get_stxs_bin_or_range(113),
    "ggH_GG2H_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25125": _get_stxs_bin_or_range(114),
    "ggH_GG2H_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25125": _get_stxs_bin_or_range(115),
    "ggH_GG2H_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25125": _get_stxs_bin_or_range(116),
}
qqH_htxs = {
    "qqH125": _get_stxs_bin_or_range(200, 210),
    "qqH_QQ2HQQ_FWDH125": _get_stxs_bin_or_range(200),
    "qqH_QQ2HQQ_0J125": _get_stxs_bin_or_range(201),
    "qqH_QQ2HQQ_1J125": _get_stxs_bin_or_range(202),
    "qqH_QQ2HQQ_GE2J_MJJ_0_60125": _get_stxs_bin_or_range(203),
    "qqH_QQ2HQQ_GE2J_MJJ_60_120125": _get_stxs_bin_or_range(204),
    "qqH_QQ2HQQ_GE2J_MJJ_120_350125": _get_stxs_bin_or_range(205),
    "qqH_QQ2HQQ_GE2J_MJJ_GT350_PTH_GT200125": _get_stxs_bin_or_range(206),
    "qqH_QQ2HQQ_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25125": _get_stxs_bin_or_range(207),
    "qqH_QQ2HQQ_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25125": _get_stxs_bin_or_range(208),
    "qqH_QQ2HQQ_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25125": _get_stxs_bin_or_range(209),
    "qqH_QQ2HQQ_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25125": _get_stxs_bin_or_range(210),
}
WH_htxs = {
    "WH_lep125": _get_stxs_bin_or_range(300, 305),
    "WH_lep_QQ2HLNU_FWDH125": _get_stxs_bin_or_range(300),
    "WH_lep_QQ2HLNU_PTV_0_75125": _get_stxs_bin_or_range(301),
    "WH_lep_QQ2HLNU_PTV_75_150125": _get_stxs_bin_or_range(302),
    "WH_lep_QQ2HLNU_PTV_150_250_0J125": _get_stxs_bin_or_range(303),
    "WH_lep_QQ2HLNU_PTV_150_250_GE1J125": _get_stxs_bin_or_range(304),
    "WH_lep_QQ2HLNU_PTV_GT250125": _get_stxs_bin_or_range(305),
}
ZH_htxs = {
    "ZH_lep125": _get_stxs_bin_or_range(400, 405),
    "ZH_lep_QQ2HLL_FWDH125": _get_stxs_bin_or_range(400),
    "ZH_lep_QQ2HLL_PTV_0_75125": _get_stxs_bin_or_range(401),
    "ZH_lep_QQ2HLL_PTV_75_150125": _get_stxs_bin_or_range(402),
    "ZH_lep_QQ2HLL_PTV_150_250_0J125": _get_stxs_bin_or_range(403),
    "ZH_lep_QQ2HLL_PTV_150_250_GE1J125": _get_stxs_bin_or_range(404),
    "ZH_lep_QQ2HLL_PTV_GT250125": _get_stxs_bin_or_range(405),
}
ggZH_htxs = {
    "ggZH_lep125": _get_stxs_bin_or_range(500, 505),
    "ggZH_lep_GG2HLL_FWDH125": _get_stxs_bin_or_range(500),
    "ggZH_lep_GG2HLL_PTV_0_75125": _get_stxs_bin_or_range(501),
    "ggZH_lep_GG2HLL_PTV_75_150125": _get_stxs_bin_or_range(502),
    "ggZH_lep_GG2HLL_PTV_150_250_0J125": _get_stxs_bin_or_range(503),
    "ggZH_lep_GG2HLL_PTV_150_250_GE1J125": _get_stxs_bin_or_range(504),
    "ggZH_lep_GG2HLL_PTV_GT250125": _get_stxs_bin_or_range(505),
}

scheme_ggH = {
    "ggH_scale_0jet": [
        "ggH_GG2H_0J_PTH_0_10125",
        "ggH_GG2H_0J_PTH_GT10125",
    ],
    "ggH_scale_1jet_lowpt": [
        "ggH_GG2H_1J_PTH_0_60125",
        "ggH_GG2H_1J_PTH_60_120125",
        "ggH_GG2H_1J_PTH_120_200125",
    ],
    "ggH_scale_2jet_lowpt": [
        "ggH_GG2H_GE2J_MJJ_0_350_PTH_0_60125",
        "ggH_GG2H_GE2J_MJJ_0_350_PTH_60_120125",
        "ggH_GG2H_GE2J_MJJ_0_350_PTH_120_200125",
    ],
    "ggH_scale_highpt": [
        "ggH_GG2H_PTH_200_300125",
        "ggH_GG2H_PTH_300_450125",
    ],
    "ggH_scale_very_highpt": [
        "ggH_GG2H_PTH_450_650125",
        "ggH_GG2H_PTH_GT650125",
    ],
    "ggH_scale_vbf": [
        "ggH_GG2H_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25125",
        "ggH_GG2H_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25125",
        "ggH_GG2H_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25125",
        "ggH_GG2H_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25125",
    ],
}
scheme_qqH = {
    "qqh_scale_0jet": ["qqH_QQ2HQQ_0J125"],
    "qqh_scale_1jet": ["qqH_QQ2HQQ_1J125"],
    "qqh_scale_lowmjj": [
        "qqH_QQ2HQQ_GE2J_MJJ_0_60125",
        "qqH_QQ2HQQ_GE2J_MJJ_60_120125",
        "qqH_QQ2HQQ_GE2J_MJJ_120_350125",
    ],
    "qqh_scale_highmjj_lowpt": [
        "qqH_QQ2HQQ_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_0_25125",
        "qqH_QQ2HQQ_GE2J_MJJ_350_700_PTH_0_200_PTHJJ_GT25125",
        "qqH_QQ2HQQ_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_0_25125",
        "qqH_QQ2HQQ_GE2J_MJJ_GT700_PTH_0_200_PTHJJ_GT25125",
    ],
    "qqh_scale_highmjj_highpt": ["qqH_QQ2HQQ_GE2J_MJJ_GT350_PTH_GT200125"],
}

ggh_acceptance = []
for unc in [
    "THU_ggH_Mig01",
    "THU_ggH_Mig12",
    "THU_ggH_Mu",
    "THU_ggH_PT120",
    "THU_ggH_PT60",
    "THU_ggH_Res",
    "THU_ggH_VBF2j",
    "THU_ggH_VBF3j",
    "THU_ggH_qmtop",
]:
    ggh_acceptance.append(AddWeight(f"{unc}Up", Weight(f"({unc})", f"{unc}_weight")))
    ggh_acceptance.append(AddWeight(f"{unc}Down", Weight(f"(2.0-{unc})", f"{unc}_weight")))

# ---

qqh_acceptance = []
for unc in [
    "THU_qqH_25",
    "THU_qqH_JET01",
    "THU_qqH_Mjj1000",
    "THU_qqH_Mjj120",
    "THU_qqH_Mjj1500",
    "THU_qqH_Mjj350",
    "THU_qqH_Mjj60",
    "THU_qqH_Mjj700",
    "THU_qqH_PTH200",
    "THU_qqH_TOT",
]:
    qqh_acceptance.append(AddWeight(f"{unc}Up", Weight(f"({unc})", f"{unc}_weight")))
    qqh_acceptance.append(AddWeight(f"{unc}Down", Weight(f"(2.0-{unc})", f"{unc}_weight")))

ggh_muRmuF_acceptance, qqh_muRmuF_acceptance, vh_as_qqh_muRmuF_acceptance = [], [], []
for _container, _scheme, _cuts, _postfix in [
    (ggh_muRmuF_acceptance, scheme_ggH, ggH_htxs, "ggH"),
    (qqh_muRmuF_acceptance, scheme_qqH, qqH_htxs, "qqH"),
    # Same qqH STXS-1.2 categorization/cuts as qqh_muRmuF_acceptance above, but for
    # the hadronic-decay WminusH/WplusH/ZH events booked as the "vh_as_qqh" process
    # (see shapes/produce_shapes.py) -- those ntuples only carry "_VH"-postfixed
    # lhe_scale_weight branches (CROWN's "rem_htautau" sample type), never "_qqH".
    (vh_as_qqh_muRmuF_acceptance, scheme_qqH, qqH_htxs, "VH"),
]:
    for shift, scale_type in product(("Up", "Down"), ("muR", "muF")):
        _qcd_scale_kind = "ren" if scale_type == "muR" else "fac"
        for scheme, scheme_collection in _scheme.items():
            _container.append(
                AddWeight(
                    f"{scheme}_{scale_type}_{shift}",
                    Weight(
                        " * ".join(
                            f"""(
                                1.0 + (
                                    (
                                        lhe_scale_weight__QCDscale_{_qcd_scale_kind}_{_postfix}{shift} - 1.0
                                    ) * ({_cuts[scheme_parts]})
                                )
                            )"""
                            for scheme_parts in scheme_collection
                        ),
                        f"stxs_acceptance_uncertainty_{scale_type}_variation_{scheme}_{shift.lower()}",
                    )
                )
            )

# ------------------------------------------------------------------------------------------
# collections for ordering


__doc__ = """
Usage Example for Variation Collections

This module defines several systematic variation collections that group different
systematic adjustments such as fake process estimations, energy scale shifts, MET variations,
efficiency corrections, fake rate variations, trigger efficiencies, and additional uncertainties.
Each collection can be applied at once using `<VariationCollection>.unrolled()` that returns a
list of all variations defined within that collection.

For example, instead of fetching each variation individually this would be possible:

    from shapes.selection import variations

    # Retrieve and loop over all fake process estimation variations
    variations = [
        tau_es_3prong,
        tau_es_3prong1pizero,
        tau_es_1prong,
        tau_es_1prong1pizero,
        ...
    ]
    # Or use
    variations = variations.EnergyScaleVariations.unrolled()
    # Or another collection you might seems be more fitting i.e. process wise.

This pattern applies similarly to other collections. Thus, you only need to import the corresponding
variation collection and call its `unrolled()` method to obtain a list of all variations, making the
application of systematics both concise and consistent.

The individual Application either trough variations.tau_es_3prong or variations.EnergyScaleVariations.tau_es_3prong
is still possible.
"""


class VariationCollectionMeta(type):
    def __add__(cls, other):
        if not issubclass(other, _VariationCollection):
            raise TypeError("Cannot add {} to {}".format(other, cls))
        merged_attrs = {
            **{k: v for k, v in cls.__dict__.items() if not k.startswith("__")},
            **{k: v for k, v in other.__dict__.items() if not k.startswith("__")},
        }
        return type(f"{cls.__name__}+{other.__name__}", (_VariationCollection,), merged_attrs)


class _VariationCollection(metaclass=VariationCollectionMeta):
    @classmethod
    def unrolled(cls):
        results = []
        for name, value in cls.__dict__.items():
            if not name.startswith("__"):
                results.append(value)
        return results


class SemiLeptonicFFEstimations(_VariationCollection):
    anti_iso_lt = anti_iso_lt
    same_sign_anti_iso_lt = same_sign_anti_iso_lt


class FullyHadronicFFEstimations(_VariationCollection):
    abcd_method = abcd_method
    anti_iso_tt = anti_iso_tt


# ------------------------------------------------------------------------------------------

def _lhe_scale_variation_collection(postfix):
    class _LHEScaleForMode(_VariationCollection):
        LHE_scale_norm_muR = _lhe_scale_norm_muR(postfix)
        LHE_scale_norm_muF = _lhe_scale_norm_muF(postfix)
        PS_scale_norm_Fsr = _ps_scale_norm_fsr(postfix)
        PS_scale_norm_Isr = _ps_scale_norm_isr(postfix)
        LHE_pdf = _lhe_pdf(postfix)
        LHE_alphaS = _lhe_alphaS(postfix)
    return _LHEScaleForMode


# One collection per STXS stage-0 Higgs production mode -- booked onto the
# matching signal process only (see shapes/produce_shapes.py), since the
# LHE-scale/PS/PDF theory variations are uncorrelated nuisances per mode.
LHE_scale_ggH = _lhe_scale_variation_collection("ggH")
LHE_scale_qqH = _lhe_scale_variation_collection("qqH")
LHE_scale_VH = _lhe_scale_variation_collection("VH")
LHE_scale_ttH = _lhe_scale_variation_collection("ttH")


class TauEmbeddingEnergyScale(_VariationCollection):
    emb_tau_es_3prong = emb_tau_es_3prong
    emb_tau_es_3prong1pizero = emb_tau_es_3prong1pizero
    emb_tau_es_1prong = emb_tau_es_1prong
    emb_tau_es_1prong1pizero = emb_tau_es_1prong1pizero


class FakeFactorLT(_VariationCollection):
    ff_variations_lt = ff_variations_lt


class TauIDAndTriggerEfficiency(_VariationCollection):
    emb_tau_id_eff_tt = emb_tau_id_eff_tt
    tau_id_eff_tt = tau_id_eff_tt
    # tau_trigger_eff_tt_emb = tau_trigger_eff_tt_emb
    # tau_trigger_eff_tt = tau_trigger_eff_tt
    # emb_decay_mode_eff_tt = emb_decay_mode_eff_tt


# ------------------------------------------------------------------------------------------


class FakeProcessEstimationVariations(_VariationCollection):
    same_sign = same_sign
    same_sign_em = same_sign_em
    anti_iso_lt = anti_iso_lt
    anti_iso_tt = anti_iso_tt
    abcd_method = abcd_method


class EnergyScaleVariations(_VariationCollection):
    # tau_es_3prong/tau_es_3prong1pizero/tau_es_1prong/tau_es_1prong1pizero
    # live in tau_energy_scale(era) now (era-parameterized, not a static
    # list) -- see shapes/produce_shapes.py for how it's booked.
    # mu_fake_es_inc lives in mu_fake_es_inc(era) now (era-parameterized,
    # not a static list) -- see shapes/produce_shapes.py for how it's booked.
    ele_fake_es = ele_fake_es
    emb_tau_es_3prong = emb_tau_es_3prong
    emb_tau_es_3prong1pizero = emb_tau_es_3prong1pizero
    emb_tau_es_1prong = emb_tau_es_1prong
    emb_tau_es_1prong1pizero = emb_tau_es_1prong1pizero
    # jet_es lives in jet_energy_scale(era)/jet_energy_resolution(era) now
    # (era-parameterized, not a static list) -- see shapes/produce_shapes.py
    # for how it's booked.
    # TODO add missing ES
    # mu_fake_es_1prong = mu_fake_es_1prong
    # mu_fake_es_1prong1pizero = mu_fake_es_1prong1pizero
    # ele_es = ele_es
    # ele_res = ele_res
    emb_e_es,
    # ele_fake_es_1prong = ele_fake_es_1prong
    # ele_fake_es_1prong1pizero = ele_fake_es_1prong1pizero
    # ele_fake_es = ele_fake_es


class METVariations(_VariationCollection):
    # met_unclustered/recoil_resolution/recoil_response live in
    # met_unclustered(era)/recoil_resolution(era)/recoil_response(era) now
    # (era-parameterized, not a static list) -- see shapes/produce_shapes.py
    # for how they're booked.
    pass


class EffifiencyVariations(_VariationCollection):
    # tau_id_eff_lt lives in tau_id_eff_lt(era) now (era-parameterized, not a
    # static list) -- see shapes/produce_shapes.py for how it's booked.
    tau_id_eff_tt = tau_id_eff_tt
    emb_tau_id_eff_lt = emb_tau_id_eff_lt
    emb_tau_id_eff_tt = emb_tau_id_eff_tt
    emb_tau_id_eff_lt_corr = emb_tau_id_eff_lt_corr


class FakeRateVariations(_VariationCollection):
    jet_to_tau_fake = jet_to_tau_fake
    zll_et_fake_rate = zll_et_fake_rate
    zll_mt_fake_rate = zll_mt_fake_rate


# trigger_eff_mt/et/tt are booked directly in shapes/produce_shapes.py
# (per-channel, not through a _VariationCollection) -- the
# TriggerEfficiencyVariations class formerly here was unused (never
# .unrolled()'d anywhere) and referenced the removed _emb variants; removed.


# Additional uncertainties
class AdditionalVariations(_VariationCollection):
    prefiring = prefiring
    top_pt = top_pt
    # zpt/pileup_reweighting live in zpt(era)/pileup_reweighting(era) now
    # (era-parameterized, not a static list) -- see shapes/produce_shapes.py
    # for how they're booked.
    # TODO add missing uncertainties
    # btag_eff = btag_eff
    # mistag_eff = mistag_eff
    # emb_decay_mode_eff_lt = emb_decay_mode_eff_lt
    # emb_decay_mode_eff_tt = emb_decay_mode_eff_tt


class JetFakeVariations(_VariationCollection):
    # TODO add jetfake uncertainties
    ff_variations_lt = ff_variations_lt
    ff_variations_tau_es_lt = ff_variations_tau_es_lt
    ff_variations_tau_es_emb_lt = ff_variations_tau_es_emb_lt
    ff_variations_tt = ff_variations_tt
    # qcd_variations_em = qcd_variations_em
    ff_variations_tau_es_tt = ff_variations_tau_es_tt
    ff_variations_tau_es_emb_tt = ff_variations_tau_es_emb_tt

# ------------------------------------------------------------------------------------------

# TODO: TBD, needed or not, collection:

# # fake met scaling in embedded samples
# emb_met_scale = [  # TODO: Check if needed or is replaced
#         ReplaceVariable("scale_embed_metUp", "emb_scale_metUp"),
#         ReplaceVariable("scale_embed_metDown", "emb_scale_metDown")
#         ]
# # cross triggers
# trigger_eff_mt = [  # TODO: Check if needed or is replaced
#     *[
#         ReplaceWeight(
#             name,
#             "triggerweight",
#             Weight(weight, "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for name, weight in [
#             (f"CMS_eff_trigger_mt_Era{shift}", f"mtau_triggerweight_ic_singlelep_{shift.lower()}"),
#             (f"CMS_eff_xtrigger_l_mt_Era{shift}", f"mtau_triggerweight_ic_crosslep_{shift.lower()}"),
#             (f"CMS_eff_trigger_single_t_Era{shift}", f"mtau_triggerweight_ic_singletau_{shift.lower()}")
#         ]
#     ],
#     *[
#         ReplaceWeight(
#             f"CMS_eff_xtrigger_t_mt_dm{dm}_Era{shift}",
#             "triggerweight",
#             Weight(f"mtau_triggerweight_ic_dm{dm}_{shift.lower()}", "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for dm in [0, 1, 10, 11]
#     ],
# ]
# trigger_eff_mt_emb = [  # TODO: Check if needed or is replaced
#     *[
#         ReplaceWeight(
#             name,
#             "triggerweight",
#             Weight(weight, "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for name, weight in [
#             (f"CMS_eff_trigger_emb_mt_Era{shift}", f"mtau_triggerweight_ic_singlelep_{shift.lower()}"),
#             (f"CMS_eff_xtrigger_l_emb_mt_Era{shift}", f"mtau_triggerweight_ic_crosslep_{shift.lower()}"),
#             (f"CMS_eff_trigger_single_t_emb_Era{shift}", f"mtau_triggerweight_ic_singletau_{shift.lower()}")
#         ]
#     ],
#     *[
#         ReplaceWeight(
#             f"CMS_eff_xtrigger_t_emb_mt_dm{dm}_Era{shift}",
#             "triggerweight",
#             Weight(f"mtau_triggerweight_ic_dm{dm}_{shift.lower()}", "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for dm in [0, 1, 10, 11]
#     ]
# ]
# trigger_eff_et = [  # TODO: Check if needed or is replaced
#     *[
#         ReplaceWeight(
#             name,
#             "triggerweight",
#             Weight(weight, "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for name, weight in [
#             (f"CMS_eff_trigger_et_Era{shift}", f"etau_triggerweight_ic_singlelep_{shift.lower()}"),
#             (f"CMS_eff_xtrigger_l_et_Era{shift}", f"etau_triggerweight_ic_crosslep_{shift.lower()}"),
#             (f"CMS_eff_trigger_single_t_Era{shift}", f"etau_triggerweight_ic_singletau_{shift.lower()}")
#         ]
#     ],
#     *[
#         ReplaceWeight(
#             f"CMS_eff_xtrigger_t_et_dm{dm}_Era{shift}",
#             "triggerweight",
#             Weight(f"etau_triggerweight_ic_dm{dm}_{shift.lower()}", "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for dm in [0, 1, 10, 11]
#     ]
# ]
# trigger_eff_et_emb = [  # TODO: Check if needed or is replaced
#     *[
#         ReplaceWeight(
#             name,
#             "triggerweight",
#             Weight(weight, "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for name, weight in [
#             (f"CMS_eff_trigger_emb_et_Era{shift}", f"etau_triggerweight_ic_singlelep_{shift.lower()}"),
#             (f"CMS_eff_xtrigger_l_emb_et_Era{shift}", f"etau_triggerweight_ic_crosslep_{shift.lower()}"),
#             (f"CMS_eff_trigger_single_t_emb_Era{shift}", f"etau_triggerweight_ic_singletau_{shift.lower()}")
#         ]
#     ],
#     *[
#         ReplaceWeight(
#             f"CMS_eff_xtrigger_t_emb_et_dm{dm}_Era{shift}",
#             "triggerweight",
#             Weight(f"etau_triggerweight_ic_dm{dm}_{shift.lower()}", "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for dm in [0, 1, 10, 11]
#     ]
# ]
# tau_trigger_eff_tt = [  # TODO: Check if needed or is replaced
#     *[
#         ReplaceWeight(
#             name,
#             "triggerweight",
#             Weight(weight, "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for dm in [0, 1, 10, 11]
#         for name, weight in [
#             (f"CMS_eff_xtrigger_t_tt_dm{dm}_Era{shift}", f"tautau_triggerweight_ic_lowpt_dm{dm}_{shift.lower()}")
#             (f"CMS_eff_xtrigger_t_tt_dm{dm}_highpT_Era{shift}", f"tautau_triggerweight_ic_highpt_dm{dm}_{shift.lower()}")
#         ]
#     ],
#     *[
#         ReplaceWeight(
#             f"CMS_eff_trigger_single_t_Era{shift}",
#             "triggerweight",
#             Weight(f"tautau_triggerweight_ic_singletau_{shift.lower()}", "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#     ]
# ]
# tau_trigger_eff_tt_emb = [  # TODO: Check if needed or is replaced
#     *[
#         ReplaceWeight(
#             name,
#             "triggerweight",
#             Weight(weight, "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#         for dm in [0, 1, 10, 11]
#         for name, weight in [
#             (f"CMS_eff_xtrigger_t_emb_tt_dm{dm}_Era{shift}", f"tautau_triggerweight_ic_lowpt_dm{dm}_{shift.lower()}"),
#             (f"CMS_eff_xtrigger_t_emb_tt_dm{dm}_highpT_Era{shift}", f"tautau_triggerweight_ic_highpt_dm{dm}_{shift.lower()}")
#         ]
#     ],
#     *[
#         ReplaceWeight(
#             f"CMS_eff_trigger_single_t_emb_Era{shift}",
#             "triggerweight",
#             Weight(f"tautau_triggerweight_ic_singletau_{shift.lower()}", "triggerweight"),
#         )
#         for shift in SHIFT_DIRECTIONS
#     ]
# ]
# # embedded lt eff by decay mode
# emb_decay_mode_eff_lt = [  # TODO: Check if needed or is replaced,  add embeddedDecayModeWeight, Needed or covered by something other?
#     ReplaceWeight(
#         name,
#         "decayMode_SF",
#         Weight(weight, "decayMode_SF"),
#     )
#     for shift in SHIFT_DIRECTIONS
#     for name, weight in [
#         (f"CMS_3ProngEff_Era{shift}", f"(pt_2<100)*embeddedDecayModeWeight_eff{shift}_pi0Nom+(pt_2>=100)"),
#         (f"CMS_1ProngPi0Eff_Era{shift}", f"(pt_2<100)*embeddedDecayModeWeight_effNom_pi0{shift}+(pt_2>=100)"),
#     ]
# ]
# _emb_decay_mode_eff_tt = [  # TODO: Check if needed or is replaced,  add embeddedDecayModeWeight, Needed or covered by something other?
#     ReplaceWeight(
#         "CMS_3ProngEff_EraUp",
#         "decayMode_SF",
#         Weight(
#             "(pt_2>=100)+(pt_1<100)*embeddedDecayModeWeight_effUp_pi0Nom+(pt_1>=100)*(pt_2<100)*((decayMode_2==0)*0.983+(decayMode_2==1)*0.983*1.051+(decayMode_2==10)*0.983*0.983*0.983+(decayMode_2==11)*0.983*0.983*0.983*1.051)",
#             "decayMode_SF",
#         ),
#     ),
#     ReplaceWeight(
#         "CMS_3ProngEff_EraDown",
#         "decayMode_SF",
#         Weight(
#             "(pt_2>=100)+(pt_1<100)*embeddedDecayModeWeight_effDown_pi0Nom+(pt_1>=100)*(pt_2<100)*((decayMode_2==0)*0.967+(decayMode_2==1)*0.967*1.051+(decayMode_2==10)*0.967*0.967*0.967+(decayMode_2==11)*0.967*0.967*0.967*1.051)",
#             "decayMode_SF",
#         ),
#     ),
#     ReplaceWeight(
#         "CMS_1ProngPi0Eff_EraUp",
#         "decayMode_SF",
#         Weight(
#             "(pt_2>=100)+(pt_1<100)*embeddedDecayModeWeight_effNom_pi0Up+(pt_1>=100)*(pt_2<100)*((decayMode_2==0)*0.975+(decayMode_2==1)*0.975*1.065+(decayMode_2==10)*0.975*0.975*0.975+(decayMode_2==11)*0.975*0.975*0.975*1.065)",
#             "decayMode_SF",
#         ),
#     ),
#     ReplaceWeight(
#         "CMS_1ProngPi0Eff_EraDown",
#         "decayMode_SF",
#         Weight(
#             "(pt_2>=100)+(pt_1<100)*embeddedDecayModeWeight_effNom_pi0Down+(pt_1>=100)*(pt_2<100)*((decayMode_2==0)*0.975+(decayMode_2==1)*0.975*1.037+(decayMode_2==10)*0.975*0.975*0.975+(decayMode_2==11)*0.975*0.975*0.975*1.037)",
#             "decayMode_SF",
#         ),
#     ),
# ]
