import argparse
import logging
import os
import gc
from functools import partial
from pathlib import Path
import pandas as pd
import yaml
from src.dataset_manipulation import (
    CombinedDataFrameManipulation,
    ProcessDataFrameManipulation,
    ROOTToPlain,
    exemplary_custom_selection,
    exemplary_remove_cut_regions,
    get_fold_conditions,
)
from src.helper import Iterate, Keys, PipeDict, downcast_dataframe
from tqdm import tqdm

try:
    from CustomLogging import setup_logging
except ModuleNotFoundError:
    import sys
    sys.path.extend([".", ".."])
    from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))

try:
    from common.analysis import get_training_variables as _get_training_vars
    _ANALYSIS_TRAINING_VARS: list[str] | None = _get_training_vars()
except (ImportError, ModuleNotFoundError):
    _ANALYSIS_TRAINING_VARS = None

try:
    import importlib
    from common.analysis import ACTIVE_ANALYSIS
    _analysis_training_labels = importlib.import_module(f"analyses.{ACTIVE_ANALYSIS}.trainings.training_labels")
except (ImportError, ModuleNotFoundError):
    _analysis_training_labels = None


def parse_args():
    parser = argparse.ArgumentParser(description="Create training datasets")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to the config file",
    )
    parser.add_argument(
        "--base-dataset-dir",
        type=str,
        default=f"/ceph/{os.environ['USER']}/tauer_training/training_datasets",
        help="Base directory for the output files",
    )
    parser.add_argument(
        "--common-setup-config",
        type=str,
        default="",
        help="Path to the common setup config file",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        default=False,
        help="Force recreation of existing datasets and folds (default: skip if they exist)",
    )
    return parser.parse_args()


def filepath(directory: str, basename: str = "", extension: str = "feather"):
    path = (Path(args.base_dataset_dir) / Path(directory))
    path.mkdir(parents=True, exist_ok=True)
    return path.joinpath(f"{basename}.{extension}") if basename else path


def is_nonempty_root_file(filepath, tree_name="ntuple"):
    """Check if a ROOT file is non-empty using ROOT.TFile (supports root:// XRootD URLs)."""
    import ROOT
    try:
        f = ROOT.TFile.Open(filepath)
        if not f or f.IsZombie():
            return False
        tree = f.Get(tree_name)
        result = tree and tree.GetEntries() > 0
        f.Close()
        return result
    except Exception:
        return False


def _stxs_bin_flag_value(flag_name, current_flag):
    if _analysis_training_labels is not None and hasattr(_analysis_training_labels, "flag_value"):
        return _analysis_training_labels.flag_value(flag_name, current_flag)
    return "(int)1" if flag_name == current_flag else "(int)0"


def collect_filtered_plain_dataframes(
    config: dict,
    channel: str,
    era: str,
    process: str,
    subprocess: str,
    subprocess_dict: dict,
    common_setup_config: dict = None,
) -> tuple:
    """
    TODO: Update docstring
    Function to collect filtered plain dataframes. It creates raw and filtered dataframes
    and stores them if not present applying basic filter, collecting any cuts.

    Args:
        arguments (Tuple[dict, str, str, str, str, dict]): A tuple containing the config,
            config: dict: The config dictionary.
            channel: str: The channel name.
            era: str: The era name.
            process: str: The process name.
            subprocess: str: The subprocess name.
            subprocess_dict: dict: The subprocess dictionary.

    Returns:
        dict: A dictionary containing the filtered plain dataframes.
    """
    def any_cut(df):
        pattern = "__common__cut__"
        return df[[it for it in df.columns if it.startswith(pattern)]].any(axis=1)

    all_filepaths = list(Iterate.rdf_files(config[channel][era][process][Keys.PATHS]))
    nonempty_filepaths = [tpl for tpl in all_filepaths if is_nonempty_root_file(tpl[1], tpl[0])]
    logger.debug(f"{channel}/{era}/{process}/{subprocess}: {len(all_filepaths)} total files, {len(nonempty_filepaths)} non-empty")
    common_dict = config[channel][era][process].get(Keys.COMMON, {})
    if not common_dict:
        logger.debug(f"No '{Keys.COMMON}' key found for {channel}/{era}/{process}, using empty definitions")
    definitions_tuples = list(Iterate.common_dict(common_dict))
    subprocess_flag_tuples = [it for it in subprocess_dict.items() if it[0].startswith("is_")]

    # Auto-generate is_{process}__{subprocess} flag definitions from renaming_map
    # when not already present in subprocess_dict (i.e. when 'common' config is missing)
    if common_setup_config:
        renaming_map = common_setup_config.recursive_get(
            ["dataset_modifications", "labels", "renaming_map"], {}
        )
        if renaming_map:
            current_flag = f"is_{process}__{subprocess.replace('-', '_')}"
            existing_flags = {t[0] for t in subprocess_flag_tuples}
            for flag_refs in renaming_map.values():
                if isinstance(flag_refs, str):
                    flag_refs = [flag_refs]
                for flag_name in flag_refs:
                    # Only auto-generate compound flags (is_X__Y), skip branch flags like is_data
                    if "__" in flag_name and flag_name not in existing_flags:
                        value = _stxs_bin_flag_value(flag_name, current_flag)
                        subprocess_flag_tuples.append((flag_name, value))
                        existing_flags.add(flag_name)
            logger.debug(f"Auto-generated {len(subprocess_flag_tuples)} flag definitions for {process}/{subprocess} (current_flag={current_flag})")

    # Get variables: prefer process config, then common.analysis, then setup.yaml
    variables_dict = config[channel][era][process].get(Keys.VARIABLES, {})
    if variables_dict:
        additional_columns = list(variables_dict.keys())
    elif _ANALYSIS_TRAINING_VARS:
        additional_columns = list(_ANALYSIS_TRAINING_VARS)
        logger.debug(f"Using training_variables from common.analysis: {len(additional_columns)} variables")
    elif common_setup_config and common_setup_config.recursive_get(["training_variables"]):
        additional_columns = common_setup_config.recursive_get(["training_variables"])
        logger.debug(f"Using training_variables from common_setup_config: {len(additional_columns)} variables")
    else:
        additional_columns = []
        logger.warning("No training variables found in config or common_setup_config")

    root_plain = ROOTToPlain(
        raw_path=filepath("raw", f"{channel}_{era}_{process}_{subprocess}"),
        filtered_path=filepath("filtered", f"{channel}_{era}_{process}_{subprocess}"),
    )
    # Remove existing cached feather files to force recreation if requested
    if args.recreate:
        for p in [root_plain.raw_path, root_plain.filtered_path]:
            if p is not None and p.exists():
                logger.debug(f"Removing existing {p} to force recreation")
                p.unlink()
    filtered_df = root_plain.setup_raw_dataframe(
        tree_and_filepaths=nonempty_filepaths,
        definitions=definitions_tuples + subprocess_flag_tuples,
        additional_columns=additional_columns + list(Keys.EVENT_IDENTIFIER_COLUMNS),
        filters=None,
        description=f"{channel}_{era}_{process}_{subprocess}",
        max_workers=16,
    ).filter_dataframe(
        filter_function=any_cut,
    )
    logger.debug(f"Filtered dataframe shape: {filtered_df._dataframe.shape if filtered_df._dataframe is not None else 'N/A'}")
    return (
        channel,
        era,
        process,
        subprocess,
        subprocess_dict,
        filtered_df,
    )


def create_process_folds(
    config: dict,
    channel: str,
    era: str,
    process: str,
    subprocess: str,
    subprocess_dict: dict,
    plain_subprocess_dataframe_obj: ROOTToPlain,
    common_setup_config: dict,
) -> None:
    """
    Function to collect folds for the training dataset. It creates a dataframe
    for each process and subprocess, applies the necessary manipulations, adding
    labels, event quantities, nominal variables, weights and cuts, and additional
    nominal cuts. It also handles uncertainties and splits the dataframe into folds.

    Args:
        arguments (Tuple[dict, str, str, str, str, dict, pd.DataFrame]): A tuple containing the config,
            config: dict: The config dictionary.
            channel: str: The channel name.
            era: str: The era name.
            process: str: The process name.
            subprocess: str: The subprocess name.
            subprocess_dict: dict: The subprocess dictionary.
            plain_subprocess_dataframe: pd.DataFrame: The plain subprocess dataframe.

    Returns:
        dict: A dictionary containing the folds for the training dataset.
    """

    fold_conditions = get_fold_conditions()
    filenames = {
        fold_name: filepath("_folds", f"__{fold_name}__{channel}_{era}_{process}_{subprocess}")
        for fold_name in fold_conditions.keys()
    }

    if not args.recreate and all(filename.exists() for filename in filenames.values()):
        logger.info(f"Folds for {channel} {era} {process} - {subprocess} already exist, skipping (use --recreate to overwrite).")
    else:
        add = ProcessDataFrameManipulation(
            config=config,
            subprocess_dict=subprocess_dict,
            subprocess_df=plain_subprocess_dataframe_obj.dataframe.reset_index(drop=True),
            process_name=process,
            subprocess_name=subprocess,
        )
        logger.info(f"Processing {process} - {subprocess}")
        process_df = (
            pd.DataFrame()
            .pipe(
                add.labels,
                renaming_map=common_setup_config.recursive_get(
                    ["dataset_modifications", "labels", "renaming_map"]
                )
            )
            .pipe(add.update_subprocess_df, by="index")
            .pipe(add.event_quantities, columns=list(Keys.EVENT_IDENTIFIER_COLUMNS))
            .pipe(add.nominal_variables)
            .pipe(add.nominal_weight_and_cut)
            .pipe(add.additional_nominal_cuts)
            .pipe(add.weight_like_uncertainties)
            .pipe(add.shift_like_uncertainties)
            .pipe(exemplary_remove_cut_regions, regions=("ss",))
        )

        if subprocess == "jetFakes":
            process_df = (
                process_df
                .pipe(add.adjust_jetFakes_weights)
            )

        process_df.columns = pd.MultiIndex.from_tuples(process_df.columns)

        process_df = (
            process_df
            .pipe(
                exemplary_custom_selection,
                selections=common_setup_config.recursive_get(
                    ["dataset_modifications", "selections"]
                )
            )
        )

        logger.debug(f"Shape of process_df for {channel}-{era}-{process}-{subprocess}: {process_df.shape}")

        msg = f"Creating folds for {channel} {era} {process} - {subprocess}"
        for fold_name, fold_condition in fold_conditions.items():
            df = CombinedDataFrameManipulation.split_folds(
                df=process_df,
                condition=fold_condition,
            )
            msg += f"\n\t{fold_name}: {df.shape}"
            df.to_feather(filenames[fold_name])
        logger.info(msg)

    try:
        del add
        gc.collect()
    except UnboundLocalError:
        pass


def combine_folds(
    class_weighted: bool = True,
    default_in_nominal_additional: float = 0.0,
) -> None:
    for fold_name in get_fold_conditions().keys():
        print(f"Start processing fold {fold_name}")

        fold_files = list(Path(filepath("_folds")).glob(f"__{fold_name}__*.feather"))
        if not fold_files:
            print(f"No .feather files found for fold {fold_name}, skipping.")
            continue

        fold = pd.concat(
            [
                downcast_dataframe(pd.read_feather(it)).reset_index(drop=True)
                for it in tqdm(
                    fold_files,
                    desc=f"Loading fold {fold_name} parts",
                )
            ]
        ).reset_index(drop=True)
        print(f"Combining fold {fold_name} to shape {fold.shape}")

        fold = (
            fold
            .pipe(
                CombinedDataFrameManipulation.add_class_weights,
                class_weighted=class_weighted,
            )
            .pipe(CombinedDataFrameManipulation.fill_nans_in_weight_like)
            .pipe(CombinedDataFrameManipulation.fill_nans_in_shift_like)
            .pipe(
                CombinedDataFrameManipulation.fill_nans_in_nominal_additional,
                default_value=default_in_nominal_additional,
            )
        )
        print(f"Final shape of fold {fold_name} is {fold.shape}")
        fold.to_feather(filepath("folds", f"{fold_name}"))
        print(f"Saved combined fold {fold_name} at {filepath('folds', f'{fold_name}')}")


if __name__ == "__main__":
    # Self-nice regardless of invocation method (run.py already wraps this in
    # `nice -n 19`, but this also covers direct invocation). Safe to call even
    # when already niced (os.nice() clamps at the max of 19).
    os.nice(19)

    args = parse_args()

    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    if args.common_setup_config:
        with open(args.common_setup_config, "r") as f:
            args.common_setup_config = yaml.safe_load(f)
            if not args.common_setup_config:
                logger.warning("No common setup config provided or it is empty, using default settings.")
                args.common_setup_config = {}
    else:
        args.common_setup_config = {}

    args.common_setup_config = PipeDict(args.common_setup_config)

    WEIGHT_AND_CUT_CONTAINING = {"ps_weight__FsrWeight", "ps_weight__IsrWeight"}
    Iterate.common_dict = partial(Iterate.common_dict, ignore_weight_and_cuts=WEIGHT_AND_CUT_CONTAINING)
    logger.warning(f"Ignoring cuts and weights of {WEIGHT_AND_CUT_CONTAINING}, until fixed!")

    for ch_key, ch_val in config.items():
        if not isinstance(ch_val, dict):
            continue
        if ch_key not in Keys.CHANNELS:
            logger.warning(f"Channel '{ch_key}' not in Keys.CHANNELS, will be skipped.")
        for era_key in ch_val.keys():
            if era_key not in Keys.ERAS:
                logger.warning(f"Era '{era_key}' (channel '{ch_key}') not in Keys.ERAS, will be skipped.")

    subprocess_list = list(Iterate.subprocesses(config))
    logger.debug(f"Iterate.subprocesses yielded {len(subprocess_list)} subprocess(es)")
    if not subprocess_list:
        logger.warning(
            "No subprocesses found -- no folds will be created. Most likely cause: era "
            "names in config don't match Keys.ERAS (add your era(s) to Keys.ERAS in "
            "src/helper.py)."
        )

    SUBPROCESSES_TO_SKIP = args.common_setup_config.recursive_get(["dataset_modifications", "subprocesses_to_skip"], set())
    logger.debug(f"SUBPROCESSES_TO_SKIP = {SUBPROCESSES_TO_SKIP}")

    subprocess_count = 0
    processing_pipeline = (
        collect_filtered_plain_dataframes(config, channel, era, process, subprocess, subprocess_dict, args.common_setup_config)
        for channel, era, process, subprocess, subprocess_dict in Iterate.subprocesses(config)
        if subprocess not in SUBPROCESSES_TO_SKIP
    )

    for items in processing_pipeline:
        subprocess_count += 1
        logger.debug(f"Processing tuple #{subprocess_count}: {[str(x) for x in items[:5]]}")
        create_process_folds(config, *items, args.common_setup_config)

        items[-1]._dataframe = None
        del items
        gc.collect()

    logger.info(f"Total subprocesses processed: {subprocess_count}")
    if subprocess_count == 0:
        logger.warning("No subprocesses were processed -- combine_folds will find nothing.")

    combine_folds()
