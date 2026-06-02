from typing import Any, Callable, Optional, TypeVar, Union


class BaseLink(object):
    def get_offset_link(self, offset: int) -> "BaseLink":
        raise NotImplementedError("Not Implemented")

    def emit_lea(self, memory: Union[memoryview, bytearray]):
        """
        Load Effective Address
        """
        raise NotImplementedError("Not Implemented")

    def emit_load_pot(
        self,
        memory: Union[memoryview, bytearray],
        sz_cls: int,
        cmpl_obj=None,
        volatile_access: bool = False,
    ):
        self.emit_lea(memory)
        if cmpl_obj is not None:
            record_memory_access(cmpl_obj, "load", 1 << sz_cls, volatile_access)
        memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])

    def emit_stor_pot(
        self,
        memory: Union[memoryview, bytearray],
        sz_cls: int,
        cmpl_obj=None,
        volatile_access: bool = False,
    ):
        self.emit_lea(memory)
        if cmpl_obj is not None:
            record_memory_access(cmpl_obj, "stor", 1 << sz_cls, volatile_access)
        memory.extend([
            # BC_SWAP, BCS_SZ8_B | sz_cls,  # SzCls0 does not need to be shifted as BCS_SZ_A_MASK is 0x7
            BC_STOR, BCR_ABS_S8 | (sz_cls << 5)])

    def emit_load(
        self,
        memory: bytearray,
        size: int,
        byte_copy_arg: TypeVar("T"),
        byte_copy_intrinsic: Callable[[TypeVar("T"), Union[memoryview, bytearray], Optional[int], bool, bool], Any],
        volatile_access: bool = False,
    ):
        cmpl_obj = byte_copy_arg if hasattr(byte_copy_arg, "memory_accesses") else None
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 4:
            if cmpl_obj is not None:
                record_memory_access(
                    cmpl_obj,
                    "load",
                    size,
                    volatile_access,
                    lowered_as_copy=True,
                )
            sz_cls_1 = emit_load_i_const(memory, size, False)
            memory.extend([BC_ADD_SP1 + sz_cls_1])
            self.emit_lea(memory)
            # using @@ByteCopyFn1
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, True)
            sz_cls_1 = emit_load_i_const(memory, stack_left, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_load_pot(memory, sz_cls_0, cmpl_obj, volatile_access)

    def emit_stor(
        self,
        memory: bytearray,
        size: int,
        byte_copy_arg: TypeVar("T"),
        byte_copy_intrinsic: Callable[[TypeVar("T"), Union[memoryview, bytearray], Optional[int], bool, bool], Any],
        volatile_access: bool = False,
    ):
        cmpl_obj = byte_copy_arg if hasattr(byte_copy_arg, "memory_accesses") else None
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 4:
            if cmpl_obj is not None:
                record_memory_access(
                    cmpl_obj,
                    "stor",
                    size,
                    volatile_access,
                    lowered_as_copy=True,
                )
            self.emit_lea(memory)
            # using @@ByteCopyFn2
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, False)
            sz_cls_1 = emit_load_i_const(memory, stack_left + size, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_stor_pot(memory, sz_cls_0, cmpl_obj, volatile_access)
    # byte_copy_intrinsic
    # OutIsStack for Load, InIsStack for Stor
    #   Arg: Generic
    #   memory: bytearray
    #   size: int
    #   IsStack: bool
    #   IsLoad
    '''def EmitLoad(self, memory, size, byte_copy_arg, byte_copy_intrinsic):
        """
        :param bytearray memory:
        :param int size:
        :param T byte_copy_arg:
        :param (T, bytearray, int|None, bool, bool) -> any byte_copy_intrinsic:
        """
        raise NotImplementedError("Not Implemented")
    def EmitStor(self, memory, size, byte_copy_arg, byte_copy_intrinsic):
        """
        :param bytearray memory:
        :param int size:
        :param T byte_copy_arg:
        :param (T, bytearray, int|None, bool, bool) -> any byte_copy_intrinsic:
        """
        raise NotImplementedError("Not Implemented")'''


from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from .memory_access import record_memory_access
from ..StackVM.PyStackVM import BCR_ABS_S8, BC_ADD_SP1, BC_LOAD, BC_RST_SP1,\
    BC_STOR
