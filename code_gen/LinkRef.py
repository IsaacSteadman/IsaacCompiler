from typing import Optional


class LinkRef(object):
    def __init__(self, pos: int, rel_off: Optional[int]=None):
        self.pos = pos
        self.rel_off = rel_off

    def try_fill_ref_abs(self, memory: bytearray, abs_addr: int) -> bool:
        if self.rel_off is None:
            memory[self.pos:self.pos + 8] = sz_cls_align_long(abs_addr, False, 3)
        else:
            memory[self.pos:self.pos + 8] = sz_cls_align_long(abs_addr - (self.pos + 8 + self.rel_off), True, 3)
        return True

    def try_fill_ref_rel(self, memory: bytearray, local_abs_addr: int) -> bool:
        if self.rel_off is None:
            return False
        else:
            memory[self.pos:self.pos + 8] = sz_cls_align_long(local_abs_addr - (self.pos + 8 + self.rel_off), True, 3)
        return True

    def fill_ref(self, memory: bytearray, abs_addr: int):
        self.try_fill_ref_abs(memory, abs_addr)

    def get_new_link_off(self, mem_off: int):
        return LinkRef(self.pos + mem_off, self.rel_off)


from .stackvm_binutils.sz_cls_align_long import sz_cls_align_long