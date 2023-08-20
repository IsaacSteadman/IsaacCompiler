from .BaseLink import BaseLink


class OffsetIndirectLink(BaseLink):
    def __init__(self, parent: "IndirectLink", offset: int):
        self.parent = parent
        self.offset = offset

    def get_offset_link(self, offset: int):
        return OffsetIndirectLink(self.parent, self.offset + offset)

    def emit_lea(self, memory: bytearray):
        self.parent.emit_lea(memory)
        emit_load_i_const(memory, self.offset, True, 3)
        memory.append(BC_ADD8)


from ..StackVM.PyStackVM import BC_ADD8
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from .IndirectLink import IndirectLink
