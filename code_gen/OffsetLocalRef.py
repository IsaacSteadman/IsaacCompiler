from .BaseLink import BaseLink


class OffsetLocalRef(BaseLink):
    def __init__(self, parent: "LocalRef", offset: int):
        self.parent = parent
        self.offset = offset
        self.sz = parent.sz - offset

    def get_offset_link(self, offset: int) -> BaseLink:
        # TODO: Convert EmitLoad, EmitStor, EmitLEA
        return OffsetLocalRef(self.parent, self.offset + offset)

    def emit_load_pot(
        self,
        memory: bytearray,
        sz_cls: int,
        cmpl_obj=None,
        volatile_access: bool = False,
        atomic_access: bool = False,
        atomic_order: int = 3,
    ):
        byts, sz_cls_r_bp = get_sz_cls_align_long(self.parent.rel_addr + self.offset, True)
        if cmpl_obj is not None:
            record_memory_access(cmpl_obj, "load", 1 << sz_cls, volatile_access)
        if atomic_access:
            self.emit_lea(memory)
            memory.extend([BC_LOAD, BCR_ATOMIC_LOAD | (sz_cls << 5), atomic_order & 0xFF])
            return
        memory.extend([BC_LOAD, (BCR_R_BP1 + sz_cls_r_bp) | (sz_cls << 5)])
        memory.extend(byts)

    def emit_stor_pot(
        self,
        memory: bytearray,
        sz_cls: int,
        cmpl_obj=None,
        volatile_access: bool = False,
        atomic_access: bool = False,
        atomic_order: int = 3,
    ):
        byts, sz_cls_r_bp = get_sz_cls_align_long(self.parent.rel_addr + self.offset, True)
        if cmpl_obj is not None:
            record_memory_access(cmpl_obj, "stor", 1 << sz_cls, volatile_access)
        if atomic_access:
            self.emit_lea(memory)
            memory.extend([BC_STOR, BCR_ATOMIC_STORE | (sz_cls << 5), atomic_order & 0xFF])
            return
        memory.extend([BC_STOR, (BCR_R_BP1 + sz_cls_r_bp) | (sz_cls << 5)])
        memory.extend(byts)

    def emit_lea(self, memory: bytearray):
        byts = sz_cls_align_long(self.parent.rel_addr + self.offset, True, 3)
        memory.extend([BC_LOAD, BCR_REG_BP | BCR_SZ_8, BC_LOAD, BCR_ABS_C | BCR_SZ_8])
        memory.extend(byts)
        memory.extend([BC_ADD8])


from .LocalRef import LocalRef
from .memory_access import record_memory_access
from .stackvm_binutils.get_sz_cls_align_long import get_sz_cls_align_long
from .stackvm_binutils.sz_cls_align_long import sz_cls_align_long
from ..StackVM.PyStackVM import BCR_ABS_C, BCR_ATOMIC_LOAD, BCR_ATOMIC_STORE,\
    BCR_REG_BP, BCR_R_BP1, BCR_SZ_8, BC_ADD8, BC_LOAD, BC_STOR
