"""
Category (bin) definitions for datacard construction.

Relocated from SMRun2Legacy's ``python/categories.py`` (``run3_htt`` branch) --
see STATUS.md ("## Phase 2d") for the relocation record.

Import-path change vs. the original: SMRun2Legacy pulled the DNN class mapping
from an *external* smhtt_ul checkout via the ``SMHTT_UL_PATH`` env var, because
SMRun2Legacy and smhtt_ul were separate repos. TauKITFlow merges what used to be
smhtt_ul's role into itself, so ``stxs_stage0_run3`` now imports directly from
``shapes.selection.category_selection`` -- no external path / env var needed.

KNOWN GAP (documented, not silently papered over -- see STATUS.md "## Phase 2d"
and "## Blockers"): ``shapes/selection/category_selection.py`` does not yet define
a ``DNN_CLASS_MAPPING`` with per-category ``index``/``is_signal`` metadata the
way smhtt_ul's did; it only has a single-channel (``mt``) ``category_mapping``
without an ``is_signal`` flag. The ``stxs_stage0_run3`` categorization path
below will raise a clear ``NotImplementedError`` until that config is extended.
The ``gof`` and ``stxs_stage0`` paths do not depend on this and are fully
functional today -- that's what Phase 2d's build/run validation exercises.
"""
import logging
from itertools import count

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def _get_dnn_class_mapping() -> dict:
    """
    Import DNN_CLASS_MAPPING from TauKITFlow's own central shapes config.

    Raises NotImplementedError with an explicit pointer to the gap (see module
    docstring) if shapes/selection/category_selection.py hasn't been extended
    with a DNN_CLASS_MAPPING (index + is_signal per category) yet.
    """
    try:
        from shapes.selection.category_selection import DNN_CLASS_MAPPING
    except ImportError as exc:
        raise NotImplementedError(
            "stxs_stage0_run3 categorization requires "
            "shapes.selection.category_selection.DNN_CLASS_MAPPING (per-channel dict "
            "of {category_name: {'index': int, 'is_signal': bool}}), which does not "
            "exist yet -- shapes/selection/category_selection.py currently only has a "
            "single-channel 'category_mapping' without an 'is_signal' flag. "
            "See STATUS.md Phase 2d / Blockers. Use --categories gof or "
            "stxs_stage0 in the meantime."
        ) from exc
    return DNN_CLASS_MAPPING


def get_categories(
    channel: str,
    categorization: str,
    gof_category_name: str = "gof",
    embedding: bool = True,
    jetfakes: bool = True,
) -> list:
    logger.debug(f"Calling get_categories with {locals()}")

    counter = count(10)  # Start category IDs from 11
    background_categories = []

    if categorization == "gof":
        categories = [(300, gof_category_name)]
        logger.info(f"Using GOF categorization with category: {categories[0]}")
        return categories

    # stxs_stage0_run3: pure DNN categorization for Run3 -- DNN score bins serve
    # as both signal and control regions.  embedding / jetfakes flags are irrelevant.
    if categorization == "stxs_stage0_run3":
        dnn_class_mapping = _get_dnn_class_mapping()
        if channel not in dnn_class_mapping:
            raise NotImplementedError(f"stxs_stage0_run3 not defined for channel '{channel}'")
        mapping = dnn_class_mapping[channel]
        signal_dnn = [
            (info["index"] + 1, f"{channel}_{name}")
            for name, info in sorted(mapping.items(), key=lambda x: x[1]["index"])
            if info["is_signal"]
        ]
        bkg_dnn = [
            (info["index"] + 1, f"{channel}_{name}")
            for name, info in sorted(mapping.items(), key=lambda x: x[1]["index"])
            if not info["is_signal"]
        ]
        logger.info(f"Using stxs_stage0_run3: signal={signal_dnn}, background={bkg_dnn}")
        return signal_dnn + bkg_dnn

    # stxs_stage1p2_run3: placeholder for Run3 STXS stage 1.2 categorization
    if categorization == "stxs_stage1p2_run3":
        raise NotImplementedError("stxs_stage1p2_run3 is not yet implemented.")

    # All Run2 categorizations below use embedding / jetFakes control regions
    if embedding:
        background_categories.append((next(counter), f"{channel}_embedding"))
        logger.info(f"Added {background_categories[-1]}")
    else:
        logger.info(f"Skipping embedding category for channel {channel} (non-embedding mode)")

    if jetfakes:
        background_categories.append((next(counter), f"{channel}_jetFakes"))
        logger.info(f"Added {background_categories[-1]}")
    else:
        logger.info(f"Skipping jetFakes category for channel {channel}")

    if channel == "mt":
        background_categories.extend(
            [
                (next(counter), f"{channel}_ttbar"),
                (next(counter), f"{channel}_dyjets"),
                (next(counter), f"{channel}_diboson"),
            ],
        )
        logger.info(f"Added mt-specific background categories: {background_categories[-3:]}")
    elif channel == "et":
        background_categories.extend(
            [
                (next(counter), f"{channel}_ttbar"),
                (next(counter), f"{channel}_dyjets"),
                (next(counter), f"{channel}_diboson"),
                (next(counter), f"{channel}_wjets"),
            ],
        )
        logger.info(f"Added et-specific background categories: {background_categories[-4:]}")
    elif channel == "tt":
        background_categories.extend(
            [
                (next(counter), f"{channel}_ttbar"),
                (next(counter), f"{channel}_dyjets"),
            ],
        )
        logger.info(f"Added tt-specific background categories: {background_categories[-2:]}")
    else:
        raise NotImplementedError(f"Channel-specific background categories for {channel} not implemented.")

    if categorization == "stxs_stage0":
        signal_categories = [(1, f"{channel}_qqh"), (2, f"{channel}_ggh")]
        logger.info(f"Using stxs_stage0 with signal categories: {signal_categories}")
        return signal_categories + background_categories

    elif categorization == "stxs_stage1p2_run2":
        signal_categories = [
            (100, f"{channel}_qqh_bin201to210"),
            (101, f"{channel}_ggh_bin101to104"),
            (102, f"{channel}_ggh_bin105to106"),
            (103, f"{channel}_ggh_bin107to109"),
            (104, f"{channel}_ggh_bin110to116"),
        ]
        logger.info(f"Using stxs_stage1p2_run2 with signal categories: {signal_categories}")
        return signal_categories + background_categories

    elif categorization == "stxs_stage1p2_run2_bkg_only":
        logger.info(f"Using stxs_stage1p2_run2_bkg_only: {background_categories}")
        return background_categories

    else:
        raise ValueError(f"Unknown categorization: {categorization}")
