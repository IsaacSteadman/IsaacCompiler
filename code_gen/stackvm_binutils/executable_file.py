from dataclasses import dataclass
import struct
from typing import BinaryIO, Optional, Union


SBC_MAGIC = b"\xf7SVE\0\0\0\0"
SBC_SPARSE_MAGIC = b"\xf7SVE\0\0\0\1"
SBC_HEADER_SIZE = 32

_HEADER = struct.Struct("<8sQQQ")

assert _HEADER.size == SBC_HEADER_SIZE


@dataclass
class StackVMExecutable:
    memory: bytes
    code_segment_end: int
    data_segment_start: int
    file_size: Optional[int] = None


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


def dumps_sbc(executable: StackVMExecutable) -> bytes:
    _validate_executable(executable)
    memory = bytes(executable.memory)
    file_size = len(memory) if executable.file_size is None else executable.file_size
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
    magic, code_segment_end, data_segment_start, memory_size = _HEADER.unpack_from(data)
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
