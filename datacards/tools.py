"""
CombineHarvester post-processing utilities for TAUER datacard production: pure
CombineHarvester bookkeeping (negative-bin fixing, zero-yield filtering, shape-vs-lnN
conversion, Asimov replacement, NN-output rebinning).
"""
import ctypes
import logging
import math
import re
from typing import Literal, Optional, Dict, List

import ROOT

import CombineHarvester.CombineTools.ch as ch
from common.analysis import legacy_nuisance_name
from CustomLogging import setup_logging


logger = setup_logging(logger=logging.getLogger(__name__))


def filter_zero_yield_processes(cb: ch.CombineHarvester) -> None:
    logger.info("Filtering processes with null yield...")

    def filter_proc(p):
        if (null_yield := not (p.rate() > 0.0)):
            logger.warning(f"Removing process {p.process()} in bin {p.bin()} with null yield")
            cb.FilterSysts(lambda s: s.bin() == p.bin() and s.process() == p.process() and s.era() == p.era())
        return null_yield

    cb.FilterProcs(filter_proc)


def fix_negative_bins(cb: ch.CombineHarvester) -> None:
    logger.info("Fixing negative bins to zero...")

    def zero_negative_bins_th1(hist):
        if not hist:
            return False
        has_negative = False
        for i in range(1, hist.GetNbinsX() + 1):
            if hist.GetBinContent(i) < 0.0:
                has_negative = True
                hist.SetBinContent(i, 0.0)
        # Process/Systematic shapes are stored unit-normalized (integral == 1),
        # with the absolute normalization cached separately (rate_/value_u_/value_d_).
        # Zeroing negative bins raises the integral above 1, so it must be rescaled
        # back to unit integral to keep the cached normalization consistent with
        # the shape that gets written out later.
        if has_negative and hist.Integral() > 0.0:
            hist.Scale(1.0 / hist.Integral())
        return has_negative

    cb.ForEachProc(lambda p: zero_negative_bins_th1(p.shape()))

    def fix_syst(s):
        if (s.type() == "shape") and (hist_up := s.shape_u()):
            zero_negative_bins_th1(hist_up)
        if (s.type() == "shape") and (hist_down := s.shape_d()):
            zero_negative_bins_th1(hist_down)

    cb.ForEachSyst(fix_syst)


def filter_zero_yield_systs(cb: ch.CombineHarvester) -> None:
    logger.info("Filtering shape systematics with null yield...")

    def hist_integral(hist):
        if not hist:
            return None
        return hist.Integral(1, hist.GetNbinsX())

    def filter_syst(s):
        if s.type() == "shape":
            shape_u, shape_d = s.shape_u(), s.shape_d()
            if not shape_u or not shape_d:
                logger.warning(f"Removing systematic {s.name()} on {s.process()} with missing shape")
                return True

            yield_u, yield_d = hist_integral(shape_u), hist_integral(shape_d)

            if yield_u is None or yield_d is None:
                return True

            if yield_u == 0.0 or yield_d == 0.0:
                logger.warning(f"Removing systematic {s.name()} on {s.process()} with null yield in shift")
                return True
        return False
    cb.FilterSysts(filter_syst)


def load_systematic_shapes(cb: ch.CombineHarvester, root_file: str, channel: str, variable: str) -> None:
    logger.info(f"Loading shape systematics for {channel} from {root_file}")
    tfile = ROOT.TFile.Open(root_file, "READ")

    def has_shapes(s):
        mass, process = s.mass(), s.process()
        process = f"{process}{mass}" if mass and mass != "*" else process
        base = f"{variable}/{s.bin()}/{process}_{s.name()}"
        return bool(tfile.Get(base + "Up")) and bool(tfile.Get(base + "Down"))

    def filter_missing(s):
        if s.channel() != channel or s.type() != "shape":
            return False
        if not has_shapes(s):
            logger.warning(f"Removing systematic {s.name()} on {s.process()} with missing shape")
            return True
        return False

    cb.FilterSysts(filter_missing)
    tfile.Close()

    scope = cb.cp().channel([channel])
    scope.cp().backgrounds().ExtractShapes(root_file, f"{variable}/$BIN/$PROCESS", f"{variable}/$BIN/$PROCESS_$SYSTEMATIC")
    pattern = signal_shape_pattern(cb, variable)
    scope.cp().signals().ExtractShapes(root_file, pattern, f"{pattern}_$SYSTEMATIC")


def signal_shape_pattern(cb, variable: str) -> str:
    """Signal shape name: `$PROCESS$MASS` for mass-labelled signals, plain `$PROCESS` for the mass-less STXS stage-1.2 models."""
    return f"{variable}/$BIN/$PROCESS" if set(cb.mass_set()) <= {"*", ""} else f"{variable}/$BIN/$PROCESS$MASS"


def convert_shapes_to_lnN(cb: ch.CombineHarvester) -> None:
    # Checks shape systematics. If the normalization shift and the bin-by-bin shape change are both within the
    # statistical uncertainty of the templates, it replaces the shape systematic with a symmetrized lnN systematic.

    logger.info("Checking shape systematics for lnN conversion...")
    count = {"lnN": 0, "all": 0, "all_considered": 0}

    def check_and_convert(s):
        if s.type() != "shape":
            return

        count["all"] += 1
        name = s.name()
        if any(
            substring in name for substring in [
                "scale",
                "CMS_htt_boson_res_met",
                "res_j",
                "res_e",
            ]
        ):
            count["all_considered"] += 1
            shape_u, shape_d = s.shape_u(), s.shape_d()

            if not shape_u or not shape_d:
                return

            nbins = shape_u.GetNbinsX()
            err_u_ref, err_d_ref = ctypes.c_double(0.0), ctypes.c_double(0.0)

            yield_u = shape_u.IntegralAndError(1, nbins, err_u_ref)
            yield_d = shape_d.IntegralAndError(1, nbins, err_d_ref)

            err_u, err_d = err_u_ref.value, err_d_ref.value

            if yield_u <= 0.0 or yield_d <= 0.0:
                return

            value_u, value_d = s.value_u(), s.value_d()

            # bin-by-bin difference of the unit-area up and down templates in units of their statistical uncertainty
            chi2, ndf = 0.0, 0
            for i in range(1, nbins + 1):
                var = (shape_u.GetBinError(i) / yield_u) ** 2 + (shape_d.GetBinError(i) / yield_d) ** 2
                if var > 0.0:
                    chi2 += (shape_u.GetBinContent(i) / yield_u - shape_d.GetBinContent(i) / yield_d) ** 2 / var
                    ndf += 1

            # Are both the normalisation shift and the shape change smaller than the statistical uncertainty of the shift?
            if abs(value_u - 1.0) + abs(value_d - 1.0) < (err_u / yield_u) + (err_d / yield_d) and chi2 <= ndf:
                count["lnN"] += 1
                logger.warning(f"Replacing systematic by lnN: {name} (bin: {s.bin()}, proc: {s.process()})")

                s.set_type("lnN")
                up_is_larger = (value_u > value_d)

                if value_u < 1.0:
                    value_u = 1.0 / value_u
                if value_d < 1.0:
                    value_d = 1.0 / value_d

                if up_is_larger:  # Symmetrize
                    value_u = math.sqrt(value_u * value_d)
                    value_d = 1.0 / value_u
                else:
                    value_d = math.sqrt(value_u * value_d)
                    value_u = 1.0 / value_d

                s.set_value_u(value_u)
                s.set_value_d(value_d)

    cb.cp().ForEachSyst(check_and_convert)
    logger.warning(f"Turned {count['lnN']} of {count['all_considered']} considered (out of {count['all']}) checked systematics into lnN.")


_THEORY_NUISANCE = re.compile(r"THU_.*|BR_.*|pdf_.*|alphaS_.*|ps_.*|.*QCDscale.*")


def prune_signals(cb: ch.CombineHarvester, drop_processes: bool = False, syst_fraction: float = 0.01, syst_budget: float = 0.05,
                  proc_fraction: float = 0.001, proc_budget: float = 0.005) -> dict:
    """STXS pruning of the recommendations (PruningStrategies.md), per category, smallest signal processes first: step 1 drops the
    experimental systematics of processes below syst_fraction of the category's signal until syst_budget of it is reached, step 2
    (drop_processes) drops processes below proc_fraction until proc_budget. Theory nuisances are never pruned. Returns what was pruned."""
    pruned = {}
    for category in sorted(cb.bin_set()):
        signals = cb.cp().bin([category]).signals()
        rates = {p: signals.cp().process([p]).GetRate() for p in signals.process_set()}
        total = sum(rates.values())
        if total <= 0:
            continue
        steps = [("systematics", syst_fraction, syst_budget)] + ([("processes", proc_fraction, proc_budget)] if drop_processes else [])
        for step, fraction, budget in steps:
            selected, cumulated = _smallest_processes(rates, total, fraction, budget)
            if not selected:
                continue
            pruned.setdefault(category, {})[step] = {"processes": selected, "signal_fraction": cumulated / total}
            if step == "systematics":
                cb.FilterSysts(lambda s: s.bin() == category and s.process() in selected and not _THEORY_NUISANCE.fullmatch(s.name()))
            else:
                cb.FilterSysts(lambda s: s.bin() == category and s.process() in selected)
                cb.FilterProcs(lambda p: p.bin() == category and p.process() in selected)
            logger.info(f"Pruning {category}: {step} of {len(selected)} signal processes ({100 * cumulated / total:.2f}% of the signal)")
    return pruned


def _smallest_processes(rates: dict, total: float, fraction: float, budget: float) -> tuple:
    """The processes below fraction of total, smallest first, while their sum stays within budget of total, and that sum."""
    selected, cumulated = [], 0.0
    for process in sorted(rates, key=rates.get):
        if rates[process] >= fraction * total or cumulated + rates[process] > budget * total:
            break
        selected.append(process)
        cumulated += rates[process]
    return selected, cumulated


def prune_backgrounds(cb: ch.CombineHarvester, fraction: float = 0.001, budget: float = 0.005) -> dict:
    """Drops per category the backgrounds below fraction of the category's background, smallest first, until budget of it
    (step 2 of the STXS pruning applied to the backgrounds). Returns what was pruned."""
    pruned = {}
    for category in sorted(cb.bin_set()):
        backgrounds = cb.cp().bin([category]).backgrounds()
        rates = {p: backgrounds.cp().process([p]).GetRate() for p in backgrounds.process_set()}
        total = sum(rates.values())
        selected, cumulated = _smallest_processes(rates, total, fraction, budget) if total > 0 else ([], 0.0)
        if not selected:
            continue
        cb.FilterSysts(lambda s: s.bin() == category and s.process() in selected)
        cb.FilterProcs(lambda p: p.bin() == category and p.process() in selected)
        pruned[category] = {"processes": selected, "background_fraction": cumulated / total}
        logger.info(f"Pruning {category}: {selected} ({100 * cumulated / total:.3f}% of the background)")
    return pruned


def smooth_noisy_bins(cb: ch.CombineHarvester, max_stat: float = 0.5, significance: float = 2.0) -> dict:
    """In the bins where the nominal template of a process has a relative MC uncertainty above max_stat, its shape systematics
    take the nominal bin content scaled by their overall normalisation effect, unless their deviation from it is above
    significance times the nominal MC uncertainty. Returns the number of replaced bins per systematic."""
    nominal = {}
    cb.ForEachProc(lambda p: nominal.__setitem__((p.bin(), p.process()), p.shape()))
    replaced = {}

    def smooth(s):
        hist = nominal.get((s.bin(), s.process()))
        if s.type() != "shape" or not hist or not s.shape_u() or _THEORY_NUISANCE.fullmatch(s.name()):
            return
        noisy = [i for i in range(1, hist.GetNbinsX() + 1)
                 if hist.GetBinContent(i) > 0.0 and hist.GetBinError(i) > max_stat * hist.GetBinContent(i)]
        for shifted in (s.shape_u(), s.shape_d()):
            # shapes are unit-normalised with the normalisation in value_u/value_d: the scaled nominal is the nominal itself
            bins = [i for i in noisy if abs(shifted.GetBinContent(i) - hist.GetBinContent(i)) < significance * hist.GetBinError(i)]
            for i in bins:
                shifted.SetBinContent(i, hist.GetBinContent(i))
                shifted.SetBinError(i, hist.GetBinError(i))
            if bins and shifted.Integral() > 0.0:
                shifted.Scale(1.0 / shifted.Integral())
                replaced[s.name()] = replaced.get(s.name(), 0) + len(bins)

    cb.ForEachSyst(smooth)
    logger.info(f"Smoothing: {sum(replaced.values())} noisy bins of {len(replaced)} shape systematics set to the scaled nominal")
    return replaced


def symmetrize_shapes(cb: ch.CombineHarvester, pattern: str) -> dict:
    """Shape systematics matching pattern take per bin the symmetric shifts nominal +- (up - down) / 2, which removes the
    one-sided (same direction) part of the up/down templates. Returns the number of symmetrised processes per systematic."""
    nominal = {}
    cb.ForEachProc(lambda p: nominal.__setitem__((p.bin(), p.process()), p.shape()))
    regex, done = re.compile(pattern), {}

    def symmetrize(s):
        hist = nominal.get((s.bin(), s.process()))
        if s.type() != "shape" or not hist or not s.shape_u() or not regex.fullmatch(s.name()):
            return
        up, down = s.shape_u(), s.shape_d()
        # unit-normalised templates: the absolute shifts relative to the nominal are value * shape
        half = [(s.value_u() * up.GetBinContent(i) - s.value_d() * down.GetBinContent(i)) / 2.0 for i in range(1, hist.GetNbinsX() + 1)]
        for shifted, sign in ((up, 1.0), (down, -1.0)):
            for i, delta in enumerate(half, start=1):
                shifted.SetBinContent(i, max(hist.GetBinContent(i) + sign * delta, 0.0))
        if up.Integral() <= 0.0 or down.Integral() <= 0.0:
            return
        s.set_value_u(up.Integral())
        s.set_value_d(down.Integral())
        up.Scale(1.0 / up.Integral())
        down.Scale(1.0 / down.Integral())
        done[s.name()] = done.get(s.name(), 0) + 1

    cb.ForEachSyst(symmetrize)
    logger.info(f"Symmetrisation: {sum(done.values())} templates of {len(done)} shape systematics")
    return done


def prune_systematics(cb: ch.CombineHarvester, fraction: float = 0.01) -> dict:
    """Drops the experimental shape systematics of a process in a category if neither shift moves any bin by more than fraction
    of the bin's expected uncertainty (Poisson of the total yield and MC statistics). Returns the number pruned per systematic."""
    nominal, uncertainty = {}, {}
    cb.ForEachProc(lambda p: nominal.__setitem__((p.bin(), p.process()), (p.shape(), p.rate())))
    for category in cb.bin_set():
        total = cb.cp().bin([category]).GetShape()
        uncertainty[category] = [math.sqrt(max(total.GetBinContent(i), 0.0) + total.GetBinError(i) ** 2)
                                 for i in range(1, total.GetNbinsX() + 1)]
    pruned = {}

    def negligible(s):
        hist, rate = nominal.get((s.bin(), s.process()), (None, 0.0))
        if s.type() != "shape" or not hist or not s.shape_u() or _THEORY_NUISANCE.fullmatch(s.name()):
            return False
        effects = (abs(value * shifted.GetBinContent(i) - hist.GetBinContent(i)) * rate
                   for value, shifted in ((s.value_u(), s.shape_u()), (s.value_d(), s.shape_d()))
                   for i in range(1, hist.GetNbinsX() + 1))
        if all(effect <= fraction * u for effect, u in zip(effects, uncertainty[s.bin()] * 2)):
            pruned[s.name()] = pruned.get(s.name(), 0) + 1
            return True
        return False

    cb.FilterSysts(negligible)
    logger.info(f"Pruning: {sum(pruned.values())} negligible shape systematics of {len(pruned)} nuisances removed")
    return pruned


def rename_nuisances(cb: ch.CombineHarvester) -> None:
    """Renames the nuisances of shapes made from older CROWN ntuples to their datacard names (common.analysis.legacy_nuisance_name)."""
    for name in sorted(cb.syst_name_set()):
        new_name = legacy_nuisance_name(name)
        if new_name != name:
            cb.RenameSystematic(cb, name, new_name)


def replace_with_asimov(cb: ch.CombineHarvester) -> None:
    logger.info("Replacing observation with Asimov dataset...")

    def is_empty_shape(hist) -> bool:
        return not hist or (hist.GetNbinsX() == 1 and hist.Integral() == 0.0)

    for category in cb.cp().bin_set():
        category_bin = cb.cp().bin([category])
        bkg_shape = category_bin.cp().backgrounds().GetShape()
        sig_shape = category_bin.cp().signals().GetShape()
        has_bkg = not is_empty_shape(bkg_shape)
        has_sig = not is_empty_shape(sig_shape)

        if not has_bkg and not has_sig:
            logger.warning(f"No signal and no background available in bin {category}")
            continue

        template = bkg_shape if has_bkg else sig_shape
        asimov_shape = template.Clone()
        asimov_shape.SetDirectory(0)
        asimov_shape.Reset("ICES")

        if has_bkg:
            asimov_shape.Add(bkg_shape)
        else:
            logger.warning(f"No background available in bin {category}")

        if has_sig:
            asimov_shape.Add(sig_shape)
        else:
            logger.warning(f"No signal available in bin {category}")

        category_bin.ForEachObs(lambda obs: obs.set_shape(asimov_shape.Clone(), True))


def apply_nn_rebinning(
    cb: ch.CombineHarvester,
    strategy: Literal["total_bkg", "per_process", "total_bkg__per_process"] = "total_bkg",
    threshold: float = 10.0,
    secondary_threshold: Optional[float] = 1.0,
    custom_binnings: Optional[Dict[str, List[float]]] = None,
) -> None:
    # Merges from left (0 -> peak) and right (1 -> peak) until conditions are met.

    custom_binnings = custom_binnings or {}
    for category in cb.cp().bin_set():
        if category in custom_binnings:
            logger.info(f"Overruling category {category} with dedicated custom binning: {custom_binnings[category]}")
            cb.cp().bin([category]).VariableRebin(custom_binnings[category])
            continue

        category_bin, bkg_shapes = cb.cp().bin([category]), []

        if strategy == "total_bkg":
            bkg_shapes.append(category_bin.cp().backgrounds().GetShape())

            def is_valid(yields):
                return yields[0] >= threshold

        elif strategy == "per_process":
            for p_name in category_bin.cp().backgrounds().process_set():
                bkg_shapes.append(category_bin.cp().process([p_name]).GetShape())

            def is_valid(yields):
                has_relevant = False
                for y, shape in zip(yields, bkg_shapes):
                    if shape.Integral() >= threshold:
                        has_relevant = True
                        if y < threshold:
                            return False
                return has_relevant

        elif strategy == "total_bkg__per_process":
            if secondary_threshold is None:
                raise ValueError("secondary_threshold required for 'total_bkg__per_process'")
            for p_name in category_bin.cp().backgrounds().process_set():
                shape = category_bin.cp().process([p_name]).GetShape()
                if shape.Integral() >= secondary_threshold:
                    bkg_shapes.append(shape)

            def is_valid(yields):
                if not bkg_shapes:  # no relevant process
                    return False
                if sum(yields) < threshold:
                    return False
                for y in yields:
                    if y < secondary_threshold:
                        return False
                return True

        else:
            raise ValueError(f"Unknown rebinning strategy: {strategy}")

        if not bkg_shapes or not bkg_shapes[0]:
            continue

        ref_shape = bkg_shapes[0]
        nbins = ref_shape.GetNbinsX()
        peak_bin = category_bin.backgrounds().GetShape().GetMaximumBin()
        peak_bin = max(1, min(peak_bin, nbins))  # Protect boundaries

        edges = set()
        edges.add(ref_shape.GetBinLowEdge(1))  # Absolute min (0.0)
        edges.add(ref_shape.GetBinLowEdge(nbins + 1))  # Absolute max (1.0)

        current_yields = [0.0] * len(bkg_shapes)  # 0.0 (1) to peak (peak_bin - 1)
        for i in range(1, peak_bin):
            for j, shape in enumerate(bkg_shapes):
                current_yields[j] += shape.GetBinContent(i)

            if is_valid(current_yields):
                edges.add(ref_shape.GetBinLowEdge(i + 1))
                current_yields = [0.0] * len(bkg_shapes)  # Reset yields for next bin

        current_yields = [0.0] * len(bkg_shapes)  # 1.0 (nbins) to peak (peak_bin + 1)
        for i in range(nbins, peak_bin, -1):
            for j, shape in enumerate(bkg_shapes):
                current_yields[j] += shape.GetBinContent(i)

            if is_valid(current_yields):
                edges.add(ref_shape.GetBinLowEdge(i))
                current_yields = [0.0] * len(bkg_shapes)  # Reset yields for next bin

        final_edges = sorted(list(edges))
        cb.cp().bin([category]).VariableRebin(final_edges)  # leftovers absorbed by the peak since no internal edge was placed
