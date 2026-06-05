from dataclasses import dataclass


@dataclass
class BitFieldInfo:
    """Describes the position and size of a bit-field within its storage unit."""

    byte_offset: int
    bit_shift: int
    bit_mask: int
    storage_sz: int
