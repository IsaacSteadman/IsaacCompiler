from typing import Optional

from .stackvm_binutils.object_file import RelocationType


class LinkRef(object):
    def __init__(
        self,
        pos: int,
        rel_off: Optional[int] = None,
        relocation_type: Optional[RelocationType] = None,
        addend: int = 0,
    ):
        self.pos = pos
        if relocation_type is None:
            self.relocation_type = (
                RelocationType.ABS8
                if rel_off is None
                else RelocationType.PCREL8
            )
            self.addend = 0 if rel_off is None else -rel_off
        else:
            self.relocation_type = RelocationType(relocation_type)
            self.addend = addend

    @property
    def rel_off(self) -> Optional[int]:
        if self.relocation_type == RelocationType.ABS8:
            return None
        return -self.addend

    @rel_off.setter
    def rel_off(self, value: Optional[int]) -> None:
        if value is None:
            self.relocation_type = RelocationType.ABS8
            self.addend = 0
        else:
            self.relocation_type = RelocationType.PCREL8
            self.addend = -value

    @staticmethod
    def _write_value(memory: bytearray, pos: int, value: int) -> None:
        memory[pos : pos + 8] = (value & ((1 << 64) - 1)).to_bytes(8, "little")

    def try_fill_ref_abs(self, memory: bytearray, abs_addr: int) -> bool:
        if self.relocation_type == RelocationType.ABS8:
            value = abs_addr + self.addend
        else:
            value = abs_addr + self.addend - (self.pos + 8)
        self._write_value(memory, self.pos, value)
        return True

    def try_fill_ref_rel(self, memory: bytearray, local_abs_addr: int) -> bool:
        if self.relocation_type != RelocationType.PCREL8:
            return False
        self._write_value(
            memory,
            self.pos,
            local_abs_addr + self.addend - (self.pos + 8),
        )
        return True

    def fill_ref(self, memory: bytearray, abs_addr: int):
        self.try_fill_ref_abs(memory, abs_addr)

    def get_new_link_off(self, mem_off: int):
        return LinkRef(
            self.pos + mem_off,
            relocation_type=self.relocation_type,
            addend=self.addend,
        )
