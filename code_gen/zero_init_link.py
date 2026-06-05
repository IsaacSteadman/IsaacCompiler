def emit_push_zeros(memory: bytearray, n: int):
    """Emit bytecode that pushes exactly *n* zero bytes onto the VM stack."""
    while n >= 8:
        emit_load_i_const(memory, 0, False, 3)  # 8-byte zero
        n -= 8
    if n >= 4:
        emit_load_i_const(memory, 0, False, 2)  # 4-byte zero
        n -= 4
    if n >= 2:
        emit_load_i_const(memory, 0, False, 1)  # 2-byte zero
        n -= 2
    if n == 1:
        emit_load_i_const(memory, 0, False, 0)  # 1-byte zero


def zero_init_link(
    cmpl_obj: "BaseCmplObj",
    link: "BaseLink",
    size: int,
    volatile_access: bool = False,
) -> None:
    emit_push_zeros(cmpl_obj.memory, size)
    link.emit_stor(
        cmpl_obj.memory,
        size,
        cmpl_obj,
        byte_copy_cmpl_intrinsic,
        volatile_access=volatile_access,
    )


from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from .byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from .BaseLink import BaseLink
from .BaseCmplObj import BaseCmplObj
