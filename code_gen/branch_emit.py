from .LinkRef import LinkRef
from .stackvm_binutils.object_file import RelocationType
from ..StackVM.PyStackVM import (
    BCR_ABS_C,
    BCR_SZ_8,
    BC_LOAD,
    BC_RCALL,
    BC_RJMP,
    BC_RJMPIF,
)


def emit_pcrel_link(
    memory: bytearray,
    linkage: "Linkage",
    relative_to_after_bytes: int = 0,
) -> None:
    memory.extend([BC_LOAD, BCR_ABS_C | BCR_SZ_8, 0, 0, 0, 0, 0, 0, 0, 0])
    linkage.lst_tgt.append(
        LinkRef(
            len(memory) - 8,
            relocation_type=RelocationType.PCREL8,
            addend=-relative_to_after_bytes,
        )
    )


def emit_rel_call(memory: bytearray, linkage: "Linkage") -> None:
    emit_pcrel_link(memory, linkage, 1)
    memory.append(BC_RCALL)


def emit_rel_jump(memory: bytearray, linkage: "Linkage") -> None:
    emit_pcrel_link(memory, linkage, 1)
    memory.append(BC_RJMP)


def emit_rel_jumpif(memory: bytearray, linkage: "Linkage") -> None:
    emit_pcrel_link(memory, linkage, 1)
    memory.append(BC_RJMPIF)
