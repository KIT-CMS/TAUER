import logging
import re
from copy import deepcopy
from typing import Callable, Iterable, List, Tuple, Union

import yaml
from src.helper import Iterate, Keys, find_variable_expansions, modify_tau_iso_string

try:
    from config.logging_setup_configs import setup_logging
except ModuleNotFoundError:
    import sys
    sys.path.extend([".", ".."])
    from config.logging_setup_configs import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def remove_keys(obj: Iterable, keys_to_remove: Union[Callable, ]):
    """
    Recursively remove specified keys from nested dicts/lists.

    Args:
        obj (Iterable): nested object
        keys_to_remove (Union[Callable, Iterable]): keys or condition marked for removal
    Returns:
        Cleaned object
    """
    match = keys_to_remove if callable(keys_to_remove) else lambda k: k in set(keys_to_remove)

    if isinstance(obj, dict):
        return {k: remove_keys(v, match) for k, v in obj.items() if not match(k)}
    elif isinstance(obj, list):
        return [remove_keys(item, match) for item in obj]
    else:
        return obj


class MissingCutOrWeight(Exception):
    """Exception raised when a cut or weight is missing in the configuration."""
    pass


class _GeneralConfigManipulation(object):
    """
    Collection of general configuration manipulation methods.
    """
    @staticmethod
    def set_common(config: dict) -> dict:
        """
        Sets the common key for all subprocesses in the configuration.

        Args:
            config (dict): The configuration dictionary to modify.

        Returns:
            dict: The modified configuration dictionary with common keys set.
        """
        config = deepcopy(config)
        for channel, era, process, *_ in Iterate.subprocesses(deepcopy(config)):
            config[channel][era][process].setdefault(Keys.COMMON, {})
            logger.info(f"Setting {Keys.COMMON} key for {channel} {era} {process}")
        return config

    @staticmethod
    def remove_variation_pattern(
        config: dict,
        ff_pattern: str = "anti_iso_CMS_",
        ignore_process: str = "data",
    ) -> dict:
        """
        Removes variations matching a specific pattern from the configuration in all subprocesses,
        except for a specified process.

        Args:
            config (dict): The configuration dictionary to modify.
            ff_pattern (str): The pattern to match for removal.
            ignore_process (str): The process to ignore during removal.

        Returns:
            dict: The modified configuration dictionary with specified variations removed.
        """
        config = deepcopy(config)
        for channel, channel_dict in config.items():
            if channel not in Keys.CHANNELS or not isinstance(channel_dict, dict):
                continue
            for era_dict in channel_dict.values():
                if not isinstance(era_dict, dict):
                    continue
                for process, process_dict in era_dict.items():
                    if process == ignore_process or not isinstance(process_dict, dict):
                        continue
                    for subprocess, subprocess_dict in process_dict.items():
                        if not isinstance(subprocess_dict, dict):
                            continue
                        for key in [key for key in subprocess_dict if ff_pattern in key]:
                            logger.info(f"Removing {key} from {subprocess}")
                            del subprocess_dict[key]
        return config

    @staticmethod
    def _should_remove(key: str, collection: list) -> bool:
        """
        Helper function to determine if a key should be removed based on a collection of keys.

        Args:
            key (str): The key to check.
            collection (list): The collection of keys to check against.

        Returns:
            bool: True if the key should be removed, False otherwise.
        """
        return collection and (key in collection or any(item in key for item in collection))

    @staticmethod
    def _recursive_remove(x: dict, /, level: int, level_keys: list[str], criteria: dict) -> None:
        """
        Helper function to recursively remove keys from a dictionary based on criteria.

        Args:
            x (dict): The dictionary to modify.
            level (int): The current level in the recursion.
            level_keys (list[str]): The list of keys for each level.
            criteria (dict): The criteria for removal at each level.
        """
        if level >= len(level_keys):
            return None

        current_level = level_keys[level]
        for key in list(x.keys()):
            if _GeneralConfigManipulation._should_remove(key, criteria.get(current_level, [])):
                logger.info(f"Removing {key} from {current_level}")
                del x[key]
            else:
                if isinstance(x[key], dict):
                    _GeneralConfigManipulation._recursive_remove(x[key], level + 1, level_keys, criteria)

    @staticmethod
    def remove_from_config(
        config: dict,
        channels: list[str] = None,
        eras: list[str] = None,
        processes: list[str] = None,
        subprocesses: list[str] = None,
        shifts: list[str] = None,
    ) -> dict:
        """
        Removes specified channels, eras, processes, subprocesses, and shifts from the configuration.

        Args:
            config (dict): The configuration dictionary to modify.
            channels (list[str]): List of channels to remove.
            eras (list[str]): List of eras to remove.
            processes (list[str]): List of processes to remove.
            subprocesses (list[str]): List of subprocesses to remove.
            shifts (list[str]): List of shifts to remove.

        Returns:
            dict: The modified configuration dictionary with specified elements removed.
        """
        config = deepcopy(config)
        levels = ["channel", "era", "process", "subprocess", "shift"]
        removal = {
            "channel": channels or [],
            "era": eras or [],
            "process": processes or [],
            "subprocess": subprocesses or [],
            "shift": shifts or [],
        }
        _GeneralConfigManipulation._recursive_remove(config, 0, levels, removal)
        return config

    @staticmethod
    def rename(
        config: dict,
        processes: dict = None,
        subprocesses: dict = None,
        shifts: dict = None,
    ) -> dict:
        """
        Renames processes, subprocesses, and shifts in the configuration.

        Args:
            config (dict): The configuration dictionary to modify.
            processes (dict): Dictionary mapping old process names to new names.
            subprocesses (dict): Dictionary mapping old subprocess names to new names.
            shifts (dict): Dictionary mapping old shift names to new names.

        Returns:
            dict: The modified configuration dictionary with specified elements renamed.
        """
        config = deepcopy(config)
        processes = processes or {}
        subprocesses = subprocesses or {}
        shifts = shifts or {}

        logger.info(
            f"""
            Renaming processes: {processes}
            Renaming subprocesses: {subprocesses}
            Renaming shifts: {shifts}
            """
        )

        for channel, channel_dict in config.items():
            if channel not in Keys.CHANNELS or not isinstance(channel_dict, dict):
                continue
            for era, era_dict in channel_dict.items():
                if not isinstance(era_dict, dict):
                    continue
                new_era = {}
                for process, process_dict in era_dict.items():
                    new_process = processes.get(process, process)
                    if not isinstance(process_dict, dict):
                        new_era[new_process] = process_dict
                        continue
                    new_processes = {}
                    for subprocess, subprocess_dict in process_dict.items():
                        new_subprocesses = subprocesses.get(subprocess, subprocess)
                        if isinstance(subprocess_dict, dict):
                            new_shifts = {
                                shifts.get(shift, shift): shift_dict
                                for shift, shift_dict in subprocess_dict.items()
                            }
                            new_processes[new_subprocesses] = new_shifts
                        else:
                            new_processes[new_subprocesses] = subprocess_dict
                    new_era[new_process] = new_processes
                channel_dict[era] = new_era
        return config

    @staticmethod
    def recursive_update(x: dict, y: dict, /) -> dict:
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
                    _GeneralConfigManipulation.recursive_update(x[k], v)
                else:
                    x[k] = v
            else:
                x[k] = v
        return x

    @staticmethod
    def recursive_update_from_file(
        config: dict,
        path: Union[str, List[str]],
    ) -> dict:
        """
        Recursively updates a configuration dictionary with values from a YAML file or files.
        If the path is a string, it is treated as a single file. If it is a list, each file in the list
        is processed in order. See `recursive_update` for details on how the update is performed.

        Args:
            config (dict): The configuration dictionary to update.
            path (Union[str, List[str]]): The path to the YAML file or list of paths to YAML files.

        Returns:
            dict: The updated configuration dictionary.
        """
        path = [path] if isinstance(path, str) else path
        config = deepcopy(config)
        for p in path:
            with open(p, "r") as f:
                config = _GeneralConfigManipulation.recursive_update(config, yaml.safe_load(f))
            logger.info(f"Updated config from {p}")
        return config

    @staticmethod
    def add_era_and_process_name_flags(config):
        """
        Adds flags for each era and process name to the configuration.

        Args:
            config (dict): The configuration dictionary to modify.

        Returns:
            dict: The modified configuration dictionary with era and process name flags added.
        """
        config = deepcopy(config)

        process_subprocesses = set([(p, subp) for _, _, p, subp, *_ in Iterate.subprocesses(config)])

        for channel, era, process, subprocess, *_ in Iterate.subprocesses(config):
            for _era in Keys.ERAS:
                logger.info(f"Adding is_{_era} flag for {channel} {era} {process}")
                config[channel][era][process][Keys.COMMON][f"is_{_era}"] = f"(float){int(_era == era)}."

        for channel, era, process, subprocess, *_ in Iterate.subprocesses(config):
            for _process, _subprocess in process_subprocesses:
                flag = int(_process == process and _subprocess == subprocess)
                key = f"is_{_process}__{_subprocess.replace('-', '_')}"
                config[channel][era][process][subprocess][key] = f"(float){flag}."
                logger.info(f"Adding {key} flag for {channel} {era} {process}")

        return config


class _SpecificConfigManipulation(object):
    """
    Collection of specific configuration manipulation methods, to be applied after the general ones.
    """
    @staticmethod
    def convert_weights_and_cuts_to_common(config: dict) -> dict:
        """
        Collect all weights and cuts from subprocesses and move them to the process-wise section
        of the configuration under a key following the pattern __{Keys.COMMON}__{Keys.CUT}__{index}__
        or __{Keys.COMMON}__{Keys.WEIGHT}__{index}__. The cuts and weights in the process-wise section
        are then replaced with the new keys.

        Args:
            config (dict): The configuration dictionary to modify.

        Returns:
            dict: The modified configuration dictionary with common weights and cuts added.
        """
        config = deepcopy(config)

        for channel, era, process, _, subprocess_dict in Iterate.subprocesses(config):
            config[channel][era][process].setdefault(Keys.COMMON, {})
            config[channel][era][process][Keys.COMMON].setdefault(Keys.CUT, {})
            config[channel][era][process][Keys.COMMON].setdefault(Keys.WEIGHT, {})

            try:
                common_cuts_rev = dict(map(reversed, config[channel][era][process][Keys.COMMON][Keys.CUT].items()))
            except KeyError:
                common_cuts_rev = {}
            try:
                common_weights_rev = dict(map(reversed, config[channel][era][process][Keys.COMMON][Keys.WEIGHT].items()))
            except KeyError:
                common_weights_rev = {}

            for shift, shift_dict in subprocess_dict.items():
                if not isinstance(shift_dict, dict):
                    continue

                if shift_dict.get(Keys.CUT) is None or shift_dict.get(Keys.WEIGHT) is None:
                    raise MissingCutOrWeight(f"Missing cut or weight for {shift} in {subprocess_dict}, aborting.")

                def set_common(x, /, key):
                    if x is not None:
                        _rev = (
                            common_cuts_rev
                            if key in {Keys.CUT, Keys.ANTI_ISO_CUT}
                            else common_weights_rev
                        )
                        _key = Keys.CUT if key in {Keys.CUT, Keys.ANTI_ISO_CUT} else Keys.WEIGHT
                        if x in _rev:
                            shift_dict[key] = _rev[x]
                        else:
                            new = f"__{Keys.COMMON}__{_key}__{len(_rev)}__"
                            config[channel][era][process][Keys.COMMON][_key][new] = x
                            _rev[x] = new
                            shift_dict[key] = new

                set_common(shift_dict.get(Keys.CUT), key=Keys.CUT)
                set_common(shift_dict.get(Keys.WEIGHT), key=Keys.WEIGHT)
                set_common(shift_dict.get(Keys.ANTI_ISO_CUT), key=Keys.ANTI_ISO_CUT)
                set_common(shift_dict.get(Keys.ANTI_ISO_WEIGHT), key=Keys.ANTI_ISO_WEIGHT)

            logger.info(f"Added common cuts and weights for {channel} {era} {process}")
        return config

    @staticmethod
    def add_set_of_training_variables(
        config: dict,
        training_variables: list[str],
    ) -> dict:
        """
        Adds a set of training variables to the configuration for each subprocess

        """
        config = deepcopy(config)

        default_variables = {k: k for k in training_variables}

        for channel, era, process, subprocess, subprocess_dict in Iterate.subprocesses(deepcopy(config)):
            if isinstance(subprocess_dict, dict):
                config[channel][era][process].setdefault(Keys.COMMON, {})
                config[channel][era][process].setdefault(Keys.VARIABLES, deepcopy(default_variables))
                config[channel][era][process].setdefault(Keys.NOMINAL_VARIABLES, deepcopy(default_variables))

            for shift_name, shift_dict in subprocess_dict.items():
                if not isinstance(shift_dict, dict):
                    continue

                if (cut := shift_dict.get(Keys.CUT)) is None or (weight := shift_dict.get(Keys.WEIGHT)) is None:
                    raise MissingCutOrWeight(f"Missing cut or weight for {shift_dict}, aborting.")
                if f"__{Keys.COMMON}__{Keys.CUT}__" in str(cut):
                    if (cut := config[channel][era][process][Keys.COMMON][Keys.CUT].get(cut)) is None:
                        raise MissingCutOrWeight(f"Missing common cut for {shift_dict}, aborting.")
                if f"__{Keys.COMMON}__{Keys.WEIGHT}__" in str(weight):
                    if (weight := config[channel][era][process][Keys.COMMON][Keys.WEIGHT].get(weight)) is None:
                        raise MissingCutOrWeight(f"Missing common weight for {shift_dict}, aborting.")

                combined, variables_dict = f"{cut} && {weight}", {}
                for variable in training_variables:
                    if len((matches := list(set(find_variable_expansions(combined, variable))))) > 1:
                        raise AssertionError(f"{variable} appears multiple times in under different names ({matches}) aborting.")
                    variables_dict[variable] = matches[0] if matches else variable

                for variable in shift_dict.get("var", []):
                    basename, *shift = variable.split("__")
                    if shift:
                        variables_dict[basename] = variable

                if variables_dict == default_variables:
                    config[channel][era][process][subprocess][shift_name][Keys.VARIABLES] = f"__{Keys.NOMINAL_VARIABLES}__"
                else:
                    config[channel][era][process][subprocess][shift_name][Keys.VARIABLES] = variables_dict
                    config[channel][era][process][Keys.VARIABLES].update({v: v for v in variables_dict.values()})
            logger.info(f"Added training variables for {channel} {era} {process}")
        return config

    @staticmethod
    def nest_and_categorize_uncertainties(config: dict) -> dict:
        """
        Nest and categorize uncertainties in the configuration under the key 'uncertainties'.
        The uncertainties are categorized into 'up' and 'down' shifts based on their names.
        The uncertainties are then stored in the configuration. If the input vaariables
        in a shift differ from the nominal ones, the uncertainty type is set to 'shift-like'
        and the shifted variables are stored in the 'variables' key. If the input variables
        are the same as the nominal ones, the uncertainty type is set to 'weight-like'.

        Args:
            config (dict): The configuration dictionary to modify.

        Returns:
            dict: The modified configuration dictionary with uncertainties categorized and nested.
        """
        config = deepcopy(config)
        pattern = re.compile(r"^(.*?)(Up|Down)(?:_.*)?$")

        for *info, subprocess_dict in Iterate.subprocesses(config):
            subprocess_dict.setdefault(Keys.UNCERTAINTIES, {})
            uncertainty_group, shifts_to_remove = {}, []
            for shift in list(subprocess_dict.keys()):
                if not (m := pattern.match(shift)):
                    continue
                base_name, direction = m.groups()
                shifts_to_remove.append(shift)
                group = uncertainty_group.setdefault(base_name, {})
                shift_data = deepcopy(subprocess_dict[shift])
                group[direction.lower()] = shift_data

            for key in shifts_to_remove:
                del subprocess_dict[key]

            if uncertainty_group:
                for base_name, group in uncertainty_group.items():
                    if group[Keys.UP].get(Keys.VARIABLES) == group[Keys.DOWN].get(Keys.VARIABLES):
                        group[Keys.VARIABLES] = group[Keys.UP].get(Keys.VARIABLES)
                        del group[Keys.UP][Keys.VARIABLES]
                        del group[Keys.DOWN][Keys.VARIABLES]
                        group[Keys.UNCERTAINTY_TYPE] = Keys.WEIGHT_LIKE
                    else:
                        group[Keys.UNCERTAINTY_TYPE] = Keys.SHIFT_LIKE
                sorted_uncertainty_group = {k: v for k, v in sorted(uncertainty_group.items(), key=lambda item: item[0])}
                subprocess_dict[Keys.UNCERTAINTIES] = sorted_uncertainty_group
            logger.info(f"Categorized uncertainties for {' '.join(info)}")
        return config

    @staticmethod
    def add_anti_iso_cut_and_weight_version(
        config: dict,
        cut_tight_wp: str = "Medium",
        cut_loose_wp: str = "VVVLoose",
        fake_factor_string: str = "fake_factor_2",
        ignore_fake_factor_string_for_processes: Tuple[str, ...] = ("ggH", "qqH"),
        ignore_anti_iso_string_for_processes: Tuple[str, ...] = tuple(),
    ) -> dict:
        """
        Adds a new version of the cut and weight for anti-isolation to the configuration.
        The new cut and weight are based on the original ones, but modified to use the anti-isolation
        criteria and adding the additional fake factor weight. The new cut and weight
        are stored under the keys `Keys.ANTI_ISO_CUT` and `Keys.ANTI_ISO_WEIGHT`, respectively.

        Works only with semi-leptonic channels so far.

        Args:
            config (dict): The configuration dictionary to modify.
            cut_tight_wp (str): The tight working point for the cut.
            cut_loose_wp (str): The very loose working point for the cut.
            fake_factor_string (str): The string representing the fake factor weight.

        Returns:
            dict: The modified configuration dictionary with the new cut version added.
        """
        for channel, era, process, subprocess, subprocess_dict in Iterate.subprocesses(config):
            for shift, shift_dict in subprocess_dict.items():
                if not isinstance(shift_dict, dict):
                    continue

                if process not in ignore_anti_iso_string_for_processes:
                    shift_dict[Keys.ANTI_ISO_CUT] = modify_tau_iso_string(
                        shift_dict[Keys.CUT],
                        tight_wp=cut_tight_wp,
                        loose_wp=cut_loose_wp,
                    )
                else:
                    shift_dict[Keys.ANTI_ISO_CUT] = shift_dict[Keys.CUT]

                if process not in ignore_fake_factor_string_for_processes:
                    shift_dict[Keys.ANTI_ISO_WEIGHT] = (
                        shift_dict[Keys.WEIGHT]
                        if fake_factor_string in shift_dict[Keys.WEIGHT]
                        else f"{shift_dict[Keys.WEIGHT]}*({fake_factor_string})"
                    )
                else:
                    shift_dict[Keys.ANTI_ISO_WEIGHT] = shift_dict[Keys.WEIGHT]

                changed_cut = shift_dict[Keys.ANTI_ISO_CUT] != shift_dict[Keys.CUT]
                changed_weight = shift_dict[Keys.ANTI_ISO_WEIGHT] != shift_dict[Keys.WEIGHT]

                msg = f"{channel} {era} {process} {subprocess}\n"
                msg += f"\t\t{shift}:\n"
                msg += f"\t\t\tAnti-iso cut set ({'adjusted' if changed_cut else 'already existed'})\n"
                msg += f"\t\t\tAnti-iso weight set ({'adjusted' if changed_weight else 'already existed'})\n"

                logger.info(msg)

        return config


class ConfigModification(object):
    """
    Class to handle configuration modifications.
    """
    general = _GeneralConfigManipulation
    specific = _SpecificConfigManipulation
