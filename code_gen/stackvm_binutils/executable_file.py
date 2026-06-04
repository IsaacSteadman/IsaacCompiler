from dataclasses import dataclass
import struct
from typing import BinaryIO, Union


SBC_MAGIC = b"\xf7SVE\0\0\0\0"
SBC_HEADER_SIZE = 32

_HEADER = struct.Struct("<8sQQQ")

assert _HEADER.size == SBC_HEADER_SIZE


@dataclass
class StackVMExecutable:
    memory: bytes
    code_segment_end: int
    data_segment_start: int


def _validate_executable(executable: StackVMExecutable) -> None:
    memory_size = len(executable.memory)
    if executable.code_segment_end < 0 or executable.data_segment_start < 0:
        raise ValueError("segment addresses must be non-negative")
    if executable.code_segment_end > executable.data_segment_start:
        raise ValueError("code segment must end before the data segment starts")
    if executable.data_segment_start > memory_size:
        raise ValueError("data segment starts past the end of memory")


def dumps_sbc(executable: StackVMExecutable) -> bytes:
    _validate_executable(executable)
    memory = bytes(executable.memory)
    return _HEADER.pack(
        SBC_MAGIC,
        executable.code_segment_end,
        executable.data_segment_start,
        len(memory),
    ) + memory


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
    if magic != SBC_MAGIC:
        raise ValueError("invalid .sbc magic")
    if SBC_HEADER_SIZE + memory_size != len(data):
        raise ValueError("binary file size does not match its header")
    executable = StackVMExecutable(
        data[SBC_HEADER_SIZE:],
        code_segment_end,
        data_segment_start,
    )
    _validate_executable(executable)
    return executable


def load_sbc(source: Union[str, BinaryIO]) -> StackVMExecutable:
    if hasattr(source, "read"):
        return loads_sbc(source.read())
    with open(source, "rb") as fl:
        return loads_sbc(fl.read())
