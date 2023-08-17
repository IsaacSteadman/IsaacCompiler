from typing import Optional, Dict
from .BaseCmplObj import BaseCmplObj


LNK_RUN_STANDALONE = 1


class LinkerOptions(object):
    __slots__ = ["remove_unused_deps", "data_seg_align", "extern_deps", "run_method"]

    def __init__(
        self,
        remove_unused_deps: bool = True,
        data_seg_align: int = 1,
        extern_deps: Optional[Dict[str, BaseCmplObj]] = None,
        run_method: int = LNK_RUN_STANDALONE,
    ):
        self.remove_unused_deps = remove_unused_deps
        self.data_seg_align = data_seg_align
        self.extern_deps = extern_deps
        self.run_method = run_method
