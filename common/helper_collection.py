import json
import logging
import multiprocessing as mp
import os
import pathlib
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from itertools import product
from typing import Any, Dict, Iterable, Tuple, Union

import numpy as np
import pandas as pd
import uproot
import yaml
from tqdm import tqdm

from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


class ObjBuildingDict(ABC, dict):
    """
    Dictionary subclass that builds objects on demand from key and value.

    Extends the built‐in dict with the ability to “build” (or convert) a stored
    value into an object of a predefined type.
    Upon accessing an item via __getitem__, if the stored value is already an
    instance of the expected object type (specified during initialization via
    the 'obj' parameter), then that instance is returned as is. Otherwise, the
    abstract method build_obj(key, value) is called for a transformation.

    Subclasses must implement:
        build_obj(key: str, value: Any) -> object:
            Converts the raw value stored under key to a proper instance of the
            expected object type.

    Parameters
    ----------
    *args : any
        Positional arguments passed to the parent dict initializer.
    obj : object or None, optional
        Object used for the transformation. If provided, __getitem__ will check
        whether the stored value is an instance of this type, if not, build_obj
        will be invoked.
    **kwargs : dict
        Keyword arguments passed to the parent dict initializer.
    """

    def __init__(
        self,
        *args: Any,
        obj: Union[object, None] = None,
        **kwargs: Dict[str, Any],
    ):
        super().__init__(*args, **kwargs)
        self.obj = obj

    @abstractmethod
    def build_obj(self, key: str, value: Any) -> object:
        """
        Build and return the object corresponding to the given key.

        Parameters
        ----------
        key : str
            The dictionary key.
        value : Any
            The original value stored in the dictionary; typically not yet in
            the desired object form.

        Returns
        -------
        object
            The constructed object.
        """
        raise NotImplementedError

    def __getitem__(self, key: Any) -> Any:
        """
        Extends the built-in __getitem__ method to return the stored object
        if it is already an instance of the expected type, or build it using
        build_obj() otherwise.

        Parameters
        ----------
        key : str
            The key to look up.

        Returns
        -------
        object
            The stored object if it is already built, or the result of build_obj().
        """
        if self.obj is None:
            return super().__getitem__(key)
        try:
            obj = super().__getitem__(key)
            if isinstance(obj, self.obj):
                return obj
            return self.build_obj(key, obj)
        except KeyError:
            raise KeyError(f"Key {key} not found in the dictionary")


class NestedDefaultDict(defaultdict):
    """
    A nested defaultdict that allows for easy creation of
    multi-level dictionaries with default values.
    This class is a subclass of defaultdict and is used to
    create a nested dictionary structure where each level
    is also a defaultdict.
    """
    def __init__(self, *args, **kwargs) -> None:
        super(NestedDefaultDict, self).__init__(NestedDefaultDict, *args, **kwargs)

    def __repr__(self) -> str:
        return repr(dict(self))

    @property
    def regular(self) -> dict:
        """
        Convert the defaultdict to a regular dictionary, useful i.e. when saving as yaml
        """
        def convert(d):
            if isinstance(d, defaultdict):
                d = {k: convert(v) for k, v in d.items()}
            return d
        return convert(self)


def recursive_dict_update(x: dict, y: dict, /) -> dict:
    """
    Recursively updates a dictionary (first argument) with another dictionary (second argument).
    If a key exists in both dictionaries and the value is a dictionary, it will recursively update
    that key's value. Otherwise, it will overwrite the value in the first dictionary with the value
    from the second dictionary.

    Args:
        x (dict): The dictionary to update.
        y (dict): The dictionary with values to update the first dictionary with.

    Returns:
        dict: The updated dictionary.
    """
    for k, v in y.items():
        if k in x:
            if isinstance(x[k], dict) and isinstance(v, dict):
                recursive_dict_update(x[k], v)
            else:
                x[k] = v
        else:
            x[k] = v
    return x


class PreserveROOTPathsAsStrings(yaml.Dumper):
    """
    Custom YAML dumper that preserves ROOT paths as strings.
    This is necessary, since paths containing "root://" are not
    automatically converted to strings by PyYAML and raise errors upon loading.

    usage:
        yaml.dump(data, Dumper=PreserveROOTPathsAsStrings)

    """

    def represent_data(self, data):
        """
        Override the represent_data method to handle ROOT paths.
        """
        if isinstance(data, str) and data.startswith("root://"):
            return self.represent_scalar('tag:yaml.org,2002:str', data, style="'")

        return super(PreserveROOTPathsAsStrings, self).represent_data(data)


# requiered to be defined globally
def pandas_df_from_root(args: Tuple[str, Iterable, str]) -> pd.DataFrame:
    """
    Helper function to read a ROOT file and return a pandas DataFrame.

    Parameters
    ----------
    args : Tuple[str, Iterable, str]
        A tuple containing the file path, a list of branches to read, and the tree name

    Returns
    -------
    pd.DataFrame
        A pandas DataFrame containing the specified branches from the ROOT file.
    """
    file, branches, tree = args
    with uproot.open(file) as f:
        return f[tree].arrays(branches, library="pd")


def calculate_stxs_N_and_negative_fractions(
    database_path: str = "../TauFakeFactors/datasets/nanoAOD_v12",
    output_path: str = "./config/shapes/stxs_bin_split_info.yaml",
    stage: str = "1p2",
    granularity: str = "coarse",
    specific_process: Union[None, Iterable[str]] = ("ggh_htautau", "vbf_htautau"),
    specific_era: Union[None, Iterable[str]] = ("2022preEE", "2022postEE",
                                                "2023preBPix", "2023postBPix", "2024", "2025"),
    n_workers: int = 20,
) -> dict:
    """
    Create a YAML file with the number of events, negative fractions, and xsec fractions
    for each STXS bin in the given database path.

    Parameters
    ----------
    database_path : str
        Path to the database containing the json files with 'filelist' key.
    output_path : str
        Path where the output YAML file will be saved.
    stage: str
        The STXS stage to use, e.g., "1p2".
    granularity: str
        The granularity of the STXS bins, e.g., "coarse" or "fine".
    specific_process: Union[None, Iterable[str]]
        If provided, only processes matching these names will be processed.
    specific_era: Union[None, Iterable[str]]
        If provided, only eras matching these names will be processed.
    n_workers: int
        Number of worker processes to use for parallel processing.

    Returns
    -------
    dict
        A dictionary containing the number of events, negative fractions, and xsec fractions
        for each STXS bin, organized by process and era.
    """

    logger.info("Calculating STXS N_events, negative fractions, xsec_fraction per bin...")

    ERAS = ["2016preVFP", "2016postVFP", "2017", "2018", 
        "2022preEE", "2022postEE", "2023preBPix", "2023postBPix", "2024", "2025"]
    BINS = {
        "ggh_htautau": {
            "1p2": {
                "coarse": list(range(100, 117)),
                "fine": list(range(100, 127)),
            },
        },
        "vbf_htautau": {
            "1p2": {
                "coarse": list(range(200, 211)),
                "fine": list(range(200, 225)),
            },
        },
    }
    KEYS = {
        "weight": "genWeight",
        "cat": {
            "1p2": {
                "coarse": "HTXS_stage1_2_cat_pTjet30GeV",
                "fine": "HTXS_stage1_2_fine_cat_pTjet30GeV",
            },
        }
    }
    logger.info(f"Using database path: {database_path}")
    logger.info(f"Available Bins: {BINS}\nAvailable Eras: {ERAS}\nAvailable Keys: {KEYS}")
    logger.info(f"Adjusting to stage: {stage}, granularity: {granularity}")
    logger.info(f"Specific processes: {specific_process}, Specific eras: {specific_era}")

    def should_process_bin(bin_to_check: int, filename: str) -> bool:
        """
        Helper function to determine if a bin should be processed based on the filename.
        The files have small contaminations of other bins, so we need to check
        if the bin_to_check is within the range specified in the filename. If not
        checked a mismatch between negative fractions and N_events can occur.
        """
        if (range_match := re.compile(r"_Bin(\d+)to(\d+)_").search(filename)):
            return int(range_match.group(1)) <= bin_to_check <= int(range_match.group(2))

        if (single_match := re.compile(r"_Bin(\d+)_").search(filename)):
            return bin_to_check == int(single_match.group(1))

        return True  # file is inclusive otherwise

    def should_keep_process_and_era(item: Tuple[str, str]) -> bool:
        process, era = item
        keep_process = (specific_process is None) or (process in specific_process)
        keep_era = (specific_era is None) or (era in specific_era)
        return keep_process and keep_era

    N_events, negative_fractions, xsec_fractions = NestedDefaultDict(), NestedDefaultDict(), NestedDefaultDict()

    # prepopulate N_events and negative_fractions with empty containers
    for process, era in filter(should_keep_process_and_era, product(BINS.keys(), ERAS)):
        for b in BINS[process][stage][granularity]:
            N_events[process][era][b] = []
            negative_fractions[process][era][b] = []

    for process, era in filter(should_keep_process_and_era, product(BINS.keys(), ERAS)):
        for file in (pathlib.Path(database_path) / era / process).glob("*.json"):
            with open(file=file) as f:
                files = json.load(f)["filelist"]

            with mp.Pool(processes=n_workers) as pool:
                results_iterator = pool.imap_unordered(
                    pandas_df_from_root,
                    [
                        (
                            file,
                            [KEYS["weight"]] + [KEYS["cat"][stage][granularity]],
                            "Events",
                        )
                        for file in files
                    ],
                )
                df = pd.concat(
                    list(
                        tqdm(
                            results_iterator,
                            total=len(files),
                            desc=f"Processing files of {file.name} ",
                        )
                    ),
                    ignore_index=True
                )

            for b in BINS[process][stage][granularity]:
                _df = df[df[KEYS["cat"][stage][granularity]] == b]

                if not _df.empty and should_process_bin(b, file.name):
                    n_events = _df.shape[0]
                    positive = np.count_nonzero(_df[KEYS["weight"]] >= 0)
                    negative = np.count_nonzero(_df[KEYS["weight"]] < 0)
                    frac = 1.0 - 2.0 * (negative / (negative + positive))
                    if "_Bin" not in file.name:  # is inclusive
                        N_events[process][era][b].insert(0, n_events)
                        negative_fractions[process][era][b].insert(0, frac)
                        xsec_fractions[process][era][b] = (
                            _df[KEYS["weight"]].sum() / df[KEYS["weight"]].sum()
                        ).item()
                    else:
                        N_events[process][era][b].append(n_events)
                        negative_fractions[process][era][b].append(frac)

    info = NestedDefaultDict(
        {
            "ggh_htautau": {"xsec_inclusive": 48.58 * 0.06272},  # N3LO * BR(tau tau)
            "vbf_htautau": {"xsec_inclusive": 3.779 * 0.06272},  # NNLO * BR(tau tau)
        }
    )
    for process, era in filter(should_keep_process_and_era, product(BINS.keys(), ERAS)):
        info[process][era] = {
            "xsec_fractions": xsec_fractions[process][era].regular,
            "N_events": N_events[process][era].regular,
            "negative_fractions": negative_fractions[process][era].regular,
        }

    info = info.regular
    if os.path.exists(output_path):
        logger.info(f"Output file {output_path} already exists, merging with existing data.")
        with open(output_path, "r") as f:
            if (existing_info := yaml.safe_load(f)):
                info = recursive_dict_update(existing_info, info)

    logger.info(f"Writing results to {output_path}")
    with open(output_path, "w") as f:
        yaml.dump(info, f, sort_keys=True)

    return info
