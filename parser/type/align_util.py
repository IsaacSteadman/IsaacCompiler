from typing import Optional


def align_up(x: int, align: int) -> int:
    """Round x up to the nearest multiple of align (align must be a power of 2)."""
    return (x + align - 1) & ~(align - 1)


def host_atomic_align_for_size(size: int) -> int:
    if size <= 1:
        return 1
    if size in {2, 4, 8, 16}:
        return size
    return 1 << (size - 1).bit_length()


def normalize_default_alignment(alignment: Optional[int]) -> Optional[int]:
    if alignment is None or alignment <= 1:
        return None
    if alignment & (alignment - 1):
        raise ValueError("default alignment must be a power of two")
    return alignment


def default_align_for_size(size: int, default_alignment: Optional[int]) -> int:
    default_alignment = normalize_default_alignment(default_alignment)
    if size <= 1 or default_alignment is None:
        return 1
    return min(size, default_alignment)
