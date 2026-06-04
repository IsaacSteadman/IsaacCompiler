from typing import Optional

from .LinkerOptions import LinkerOptions
from .NameMangling import NameManglingMode, normalize_name_mangling_mode


class CompilerOptions(object):
    __slots__ = [
        "link_opts",
        "merge_and_link",
        "keep_local_syms",
        "name_mangling_mode",
    ]

    def __init__(
        self,
        link_opts: LinkerOptions,
        merge_and_link: bool = True,
        keep_local_syms: bool = False,
        name_mangling_mode: Optional[NameManglingMode] = None,
    ):
        self.link_opts = link_opts
        self.merge_and_link = merge_and_link
        self.keep_local_syms = keep_local_syms
        self.name_mangling_mode = normalize_name_mangling_mode(
            link_opts.name_mangling_mode
            if name_mangling_mode is None
            else name_mangling_mode
        )
