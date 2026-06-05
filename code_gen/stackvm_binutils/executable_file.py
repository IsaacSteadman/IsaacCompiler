from dataclasses import dataclass, field
import struct
from typing import BinaryIO, Iterable, Optional, Tuple, Union


SBC_MAGIC = b"\xf7SVE\0\0\0\0"
SBC_SPARSE_MAGIC = b"\xf7SVE\0\0\0\1"
SBC_RELOC_MAGIC = b"\xf7SVE\0\0\0\2"
SBC_DEBUG_MAGIC = b"\xf7SVE\0\0\0\3"
SBC_HEADER_SIZE = 32
SBC_RELOC_HEADER_SIZE = 48
SBC_DEBUG_HEADER_SIZE = 64

_HEADER = struct.Struct("<8sQQQ")
_RELOC_HEADER = struct.Struct("<8sQQQQQ")
_DEBUG_HEADER = struct.Struct("<8sQQQQQQQ")

assert _HEADER.size == SBC_HEADER_SIZE
assert _RELOC_HEADER.size == SBC_RELOC_HEADER_SIZE
assert _DEBUG_HEADER.size == SBC_DEBUG_HEADER_SIZE


@dataclass
class StackVMExecutable:
    memory: bytes
    code_segment_end: int
    data_segment_start: int
    file_size: Optional[int] = None
    base_relocations: Tuple[int, ...] = field(default_factory=tuple)
    debug_info: bytes = b""


def apply_base_fixups(
    memory: bytearray,
    base_relocations: Iterable[int],
    base_delta: int,
) -> bytearray:
    if base_delta == 0:
        return memory
    mask = (1 << 64) - 1
    for offset in base_relocations:
        value = int.from_bytes(memory[offset : offset + 8], "little")
        memory[offset : offset + 8] = ((value + base_delta) & mask).to_bytes(
            8,
            "little",
        )
    return memory


def _validate_executable(executable: StackVMExecutable) -> None:
    memory_size = len(executable.memory)
    if executable.code_segment_end < 0 or executable.data_segment_start < 0:
        raise ValueError("segment addresses must be non-negative")
    if executable.code_segment_end > executable.data_segment_start:
        raise ValueError("code segment must end before the data segment starts")
    if executable.data_segment_start > memory_size:
        raise ValueError("data segment starts past the end of memory")
    file_size = memory_size if executable.file_size is None else executable.file_size
    if file_size < 0 or file_size > memory_size:
        raise ValueError("file-backed memory size is outside the memory image")
    if any(executable.memory[file_size:]):
        raise ValueError("omitted executable memory must be zero-initialized")
    for offset in executable.base_relocations:
        if offset < 0 or offset + 8 > memory_size:
            raise ValueError("base relocation offset is outside the memory image")
    bytes(executable.debug_info)


def dumps_sbc(executable: StackVMExecutable) -> bytes:
    _validate_executable(executable)
    memory = bytes(executable.memory)
    file_size = len(memory) if executable.file_size is None else executable.file_size
    base_relocations = tuple(executable.base_relocations)
    debug_info = bytes(executable.debug_info)
    if debug_info:
        relocation_table = bytearray()
        for offset in base_relocations:
            relocation_table.extend(offset.to_bytes(8, "little"))
        return (
            _DEBUG_HEADER.pack(
                SBC_DEBUG_MAGIC,
                executable.code_segment_end,
                executable.data_segment_start,
                len(memory),
                file_size,
                len(base_relocations),
                len(debug_info),
                0,
            )
            + memory[:file_size]
            + relocation_table
            + debug_info
        )
    if base_relocations:
        relocation_table = bytearray()
        for offset in base_relocations:
            relocation_table.extend(offset.to_bytes(8, "little"))
        return (
            _RELOC_HEADER.pack(
                SBC_RELOC_MAGIC,
                executable.code_segment_end,
                executable.data_segment_start,
                len(memory),
                file_size,
                len(base_relocations),
            )
            + memory[:file_size]
            + relocation_table
        )
    return _HEADER.pack(
        SBC_MAGIC if file_size == len(memory) else SBC_SPARSE_MAGIC,
        executable.code_segment_end,
        executable.data_segment_start,
        len(memory),
    ) + memory[:file_size]


def write_sbc(executable: StackVMExecutable, target: Union[str, BinaryIO]) -> None:
    data = dumps_sbc(executable)
    if hasattr(target, "write"):
        target.write(data)
        return
    with open(target, "wb") as fl:
        fl.write(data)


def loads_sbc(data: bytes) -> StackVMExecutable:
    if len(data) < SBC_HEADER_SIZE:
        raise ValueError("binary file is too short to contain a header")
    magic = data[:8]
    if magic == SBC_RELOC_MAGIC:
        if len(data) < SBC_RELOC_HEADER_SIZE:
            raise ValueError("binary file is too short to contain a relocation header")
        (
            _magic,
            code_segment_end,
            data_segment_start,
            memory_size,
            file_size,
            relocation_count,
        ) = _RELOC_HEADER.unpack_from(data)
        payload_start = SBC_RELOC_HEADER_SIZE
        relocation_table_start = payload_start + file_size
        expected_size = relocation_table_start + relocation_count * 8
        if len(data) != expected_size:
            raise ValueError("binary file relocation table size does not match header")
        if file_size > memory_size:
            raise ValueError("binary file payload is larger than its memory image")
        base_relocations = []
        for index in range(relocation_count):
            offset = relocation_table_start + index * 8
            base_relocations.append(
                int.from_bytes(data[offset : offset + 8], "little")
            )
        executable = StackVMExecutable(
            data[payload_start:relocation_table_start]
            + b"\0" * (memory_size - file_size),
            code_segment_end,
            data_segment_start,
            file_size,
            tuple(base_relocations),
        )
        _validate_executable(executable)
        return executable

    if magic == SBC_DEBUG_MAGIC:
        if len(data) < SBC_DEBUG_HEADER_SIZE:
            raise ValueError("binary file is too short to contain a debug header")
        (
            _magic,
            code_segment_end,
            data_segment_start,
            memory_size,
            file_size,
            relocation_count,
            debug_size,
            reserved,
        ) = _DEBUG_HEADER.unpack_from(data)
        if reserved != 0:
            raise ValueError("binary file debug header reserved field must be zero")
        payload_start = SBC_DEBUG_HEADER_SIZE
        relocation_table_start = payload_start + file_size
        debug_start = relocation_table_start + relocation_count * 8
        expected_size = debug_start + debug_size
        if len(data) != expected_size:
            raise ValueError("binary file debug payload size does not match header")
        if file_size > memory_size:
            raise ValueError("binary file payload is larger than its memory image")
        base_relocations = []
        for index in range(relocation_count):
            offset = relocation_table_start + index * 8
            base_relocations.append(
                int.from_bytes(data[offset : offset + 8], "little")
            )
        executable = StackVMExecutable(
            data[payload_start:relocation_table_start]
            + b"\0" * (memory_size - file_size),
            code_segment_end,
            data_segment_start,
            file_size,
            tuple(base_relocations),
            data[debug_start:expected_size],
        )
        _validate_executable(executable)
        return executable

    magic, code_segment_end, data_segment_start, memory_size = _HEADER.unpack_from(
        data
    )
    if magic not in {SBC_MAGIC, SBC_SPARSE_MAGIC}:
        raise ValueError("invalid .sbc magic")
    payload_size = len(data) - SBC_HEADER_SIZE
    if magic == SBC_MAGIC and payload_size != memory_size:
        raise ValueError("binary file size does not match its header")
    if payload_size > memory_size:
        raise ValueError("binary file payload is larger than its memory image")
    executable = StackVMExecutable(
        data[SBC_HEADER_SIZE:] + b"\0" * (memory_size - payload_size),
        code_segment_end,
        data_segment_start,
        payload_size,
    )
    _validate_executable(executable)
    return executable


def load_sbc(source: Union[str, BinaryIO]) -> StackVMExecutable:
    if hasattr(source, "read"):
        return loads_sbc(source.read())
    with open(source, "rb") as fl:
        return loads_sbc(fl.read())
