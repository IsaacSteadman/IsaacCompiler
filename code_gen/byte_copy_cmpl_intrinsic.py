from typing import Optional


def byte_copy_cmpl_intrinsic(
        cmpl_obj: "BaseCmplObj",
        memory: bytearray,
        size: Optional[int],
        is_stack: bool,
        is_load: bool
):
    if is_load:
        lnk = cmpl_obj.get_link("@@ByteCopyFn1" if is_stack else "@@ByteCopyFn")
        memory.extend([
            BC_LOAD, BCR_ABS_C | BCR_SZ_8])
        memory.extend(sz_cls_align_long(size, False, 3))
        emit_rel_call(memory, lnk)
    else:
        lnk = cmpl_obj.get_link("@@ByteCopyFn2" if is_stack else "@@ByteCopyFn")
        memory.extend([
            BC_LOAD, BCR_ABS_C | BCR_SZ_8])
        memory.extend(sz_cls_align_long(size, False, 3))
        emit_rel_call(memory, lnk)
    return 16 if is_stack else 24


from .BaseCmplObj import BaseCmplObj
from .branch_emit import emit_rel_call
from .stackvm_binutils.sz_cls_align_long import sz_cls_align_long
from ..StackVM.PyStackVM import BCR_ABS_C, BCR_SZ_8, BC_LOAD
