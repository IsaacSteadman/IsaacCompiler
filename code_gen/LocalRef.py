from .BaseLink import BaseLink


class LocalRef(BaseLink):
    @classmethod
    def from_bp_off_post_inc(cls, bp_off: int, sz: int):
        return cls(-bp_off, sz)

    @classmethod
    def from_bp_off_pre_inc(cls, bp_off: int, sz: int):
        return cls(-(bp_off + sz), sz)

    def __init__(self, rel_addr: int, sz: int):
        self.rel_addr = rel_addr
        self.sz = sz

    def get_offset_link(self, offset: int) -> BaseLink:
        return OffsetLocalRef(self, offset)

    def emit_load_pot(self, memory: bytearray, sz_cls: int):
        byts, sz_cls_r_bp = get_sz_cls_align_long(self.rel_addr, True)
        memory.extend([BC_LOAD, (BCR_R_BP1 + sz_cls_r_bp) | (sz_cls << 5)])
        memory.extend(byts)

    def emit_stor_pot(self, memory: bytearray, sz_cls: int):
        byts, sz_cls_r_bp = get_sz_cls_align_long(self.rel_addr, True)
        memory.extend([BC_STOR, (BCR_R_BP1 + sz_cls_r_bp) | (sz_cls << 5)])
        memory.extend(byts)

    def emit_lea(self, memory: bytearray):
        byts = sz_cls_align_long(self.rel_addr, True, 3)
        memory.extend([BC_LOAD, BCR_REG_BP | BCR_SZ_8, BC_LOAD, BCR_ABS_C | BCR_SZ_8])
        memory.extend(byts)
        memory.extend([BC_ADD8])


from .OffsetLocalRef import OffsetLocalRef
from .stackvm_binutils.get_sz_cls_align_long import get_sz_cls_align_long
from .stackvm_binutils.sz_cls_align_long import sz_cls_align_long
from ..StackVM.PyStackVM import BCR_ABS_C, BCR_REG_BP, BCR_R_BP1, BCR_SZ_8,\
    BC_ADD8, BC_LOAD, BC_STOR