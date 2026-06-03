from dataclasses import dataclass

from ..StackVM.PyStackVM import (
    BCR_ABS_S8,
    BCR_ATOMIC_LOAD,
    BCR_ATOMIC_STORE,
    BC_LOAD,
    BC_STOR,
)


@dataclass(frozen=True)
class MemoryAccess:
    instr_offset: int
    kind: str
    size: int
    is_volatile: bool
    lowered_as_copy: bool = False

    def shifted(self, offset: int) -> "MemoryAccess":
        return MemoryAccess(
            self.instr_offset + offset,
            self.kind,
            self.size,
            self.is_volatile,
            self.lowered_as_copy,
        )


def record_memory_access(
    cmpl_obj,
    kind: str,
    size: int,
    is_volatile: bool,
    lowered_as_copy: bool = False,
) -> None:
    cmpl_obj.memory_accesses.append(
        MemoryAccess(len(cmpl_obj.memory), kind, size, is_volatile, lowered_as_copy)
    )


def emit_tracked_abs_s8_load(
    cmpl_obj,
    size: int,
    is_volatile: bool = False,
    atomic_access: bool = False,
    atomic_order: int = 3,
) -> None:
    sz_cls = size.bit_length() - 1
    assert size == 1 << sz_cls
    record_memory_access(cmpl_obj, "load", size, is_volatile)
    if atomic_access:
        cmpl_obj.memory.extend(
            [BC_LOAD, BCR_ATOMIC_LOAD | (sz_cls << 5), atomic_order & 0xFF]
        )
    else:
        cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])


def emit_tracked_abs_s8_stor(
    cmpl_obj,
    size: int,
    is_volatile: bool = False,
    atomic_access: bool = False,
    atomic_order: int = 3,
) -> None:
    sz_cls = size.bit_length() - 1
    assert size == 1 << sz_cls
    record_memory_access(cmpl_obj, "stor", size, is_volatile)
    if atomic_access:
        cmpl_obj.memory.extend(
            [BC_STOR, BCR_ATOMIC_STORE | (sz_cls << 5), atomic_order & 0xFF]
        )
    else:
        cmpl_obj.memory.extend([BC_STOR, BCR_ABS_S8 | (sz_cls << 5)])


def emit_atomic_load_variant(
    cmpl_obj,
    variant: int,
    size: int,
    atomic_order: int,
    is_volatile: bool = False,
) -> None:
    sz_cls = size.bit_length() - 1
    assert size == 1 << sz_cls
    record_memory_access(cmpl_obj, "load", size, is_volatile)
    cmpl_obj.memory.extend([BC_LOAD, variant | (sz_cls << 5), atomic_order & 0xFF])
