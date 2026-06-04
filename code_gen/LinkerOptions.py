from typing import Optional, Dict
from .BaseCmplObj import BaseCmplObj
from .NameMangling import NameManglingMode, normalize_name_mangling_mode


LNK_RUN_STANDALONE = 1


class LinkerOptions(object):
    __slots__ = [
        "remove_unused_deps",
        "data_seg_align",
        "extern_deps",
        "run_method",
        "default_alignment",
        "name_mangling_mode",
    ]

    def __init__(
        self,
        remove_unused_deps: bool = True,
        data_seg_align: int = 1,
        extern_deps: Optional[Dict[str, BaseCmplObj]] = None,
        run_method: int = LNK_RUN_STANDALONE,
        default_alignment: Optional[int] = None,
        name_mangling_mode: NameManglingMode = NameManglingMode.NONE,
    ):
        self.remove_unused_deps = remove_unused_deps
        self.data_seg_align = data_seg_align
        self.extern_deps = extern_deps
        self.run_method = run_method
        self.default_alignment = default_alignment
        self.name_mangling_mode = normalize_name_mangling_mode(name_mangling_mode)
