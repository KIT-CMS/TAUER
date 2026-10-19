import concurrent.futures
import logging
import re
from typing import Any, Callable, Generator, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from tqdm import tqdm

try:
    from CustomLogging import setup_logging
except ModuleNotFoundError:
    import sys
    sys.path.extend([".", "..", "../.."])
    from CustomLogging import setup_logging


logger = setup_logging(logger=logging.getLogger(__name__))

# Training variable list: prefer common/variables.yaml (output_features + flags),
# fall back to the hardcoded list if the config module is not on sys.path.
_TRAINING_VARIABLES_FALLBACK = [
    "pt_1",
    "pt_2",
    "eta_1",
    "eta_2",
    "jpt_1",
    "jpt_2",
    "jeta_1",
    "jeta_2",
    "m_fastmtt",
    "m_vis",
    "mjj",
    "pt_vis",
    "pt_dijet",
    "pt_tt",
    "pt_ttjj",
    "njets",
    "nbtag",
    "met",
    "deltaEta_ditaupair",
    "deltaR_ditaupair",
    "mt_2",
    "pt_fastmtt",
    "mt_tot",
    "pzetamissvis",
    "deltaR_jj",
    "deltaEta_jj",
    "deltaR_12j1",
    "deltaR_2j1",
    "deltaR_1j2",
    "deltaEta_1j1",
    "deltaEta_1j2",
    "deltaEta_2j1",
    "deltaEta_2j2",
    "deltaEta_12j1",
    "deltaEta_12j2",
    "deltaR_12j2",
    "deltaR_1j1",
    "deltaR_2j2",
    # -- label flags ---
    "is_data",
    "is_dyjets",
    "is_dy_zl",
    "is_embedding",
    "is_ggh_htautau",
    "is_ttbar",
    "is_vbf_htautau",
    "is_wjets",
    # --- era flags ---
    "is_2026",
    "is_2025",
    "is_2024",
    "is_2023postBPix",
    "is_2023preBPix",
    "is_2022postEE",
    "is_2022preEE",
    "is_2018",
    "is_2017",
    "is_2016preVFP",
    "is_2016postVFP",
    # ---
]

try:
    from common.analysis import get_training_variables as _get_training_variables
    TRAINING_VARIABLES = _get_training_variables()
except (ImportError, ModuleNotFoundError):
    TRAINING_VARIABLES = _TRAINING_VARIABLES_FALLBACK


def downcast_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    fcols = df.select_dtypes('float64').columns
    icols = df.select_dtypes('int64').columns

    df[fcols] = df[fcols].astype(np.float32)
    df[icols] = df[icols].astype(np.int32)

    return df


class Keys:
    """
    Collection of keys used in the configuration files and for columns in training dataframes.
    To be adjusted according to the actual analysis if needed.
    """
    ERAS = {"2016preVFP", "2016postVFP", "2017", "2018", "2022preEE", "2022postEE", "2023preBPix", "2023postBPix", "2024", "2025", "2026"}
    CHANNELS = {"mt", "et", "tt"}

    COMMON = "common"
    NOMINAL_VARIABLES = "nominal_variables"
    UNCERTAINTIES = "uncertainties"
    UNCERTAINTY_TYPE = "uncertainty_type"
    PATHS = "paths"

    EVENT = "Event"
    LABELS = "Labels"
    NOMINAL = "Nominal"
    WEIGHT_LIKE = "WeightLike"
    SHIFT_LIKE = "ShiftLike"

    VARIABLES = "variables"
    WEIGHT = "weight"
    CLASS_WEIGHT = "class_weight"
    CUT = "cut"
    UP = "up"
    DOWN = "down"

    ANTI_ISO = "anti_iso"
    ANTI_ISO_CUT = "anti_iso_cut"
    ANTI_ISO_WEIGHT = "anti_iso_weight"

    ID = "id"
    EVENT_IDENTIFIER_COLUMNS = ["event"]


def find_variable_expansions(full_expression: str, substring: str) -> list[str]:
    """
    Helper to find all occurrences of a substring in a full expression.

    Args:
        full_expression (str): The full expression to search in.
        substring (str): The substring to find.

    Returns:
        list[str]: A list of all occurrences of the substring in the full expression.
    """
    pattern = re.compile(r'\b' + re.escape(substring) + r'(?:__[A-Za-z0-9_]+)?\b')
    return pattern.findall(full_expression)


def modify_tau_iso_string(input_str: str, tight_wp: str = "Tight", loose_wp: str = "VLoose") -> str:
    """
    Modifies a string containing tau isolation conditions.

    1. Replaces (id_tau_vsJet_Tight_2>0.5) or (id_tau_vsJet_Tight_2==1)
       with (id_tau_vsJet_Tight_2<0.5&&id_tau_vsJet_VLoose_2>0.5).
    2. Handles optional suffixes like __something, applying them to both new variables.
    3. If no such pattern is found, appends the anti-iso variant.
    4. If an anti-iso variant already exists (with or without suffix), does nothing.
    5. Tight and VLoose working points are configurable.
    6. The _2 suffix is always present.
    """

    escaped_tight_wp = re.escape(tight_wp)
    escaped_loose_wp = re.escape(loose_wp)

    anti_iso_exists_pattern = re.compile(
        rf"\((?:id_tau_vsJet_{escaped_tight_wp}_2((?:__[a-zA-Z0-9_]+)?)\s*<\s*0\.5)\s*&&\s*(?:id_tau_vsJet_{escaped_loose_wp}_2\1\s*>\s*0\.5)\)"
    )
    if anti_iso_exists_pattern.search(input_str):
        return input_str  # Do nothing if already in anti-iso form

    pattern_to_replace_str = \
        rf"\(id_tau_vsJet_{escaped_tight_wp}_2((?:__[a-zA-Z0-9_]+)?)\s*(?:>0\.5|==1)\)"
    pattern_to_replace = re.compile(pattern_to_replace_str)

    def replacer(match):
        opt_suffix = match.group(1) if match.group(1) else ""  # Get the captured suffix or empty string
        return f"(id_tau_vsJet_{tight_wp}_2{opt_suffix}<0.5&&id_tau_vsJet_{loose_wp}_2{opt_suffix}>0.5)"

    modified_str, num_subs = pattern_to_replace.subn(replacer, input_str)

    if num_subs == 0:
        append_str = f"(id_tau_vsJet_{tight_wp}_2<0.5&&id_tau_vsJet_{loose_wp}_2>0.5)"

        if not input_str:  # If original string is empty
            return append_str
        else:
            return f"{input_str} && {append_str}"
    else:
        return modified_str


class RuntimeVariables(object):
    """
    A singleton-like container class holding variables that can be adjusted at runtime.

    Attributes:
        USE_MULTIPROCESSING (bool): Flag to enable or disable multiprocessing globally
    """
    USE_MULTIPROCESSING = True

    def __new__(cls) -> "RuntimeVariables":
        if not hasattr(cls, "instance"):
            cls.instance = super(RuntimeVariables, cls).__new__(cls)
            return cls.instance


def optional_process_pool(
    args_list: List[Tuple[Any, ...]],
    function: Callable,
    max_workers: Union[int, None] = None,
    description: Union[str, None] = None,
) -> List[Any]:
    """
    Running a function with a list of arguments in parallel using multiprocessing if
    the list of arguments is longer than one and multiprocessing is enabled.

    Args:
        args_list: List of tuples with arguments for the function
        function: Function to be executed
        max_workers: Number of workers to be used in the multiprocessing pool (default: None)

    Return:
        List of results of the function

    """

    if len(args_list) == 1 or not RuntimeVariables.USE_MULTIPROCESSING:
        results = [function(args) for args in args_list]
    else:
        n = max_workers if max_workers is not None else len(args_list)
        with concurrent.futures.ProcessPoolExecutor(max_workers=n) as executor:
            results = list(
                tqdm(
                    executor.map(function, args_list),
                    total=len(args_list),
                    desc=description,
                )
            )

    return results


class Iterate:
    """
    Collection of usefull iterators to iterate over the configuration files.
    """
    @staticmethod
    def subprocesses(
        config: dict,
    ) -> Generator[tuple[str, str, str, str, dict], None, None]:
        """
        Iterates over all subprocess in the configuration file, ignoring
        the keys "paths", "common", "variables", and "nominal_variables" and label flags.

        Args:
            config (dict): The configuration dictionary to iterate over.

        Yields:
            tuple: A tuple containing the channel, era, process, subprocess, and the corresponding dictionary.
        """
        skip_subprocesses = {"paths", "common", "variables", "nominal_variables"}
        for channel, channel_dict in config.items():
            if channel not in Keys.CHANNELS or not isinstance(channel_dict, dict):
                print(f"[DEBUG Iterate.subprocesses] Skipping channel '{channel}' (not in Keys.CHANNELS={Keys.CHANNELS} or not a dict)")
                continue
            for era, era_dict in channel_dict.items():
                if era not in Keys.ERAS or not isinstance(era_dict, dict):
                    print(f"[DEBUG Iterate.subprocesses] Skipping era '{era}' in channel '{channel}' (not in Keys.ERAS={Keys.ERAS} or not a dict)")
                    continue
                for process, process_dict in era_dict.items():
                    if not isinstance(process_dict, dict):
                        continue
                    for subprocess, subprocess_dict in process_dict.items():
                        flagname = f"is_{process}__{subprocess.replace('-', '_')}"
                        if isinstance(subprocess_dict, dict) and subprocess not in skip_subprocesses and subprocess != flagname:
                            yield channel, era, process, subprocess, subprocess_dict

    @staticmethod
    def process(config: dict) -> Generator[tuple[str, str, str, dict], None, None]:
        """
        Iterates over all processes in the configuration file.

        Args:
            config (dict): The configuration dictionary to iterate over.
        """
        for channel, channel_dict in config.items():
            for era, era_dict in channel_dict.items():
                for sample, sample_dict in era_dict.items():
                    yield channel, era, sample, sample_dict

    @staticmethod
    def common_dict(
        common_process_dict: dict,
        ignore_weight_and_cuts: Optional[set[str]] = None,
    ):
        """
        Iterates over a process specific "common" dictionary.

        Args:
            common_process_dict (dict): The common dictionary to iterate over.
            ignore_weight_and_cuts (set[str], optional): A set of strings that, if found in the dictionary values, will trigger a skip of the item.

        Yields:
            tuple: A tuple containing the name and value of each item in the dictionary.
        """
        for name, value in common_process_dict.items():
            if isinstance(value, dict):
                for sub_name, sub_value in value.items():
                    if ignore_weight_and_cuts and any(
                        it in sub_value for it in ignore_weight_and_cuts
                    ):
                        continue
                    yield sub_name, sub_value
            else:
                yield name, value

    @staticmethod
    def friends(x: dict[str, dict[int, str]], /) -> Generator:
        """
        Iterates over all keys in a dictionary that start with "friends_".

        Args:
            x (dict): The dictionary to iterate over.

        Yields:
            Generator: A generator yielding the values of the keys that start with "friends_".
        """
        yield from (v for k, v in x.items() if k.startswith("friends_"))

    @staticmethod
    def rdf_files(paths_dict: dict, tree_name: str = "ntuple") -> Generator:
        """
        Iterates over all tree_name files and corresponding firend files in agiven paths_dict.
        The tree_name is the name of the tree in the ROOT file.
        Assumes that tree_name and friends_ have the same (key, value) structure for all
        (tree_name, *firends_) files.

        Args:
            paths_dict (dict): The dictionary containing the paths to the files.
            tree_name (str): The name of the tree in the ROOT file. Defaults to "ntuple".

        Yields:
            Generator: A generator yielding tuples of the form (tree_name, ntuple, *friends).
        """
        for items in zip(
            Iterate.key_sorted_files(paths_dict[tree_name]),
            *(Iterate.key_sorted_files(it) for it in Iterate.friends(paths_dict))
        ):
            ntuple, *friends = items
            assert all(it.endswith(ntuple.split("/")[-1]) for it in friends)
            yield tree_name, ntuple, *friends

    @staticmethod
    def key_sorted_files(x: dict[int, str], /) -> Generator:
        """
        Iterates over a dictionary of files, sorted by their keys.
        The keys are assumed to be integers or floats.

        Args:
            x (dict): The dictionary containing the files to be iterated over.

        Yields:
            Generator: A generator yielding the files sorted by their keys.
        """

        for _, file in sorted(x.items(), key=lambda item: item[0]):
            yield file


class PipeDict(dict):
    """
    Helper class to allow for method chaining on dictionaries like pandas.pipe does.
    """
    def pipe(self, func: callable, *args: Any, **kwargs: Any) -> dict:
        return func(self, *args, **kwargs)

    def conditional_pipe(self, condition: bool, func: callable, *args: Any, **kwargs: Any) -> dict:
        if condition:
            return self.pipe(func, *args, **kwargs)
        return self

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self:
            logger.warning(f"Key '{key}' not found in the dictionary. Returning default value: {default}")
        return super().get(key, default)

    def recursive_get(self, keys: List[str], default: Any = None) -> Any:
        current = self
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                logger.warning(f"Key path '{' -> '.join(keys)}' not found. Returning default value: {default}")
                return default
            current = current[key]
        return current


def get_class_weights(
    weights: Union[pd.Series, np.ndarray],
    Y: Union[pd.Series, np.ndarray],
    classes: tuple = (0, 1),
    class_weighted: bool = True,
) -> Union[pd.Series, np.ndarray]:
    _weights = np.zeros_like(weights)
    for _class in classes:
        _weights[Y == _class] = weights.sum() / weights[Y == _class].sum()
    return _weights * (weights if class_weighted else 1.0)
