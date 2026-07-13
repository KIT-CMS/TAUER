import hashlib
import sys
from typing import List, Tuple, Union


from config.helper_collection import NestedDefaultDict
from ntuple_processor import RunManager


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


def add_paths(
    graph: object,
    channel: str,
    era: str,
    r_manager: RunManager,
):
    ntuple_dict, num_hash_bytes = generate_filepath_dict([it.path for it in graph.unit_block.ntuples])
    r_manager.config[channel][era][graph.name]["paths"]["ntuple"] = ntuple_dict

    for idx in range(len(graph.unit_block.ntuples[0].friends)):
        friend_files = [it.friends[idx].path for it in graph.unit_block.ntuples]

        friend_name = f'friends__{friend_files[0].split("CROWNFriends/")[-1].split("/")[0]}'
        friend_dict, _ = generate_filepath_dict(friend_files, num_bytes=num_hash_bytes)

        a, b = ntuple_dict.keys(), friend_dict.keys()
        assert not a - b and not b - a, "Hash collision detected. This should not have happen."

        r_manager.config[channel][era][graph.name]["paths"][friend_name] = friend_dict


def get_config_formatter(
    era: str,
    **kwargs,
):
    def _config_formatter(
        config: Union[dict, NestedDefaultDict],
        name: str,
        cut_expression: str,
        weight_expression: str,
        **kwargs,  # dont need more, see ntuple_processor/run/RunManager/__histo1d_from_hist for more details
    ) -> None:
        replacement_dict = {"Era": era}

        process, channel_and_sample, variation, variable = name.split("#")
        channel, *sample_parts = channel_and_sample.split("-")
        sample = "-".join(sample_parts)
        variation = variation.replace(f"_{variable}", "").replace("Channel", channel)

        for k, v in replacement_dict.items():
            variation = variation.replace(k, v)

        sample = "data" if process == "data" else sample

        config[channel][era][process][sample][variation] = NestedDefaultDict(
            cut=cut_expression or "(float)1.",
            weight=weight_expression or "(float)1.",
        )

    return _config_formatter
