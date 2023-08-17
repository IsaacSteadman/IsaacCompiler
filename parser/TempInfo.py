from typing import List, Tuple


class TempInfo(object):
    def __init__(self):
        self.temporaries: List[Tuple[BaseType, LocalRef]] = []

    def alloc_temporary(self, cmpl_data: "LocalCompileData", typ: "BaseType") -> int:
        pass


from .type.BaseType import BaseType
from ..code_gen.LocalCompileData import LocalCompileData
from ..code_gen.LocalRef import LocalRef