"""
Categorization for the ttbar+DY normalization-weight measurement ("tt_dy_weight"),
em channel only.

v2 (2026-09-08): replaces the original nbtag x m_vis-Z-peak 2x2 grid. Measured
on htt_260813_22-23 (see shapes/special/calculate_ttbar_dy_weights.py's
module docstring for the numbers): the "Z-peak" axis (m_vis in [72,112) vs
outside) turned out to carry essentially zero discriminating power between TT
and DY in the em channel -- process fractions were nearly identical inside vs
outside the window (e.g. 2022preEE nbtag0: TT/DY/VV = 32/32/31% on-peak vs
33/35/28% off-peak). That is expected in hindsight: DY's em contribution is
Z->tautau->e+mu, whose m_vis spectrum is broad and shifted well below 91 GeV
by the escaped tau neutrinos, not a narrow resonance -- a bare-mass "Z-peak"
window tuned for e+e-/mu+mu- doesn't apply. Meanwhile VV (WW->e+mu, an
irreducible, non-floated background here) sits at ~30% of nbtag==0 regardless
of the m_vis cut, further diluting whichever axis was meant to isolate DY.

Replaced the second axis with pzetamissvis, the standard CMS H->tautau
discriminant for genuine ditau vs. ttbar/WW in ll/em-like final states:
correlated visible+missing momenta (real ditau recoil) give pzetamissvis
values well above the ttbar/WW-like population, which skews negative from
uncorrelated W-decay neutrinos. Threshold at -25 GeV, the standard cut used
throughout the CMS HTT emu/ee/mumu control regions this branch is named for
(config/shapes/control_binning.py already books pzetamissvis over
[-150, 150) for control plots).

nbtag still does the heavy lifting it always did (nbtag>=1 is ~90% pure TT
with ~0% DY, see same docstring) -- pzeta now does real work splitting
nbtag==0 into a DY-enriched and a TT/VV-enriched half, instead of a m_vis cut
that split it into two statistically-identical halves.

Kept as four named sub-categories rather than a joint 2D histogram for the
same reason as before: ntuple_processor's Histogram only ever books a 1D
Histo1D (see ntuple_processor/run.py's __histo1d_from_histo), no Histo2D
support anywhere in this framework.
"""
from config.shapes.categorization import build_categorization
from config.shapes.control_binning import control_binning

_pzeta_threshold = -25.0
_dy_like_cut = f"(pzetamissvis > {_pzeta_threshold})"
_tt_like_cut = f"(pzetamissvis <= {_pzeta_threshold})"

categories = {
    "em": {
        "nbtag0_pzetahi": f"(nbtag == 0 && {_dy_like_cut})",
        "nbtag0_pzetalo": f"(nbtag == 0 && {_tt_like_cut})",
        "nbtagge1_pzetahi": f"(nbtag >= 1 && {_dy_like_cut})",
        "nbtagge1_pzetalo": f"(nbtag >= 1 && {_tt_like_cut})",
    }
}

# m_vis is the control-plot em binning, histogrammed in every region
categorization = build_categorization({"em": {region: (cut, [control_binning["em"]["m_vis"]]) for region, cut in categories["em"].items()}})
