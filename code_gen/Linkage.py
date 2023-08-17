from typing import Union, Optional, Callable, Any, TypeVar, List
from .BaseLink import BaseLink
from .types import WritableMemory


class Linkage(BaseLink):
    def __init__(self):
        self.lst_tgt: List[LinkRef] = []
        self.src: Optional[int] = None
        self.is_extern: bool = False

    def get_offset_link(self, offset):
        return OffsetLinkage(self, offset)

    def emit_load(
            self,
            memory: bytearray,
            size: int,
            byte_copy_arg: TypeVar("T"),
            byte_copy_intrinsic: Callable[[TypeVar("T"), bytearray, Optional[int], bool, bool], Any]
    ):
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 3:
            sz_cls_1 = emit_load_i_const(memory, size, False)
            memory.extend([BC_ADD_SP1 + sz_cls_1])
            self.emit_lea(memory)
            # using @@ByteCopyFn1
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, True)
            sz_cls_1 = emit_load_i_const(memory, stack_left, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_load_pot(memory, sz_cls_0)

    def emit_stor(
            self,
            memory: bytearray,
            size: int,
            byte_copy_arg: TypeVar("T"),
            byte_copy_intrinsic: Callable[[TypeVar("T"), bytearray, Optional[int], bool, bool], Any]
    ):
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 3:
            self.emit_lea(memory)
            # using @@ByteCopyFn2
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, False)
            sz_cls_1 = emit_load_i_const(memory, stack_left + size, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_stor_pot(memory, sz_cls_0)

    def emit_lea(self, memory: bytearray):
        memory.extend([
            BC_LOAD, BCR_EA_R_IP | BCR_SZ_8,
            0, 0, 0, 0, 0, 0, 0, 0])
        self.lst_tgt.append(LinkRef(len(memory) - 8, 0))

    def fill_all(self, memory: WritableMemory):
        assert self.src is not None
        assert not self.is_extern
        for Tgt in self.lst_tgt:
            assert isinstance(Tgt, LinkRef)
            Tgt.fill_ref(memory, self.src)

    def merge_from(self, other: "Linkage", mem_off: int):
        if (self.src is not None) and (other.src is not None):
            raise NameError("Link Error on merge: source ('src') is defined in 'self' and 'other'")
        if other.src is not None:
            self.src = other.src + mem_off
        start = len(self.lst_tgt)
        self.lst_tgt.extend([None] * len(other.lst_tgt))
        for c in range(start, len(self.lst_tgt)):
            a = other.lst_tgt[c - start]
            assert isinstance(a, LinkRef)
            self.lst_tgt[c] = a.get_new_link_off(mem_off)


from .OffsetLinkage import OffsetLinkage
from .LinkRef import LinkRef
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import BC_LOAD, BCR_SZ_8, BC_ADD_SP1, BC_RST_SP1, BCR_EA_R_IP, BCR_SZ_8