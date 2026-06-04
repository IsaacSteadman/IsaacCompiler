from enum import Enum
from typing import Union


class NameManglingMode(Enum):
    NONE = "none"
    ISAAC = "isaac"


def normalize_name_mangling_mode(
    mode: Union["NameManglingMode", str, None]
) -> "NameManglingMode":
    if mode is None:
        return NameManglingMode.NONE
    if isinstance(mode, NameManglingMode):
        return mode
    return NameManglingMode(mode)


def select_external_link_name(
    source_name: str,
    isaac_mangled_name: str,
    mode: Union["NameManglingMode", str, None],
) -> str:
    mode = normalize_name_mangling_mode(mode)
    return source_name if mode == NameManglingMode.NONE else isaac_mangled_name
