import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, Union

import yaml

from config.logging_setup_configs import setup_logging

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

