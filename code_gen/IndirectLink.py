from .BaseLink import BaseLink


def dummy_byte_copy_intrinsic(arg, mem, sz, b0, b1):
    raise ValueError("A Byte copy intrinsic was not provided for %r, memory(len=%u), sz=%u, b0=%r, b1=%r" % (arg, len(mem), sz, b0, b1))


class IndirectLink(BaseLink):
    def __init__(self, addr_link: BaseLink):
        self.addr_link = addr_link

    def get_offset_link(self, offset):
        return OffsetIndirectLink(self, offset)

    def emit_lea(self, memory: bytearray):
        self.addr_link.emit_load(memory, 8, None, dummy_byte_copy_intrinsic)


from .OffsetIndirectLink import OffsetIndirectLink
