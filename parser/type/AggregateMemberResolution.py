from dataclasses import dataclass
from typing import Optional


@dataclass
class AggregateMemberResolution:
    member: "ContextVariable"
    byte_offset: int
    bit_field_info: Optional["BitFieldInfo"] = None

    def shifted(self, byte_offset: int) -> "AggregateMemberResolution":
        if byte_offset == 0:
            return self
        bit_field_info = self.bit_field_info
        if bit_field_info is not None:
            bit_field_info = BitFieldInfo(
                byte_offset=bit_field_info.byte_offset + byte_offset,
                bit_shift=bit_field_info.bit_shift,
                bit_mask=bit_field_info.bit_mask,
                storage_sz=bit_field_info.storage_sz,
            )
        return AggregateMemberResolution(
            self.member,
            self.byte_offset + byte_offset,
            bit_field_info,
        )


from .BitFieldInfo import BitFieldInfo
from .ContextVariable import ContextVariable
