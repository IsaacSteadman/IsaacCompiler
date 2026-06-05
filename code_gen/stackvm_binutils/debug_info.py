from dataclasses import dataclass, field
import struct
from typing import Iterable, List, Optional, Sequence, Tuple, Union


DEBUG_SECTION_NAME = ".debug"
STACKVM_DEBUG_MAGIC = b"\xf7SVD\0\0\0\0"
STACKVM_DEBUG_VERSION = 1
DEFAULT_RETURN_ADDRESS_OFFSET = 0
DEFAULT_PREVIOUS_BP_OFFSET = 8

_HEADER = struct.Struct("<8sQQQQ")
_STRING_LENGTH = struct.Struct("<Q")
_LINE = struct.Struct("<QQQQQ")
_FUNCTION = struct.Struct("<QQQQQQQ")


@dataclass(frozen=True)
class DebugLineRecord:
    address: int
    file: str
    line: int
    column: int = 0
    section: str = ""


@dataclass(frozen=True)
class DebugFunctionRecord:
    name: str
    address: int
    size: int
    frame_size: int = 0
    return_address_offset: int = DEFAULT_RETURN_ADDRESS_OFFSET
    previous_bp_offset: int = DEFAULT_PREVIOUS_BP_OFFSET
    section: str = ""


@dataclass
class StackVMDebugInfo:
    lines: List[DebugLineRecord] = field(default_factory=list)
    functions: List[DebugFunctionRecord] = field(default_factory=list)


@dataclass(frozen=True)
class StackFrame:
    address: int
    base_pointer: int
    function: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    return_address: Optional[int] = None


def _validate_nonnegative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError("%s must be non-negative" % name)


def _validate_debug_info(info: StackVMDebugInfo) -> None:
    for record in info.lines:
        _validate_nonnegative("line address", record.address)
        _validate_nonnegative("line number", record.line)
        _validate_nonnegative("column number", record.column)
        record.file.encode("utf-8")
        record.section.encode("utf-8")
    for record in info.functions:
        _validate_nonnegative("function address", record.address)
        _validate_nonnegative("function size", record.size)
        _validate_nonnegative("frame size", record.frame_size)
        _validate_nonnegative("return address offset", record.return_address_offset)
        _validate_nonnegative("previous bp offset", record.previous_bp_offset)
        record.name.encode("utf-8")
        record.section.encode("utf-8")


def dumps_debug(info: StackVMDebugInfo) -> bytes:
    _validate_debug_info(info)
    strings: List[str] = []
    string_indices = {}

    def string_index(value: str) -> int:
        index = string_indices.get(value)
        if index is None:
            index = len(strings)
            strings.append(value)
            string_indices[value] = index
        return index

    for record in info.lines:
        string_index(record.section)
        string_index(record.file)
    for record in info.functions:
        string_index(record.section)
        string_index(record.name)

    out = bytearray(
        _HEADER.pack(
            STACKVM_DEBUG_MAGIC,
            STACKVM_DEBUG_VERSION,
            len(strings),
            len(info.lines),
            len(info.functions),
        )
    )
    for value in strings:
        encoded = value.encode("utf-8")
        out.extend(_STRING_LENGTH.pack(len(encoded)))
        out.extend(encoded)
    for record in info.lines:
        out.extend(
            _LINE.pack(
                string_index(record.section),
                record.address,
                string_index(record.file),
                record.line,
                record.column,
            )
        )
    for record in info.functions:
        out.extend(
            _FUNCTION.pack(
                string_index(record.section),
                record.address,
                record.size,
                string_index(record.name),
                record.frame_size,
                record.return_address_offset,
                record.previous_bp_offset,
            )
        )
    return bytes(out)


def _unpack_string(data: bytes, offset: int) -> Tuple[str, int]:
    if offset + _STRING_LENGTH.size > len(data):
        raise ValueError("debug string table is truncated")
    length = _STRING_LENGTH.unpack_from(data, offset)[0]
    offset += _STRING_LENGTH.size
    end = offset + length
    if end > len(data):
        raise ValueError("debug string table is truncated")
    try:
        return data[offset:end].decode("utf-8"), end
    except UnicodeDecodeError as exc:
        raise ValueError("debug string is not valid UTF-8") from exc


def _get_string(strings: Sequence[str], index: int) -> str:
    if index >= len(strings):
        raise ValueError("debug record string index is out of range")
    return strings[index]


def loads_debug(data: bytes) -> StackVMDebugInfo:
    if len(data) < _HEADER.size:
        raise ValueError("debug section is too short to contain a header")
    magic, version, string_count, line_count, function_count = _HEADER.unpack_from(data)
    if magic != STACKVM_DEBUG_MAGIC:
        raise ValueError("invalid StackVM debug magic")
    if version != STACKVM_DEBUG_VERSION:
        raise ValueError("unsupported StackVM debug version: %u" % version)

    offset = _HEADER.size
    strings = []
    for _index in range(string_count):
        value, offset = _unpack_string(data, offset)
        strings.append(value)

    lines = []
    for _index in range(line_count):
        if offset + _LINE.size > len(data):
            raise ValueError("debug line table is truncated")
        (
            section_index,
            address,
            file_index,
            line,
            column,
        ) = _LINE.unpack_from(data, offset)
        offset += _LINE.size
        lines.append(
            DebugLineRecord(
                address,
                _get_string(strings, file_index),
                line,
                column,
                _get_string(strings, section_index),
            )
        )

    functions = []
    for _index in range(function_count):
        if offset + _FUNCTION.size > len(data):
            raise ValueError("debug function table is truncated")
        (
            section_index,
            address,
            size,
            name_index,
            frame_size,
            return_address_offset,
            previous_bp_offset,
        ) = _FUNCTION.unpack_from(data, offset)
        offset += _FUNCTION.size
        functions.append(
            DebugFunctionRecord(
                _get_string(strings, name_index),
                address,
                size,
                frame_size,
                return_address_offset,
                previous_bp_offset,
                _get_string(strings, section_index),
            )
        )
    if offset != len(data):
        raise ValueError("debug section has trailing data")

    info = StackVMDebugInfo(lines, functions)
    _validate_debug_info(info)
    return info


def merge_debug_infos(infos: Iterable[StackVMDebugInfo]) -> StackVMDebugInfo:
    lines = []
    functions = []
    for info in infos:
        lines.extend(info.lines)
        functions.extend(info.functions)
    return StackVMDebugInfo(lines, functions)


def resolve_line(
    info: StackVMDebugInfo,
    address: int,
    section: Optional[str] = None,
) -> Optional[DebugLineRecord]:
    best = None
    best_address = -1
    for record in info.lines:
        if section is not None and record.section != section:
            continue
        if record.address <= address and record.address > best_address:
            best = record
            best_address = record.address
    return best


def resolve_function(
    info: StackVMDebugInfo,
    address: int,
    section: Optional[str] = None,
) -> Optional[DebugFunctionRecord]:
    best = None
    best_address = -1
    for record in info.functions:
        if section is not None and record.section != section:
            continue
        if record.address > address:
            continue
        if record.size and address >= record.address + record.size:
            continue
        if record.address > best_address:
            best = record
            best_address = record.address
    return best


def format_addr2line(record: Optional[DebugLineRecord]) -> str:
    if record is None:
        return "??:0:0"
    return "%s:%u:%u" % (record.file, record.line, record.column)


def _read_u64(memory: Union[bytes, bytearray, memoryview], offset: int) -> Optional[int]:
    if offset < 0 or offset + 8 > len(memory):
        return None
    return int.from_bytes(memory[offset : offset + 8], "little")


def unwind_stack(
    memory: Union[bytes, bytearray, memoryview],
    base_pointer: int,
    instruction_pointer: int,
    debug_info: Optional[StackVMDebugInfo] = None,
    max_frames: int = 64,
) -> List[StackFrame]:
    frames: List[StackFrame] = []
    bp = base_pointer
    ip = instruction_pointer
    for _index in range(max_frames):
        line = None if debug_info is None else resolve_line(debug_info, ip)
        function = None if debug_info is None else resolve_function(debug_info, ip)
        return_address = (
            None
            if bp < 0 or bp >= len(memory)
            else _read_u64(
                memory,
                bp
                + (
                    DEFAULT_RETURN_ADDRESS_OFFSET
                    if function is None
                    else function.return_address_offset
                ),
            )
        )
        frames.append(
            StackFrame(
                ip,
                bp,
                None if function is None else function.name,
                None if line is None else line.file,
                None if line is None else line.line,
                None if line is None else line.column,
                return_address,
            )
        )
        if bp < 0 or bp >= len(memory):
            break
        return_offset = (
            DEFAULT_RETURN_ADDRESS_OFFSET
            if function is None
            else function.return_address_offset
        )
        previous_bp_offset = (
            DEFAULT_PREVIOUS_BP_OFFSET
            if function is None
            else function.previous_bp_offset
        )
        caller_ip = _read_u64(memory, bp + return_offset)
        caller_bp = _read_u64(memory, bp + previous_bp_offset)
        if caller_ip is None or caller_bp is None:
            break
        if caller_bp <= bp or caller_bp >= len(memory):
            break
        ip = caller_ip - 1 if caller_ip > 0 else caller_ip
        bp = caller_bp
    return frames
