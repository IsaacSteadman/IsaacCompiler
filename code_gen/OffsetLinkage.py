from typing import Any, Callable, Optional, TypeVar, Union

from .BaseLink import BaseLink

T = TypeVar("T")


class OffsetLinkage(BaseLink):
    def __init__(self, parent: "Linkage", offset: int):
        self.parent = parent
        self.offset = offset

    def get_offset_link(self, offset: int):
        return OffsetLinkage(self.parent, offset + self.offset)

    def emit_lea(self, memory: Union[memoryview, bytearray]):
        memory.extend([BC_LOAD, BCR_EA_R_IP | BCR_SZ_8, 0, 0, 0, 0, 0, 0, 0, 0])
        self.parent.lst_tgt.append(LinkRef(len(memory) - 8, -self.offset))

    def emit_load(
        self,
        memory: bytearray,
        size: int,
        byte_copy_arg: T,
        byte_copy_intrinsic: Callable[[T, Optional[int], bool, bool], Any],
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
        byte_copy_arg: T,
        byte_copy_intrinsic: Callable[
            [T, Union[memoryview, bytearray], Optional[int], bool, bool], Any
        ],
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


from ..StackVM.PyStackVM import BC_ADD_SP1, BC_LOAD, BC_RST_SP1, BCR_EA_R_IP, BCR_SZ_8
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from .Linkage import Linkage
from .LinkRef import LinkRef
