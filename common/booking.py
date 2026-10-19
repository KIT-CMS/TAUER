import hashlib
import logging
import re
import sys
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, List, Tuple, Union

import yaml
from ntuple_processor import RunManager

import shapes.naming as naming

from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


class ObjBuildingDict(ABC, dict):
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
        raise NotImplementedError

    def __getitem__(self, key: Any) -> Any:
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
    def __init__(self, *args, **kwargs) -> None:
        super(NestedDefaultDict, self).__init__(NestedDefaultDict, *args, **kwargs)

    def __repr__(self) -> str:
        return repr(dict(self))

    @property
    def regular(self) -> dict:
        def convert(d):
            if isinstance(d, defaultdict):
                d = {k: convert(v) for k, v in d.items()}
            return d
        return convert(self)


def recursive_dict_update(x: dict, y: dict, /) -> dict:
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
    def represent_data(self, data):
        if isinstance(data, str) and data.startswith("root://"):
            return self.represent_scalar('tag:yaml.org,2002:str', data, style="'")

        return super(PreserveROOTPathsAsStrings, self).represent_data(data)


def stable_hash_key(key: str, num_bytes: int = 8) -> int:
    hasher = hashlib.sha1(key.encode('utf-8'))
    digest = hasher.digest()
    return int.from_bytes(digest[:num_bytes], byteorder=sys.byteorder, signed=False)


def unique_filename(item: Union[str, List[str]]) -> Union[str, List[str]]:
    *_, era, sample, channel, filename = item.split("/")
    return f"{era}__{sample}__{channel}__{filename}"


def generate_filepath_dict(
    paths: List[str],
    num_bytes: Union[int, None] = None,
) -> Tuple[int, dict]:

    allow_search = num_bytes is None
    num_bytes = 1 if num_bytes is None else num_bytes

    unique_filenames = [unique_filename(it) for it in paths]
    unique_keys = [stable_hash_key(it, num_bytes=num_bytes) for it in unique_filenames]
    if len(set(unique_keys)) == len(set(unique_filenames)):
        return {k: v for k, v in zip(unique_keys, paths)}, num_bytes
    else:
        if allow_search:
            return generate_filepath_dict(paths, num_bytes=num_bytes + 4)
        else:
            raise ValueError("Cannot find unique keys for paths")


def dataset_key(graph: object) -> str:
    return re.sub(r"\W", "_", graph.name)


def add_paths(
    graph: object,
    channel: str,
    era: str,
    r_manager: RunManager,
):
    ntuple_dict, num_hash_bytes = generate_filepath_dict([it.path for it in graph.unit_block.ntuples])
    r_manager.config[channel][era][dataset_key(graph)]["paths"]["ntuple"] = ntuple_dict

    for idx in range(len(graph.unit_block.ntuples[0].friends)):
        friend_files = [it.friends[idx].path for it in graph.unit_block.ntuples]

        friend_tag_match = re.search(r"CROWN(?:Multi)?Friends?/([^/]+)/", friend_files[0])
        friend_name = f"friends__{friend_tag_match.group(1) if friend_tag_match else friend_files[0]}"
        friend_dict, _ = generate_filepath_dict(friend_files, num_bytes=num_hash_bytes)

        a, b = ntuple_dict.keys(), friend_dict.keys()
        assert not a - b and not b - a, "Hash collision detected. This should not have happen."

        r_manager.config[channel][era][dataset_key(graph)]["paths"][friend_name] = friend_dict


def get_config_formatter(
    era: str,
    graph: object,
    processes: set,
    **kwargs,
):
    def _config_formatter(
        config: Union[dict, NestedDefaultDict],
        name: str,
        cut_expression: str,
        weight_expression: str,
        **kwargs,  # dont need more, see ntuple_processor/run/RunManager/__histo1d_from_hist for more details
    ) -> None:
        _, bin_, histogram = name.split("/")
        channel = bin_.split("_")[0]
        category, region = naming.split_bin(bin_, channel)
        assert (split := naming.split_histogram(histogram, processes)), f"Unknown process in {name}"
        process, shift = split

        config[channel][era][dataset_key(graph)][f"{process}_{category}" if category else process][
            "_".join(part for part in (region, shift) if part) or "Nominal"
        ] = NestedDefaultDict(
            cut=cut_expression or "(float)1.",
            weight=weight_expression or "(float)1.",
        )

    return _config_formatter
