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
    from config.logging_setup_configs import setup_logging
except ModuleNotFoundError:
    import sys
    sys.path.extend([".", ".."])
    from config.logging_setup_configs import setup_logging

try:
    from config.analysis import get_training_variables as _get_training_vars
    _ANALYSIS_TRAINING_VARS: list[str] | None = _get_training_vars()
except (ImportError, ModuleNotFoundError):
    _ANALYSIS_TRAINING_VARS = None


def parse_args():
    parser = argparse.ArgumentParser(description="Create training datasets")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to the config file",
    )
    parser.add_argument(
        "--base-dataset-directory",
        type=str,
        default=f"/ceph/{os.environ['USER']}/smhtt_ul_new/training_datasets",
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
    path = (Path(args.base_dataset_directory) / Path(directory))
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


import re

# Regex to extract STXS bin numbers from flag names like
# is_ggH__ggH125_ggh_htautau_bin105_selection or
# is_qqH__qqH125_vbf_htautau_bin203_selection
_STXS_BIN_RE = re.compile(r"_bin(\d+)_selection$")


def _stxs_bin_flag_value(flag_name, current_flag):
    """Determine the RDF expression for an auto-generated label flag.

    For plain process flags (is_X__Y), returns (int)1 if it matches the
    current process/subprocess, else (int)0.

    For STXS bin selection flags (is_X__Y_..._binN_selection), returns an
    HTXS_stage1_2_cat_pTjet30GeV cut when the flag belongs to the current
    process/subprocess, else (int)0.
    """
    m = _STXS_BIN_RE.search(flag_name)
    if m is None:
        # Not a bin selection flag — simple process flag
        return "(int)1" if flag_name == current_flag else "(int)0"

    # It's a bin selection flag.  Check if it belongs to this process/subprocess
    # by verifying the flag name starts with the current_flag prefix.
    if not flag_name.startswith(current_flag + "_"):
        return "(int)0"

    bin_number = int(m.group(1))
    return f"(int)(HTXS_stage1_2_cat_pTjet30GeV == {bin_number})"


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
    print(f"[DEBUG] {channel}/{era}/{process}/{subprocess}: {len(all_filepaths)} total files, {len(nonempty_filepaths)} non-empty")
    common_dict = config[channel][era][process].get(Keys.COMMON, {})
    if not common_dict:
        print(f"[DEBUG] No '{Keys.COMMON}' key found for {channel}/{era}/{process}, using empty definitions")
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
            print(f"[DEBUG] Auto-generated {len(subprocess_flag_tuples)} flag definitions for {process}/{subprocess} (current_flag={current_flag})")

    # Get variables: prefer process config, then config.analysis, then setup.yaml
    variables_dict = config[channel][era][process].get(Keys.VARIABLES, {})
    if variables_dict:
        additional_columns = list(variables_dict.keys())
    elif _ANALYSIS_TRAINING_VARS:
        additional_columns = list(_ANALYSIS_TRAINING_VARS)
        print(f"[DEBUG] Using training_variables from config.analysis: {len(additional_columns)} variables")
    elif common_setup_config and common_setup_config.recursive_get(["training_variables"]):
        additional_columns = common_setup_config.recursive_get(["training_variables"])
        print(f"[DEBUG] Using training_variables from common_setup_config: {len(additional_columns)} variables")
    else:
        additional_columns = []
        print(f"[DEBUG] No variables found in config or common_setup_config")

    root_plain = ROOTToPlain(
        raw_path=filepath("raw", f"{channel}_{era}_{process}_{subprocess}"),
        filtered_path=filepath("filtered", f"{channel}_{era}_{process}_{subprocess}"),
    )
    # Remove existing cached feather files to force recreation if requested
    if args.recreate:
        for p in [root_plain.raw_path, root_plain.filtered_path]:
            if p is not None and p.exists():
                print(f"[DEBUG] Removing existing {p} to force recreation")
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
    print(f"[DEBUG] Filtered dataframe shape: {filtered_df._dataframe.shape if filtered_df._dataframe is not None else 'N/A'}")
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
        print(f"Folds for {channel} {era} {process} - {subprocess} already exist, skipping (use --recreate to overwrite).")
    else:
        add = ProcessDataFrameManipulation(
            config=config,
            subprocess_dict=subprocess_dict,
            subprocess_df=plain_subprocess_dataframe_obj.dataframe.reset_index(drop=True),
            process_name=process,
            subprocess_name=subprocess,
        )
        print(f"Processing {process} - {subprocess}")
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
            .pipe(exemplary_remove_cut_regions, regions=("same_sign", "same_sign_anti_iso"))
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

        # Debug: Print shape of process_df
        print(f"[DEBUG] Shape of process_df for {channel}-{era}-{process}-{subprocess}: {process_df.shape}")

        msg = f"Creating folds for {channel} {era} {process} - {subprocess}"
        for fold_name, fold_condition in fold_conditions.items():
            df = CombinedDataFrameManipulation.split_folds(
                df=process_df,
                condition=fold_condition,
            )
            # Debug: Print shape of each fold
            print(f"[DEBUG] Shape of fold '{fold_name}' for {channel}-{era}-{process}-{subprocess}: {df.shape}")
            msg += f"\n\t{fold_name}: {df.shape}"
            df.to_feather(filenames[fold_name])
        print(msg)

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

    logger = setup_logging(logger=logging.getLogger(__name__))
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
    print(f"Ignoring cuts and weights of {WEIGHT_AND_CUT_CONTAINING}, until fixed!")

    # ─── DEBUG: Show config structure vs Keys expectations ───
    print(f"[DEBUG] Config top-level keys (channels): {list(config.keys())}")
    print(f"[DEBUG] Keys.CHANNELS = {Keys.CHANNELS}")
    print(f"[DEBUG] Keys.ERAS = {Keys.ERAS}")
    for ch_key, ch_val in config.items():
        if isinstance(ch_val, dict):
            era_keys = list(ch_val.keys())
            print(f"[DEBUG] Channel '{ch_key}' -> era keys: {era_keys}")
            if ch_key not in Keys.CHANNELS:
                print(f"[DEBUG]   WARNING: channel '{ch_key}' NOT in Keys.CHANNELS, will be skipped!")
            for era_key in era_keys:
                if era_key not in Keys.ERAS:
                    print(f"[DEBUG]   WARNING: era '{era_key}' NOT in Keys.ERAS, will be skipped!")
                else:
                    print(f"[DEBUG]   era '{era_key}' OK")

    # ─── DEBUG: Count subprocesses from Iterate ───
    subprocess_list = list(Iterate.subprocesses(config))
    print(f"[DEBUG] Iterate.subprocesses yielded {len(subprocess_list)} subprocess(es)")
    if subprocess_list:
        for ch, er, pr, sp, _ in subprocess_list[:10]:
            print(f"[DEBUG]   subprocess: {ch}/{er}/{pr}/{sp}")
        if len(subprocess_list) > 10:
            print(f"[DEBUG]   ... and {len(subprocess_list) - 10} more")
    else:
        print(f"[DEBUG]   --> No subprocesses found! This means no folds will be created.")
        print(f"[DEBUG]   --> Most likely cause: era names in config don't match Keys.ERAS.")
        print(f"[DEBUG]   --> Fix: add your era(s) to Keys.ERAS in src/helper.py")
    # ─── END DEBUG ───

    SUBPROCESSES_TO_SKIP = args.common_setup_config.recursive_get(["dataset_modifications", "subprocesses_to_skip"], set())
    print(f"[DEBUG] SUBPROCESSES_TO_SKIP = {SUBPROCESSES_TO_SKIP}")

    subprocess_count = 0
    processing_pipeline = (
        collect_filtered_plain_dataframes(config, channel, era, process, subprocess, subprocess_dict, args.common_setup_config)
        for channel, era, process, subprocess, subprocess_dict in Iterate.subprocesses(config)
        if subprocess not in SUBPROCESSES_TO_SKIP
    )

    for items in processing_pipeline:
        subprocess_count += 1
        # Debug: Print tuple info for each subprocess
        print(f"[DEBUG] Processing tuple #{subprocess_count}: {[str(x) for x in items[:5]]}")
        create_process_folds(config, *items, args.common_setup_config)

        items[-1]._dataframe = None
        del items
        gc.collect()

    print(f"[DEBUG] Total subprocesses processed: {subprocess_count}")
    if subprocess_count == 0:
        print(f"[DEBUG] No subprocesses were processed — combine_folds will find nothing.")

    combine_folds()
