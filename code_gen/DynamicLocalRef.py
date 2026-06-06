from typing import List, Optional

from .BaseLink import BaseLink


class DynamicLocalRef(BaseLink):
    def __init__(
        self,
        base_bp_off: int,
        sz: int,
        dynamic_size_links: List[BaseLink],
        offset: int = 0,
        vla_size_link: Optional[BaseLink] = None,
    ):
        self.base_bp_off = base_bp_off
        self.sz = sz
        self.dynamic_size_links = list(dynamic_size_links)
        self.offset = offset
        self.vla_size_link = vla_size_link

    def get_offset_link(self, offset: int) -> BaseLink:
        return DynamicLocalRef(
            self.base_bp_off,
            self.sz - offset,
            self.dynamic_size_links,
            self.offset + offset,
            self.vla_size_link,
        )

    def emit_lea(self, memory: bytearray):
        memory.extend([BC_LOAD, BCR_REG_BP | BCR_SZ_8])
        static_delta = self.offset - self.base_bp_off
        if static_delta != 0:
            emit_load_i_const(memory, static_delta, True, 3)
            memory.extend([BC_ADD8])
        for size_link in self.dynamic_size_links:
            size_link.emit_load_pot(memory, 3)
            memory.extend([BC_SUB8])


from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import BCR_REG_BP, BCR_SZ_8, BC_ADD8, BC_LOAD, BC_SUB8
