from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
import struct
from typing import BinaryIO, List, Union


SBO_MAGIC = b"\xf7SVO\0\0\0\0"
SBO_VERSION = 1
SBO_HEADER_SIZE = 80
SBO_SYMBOL_ENTRY_SIZE = 40
SBO_RELOCATION_ENTRY_SIZE = 24

_HEADER = struct.Struct("<8s9Q")
_SYMBOL = struct.Struct("<QQQBBBB12s")
_RELOCATION = struct.Struct("<QQBB6s")

assert _HEADER.size == SBO_HEADER_SIZE
assert _SYMBOL.size == SBO_SYMBOL_ENTRY_SIZE
assert _RELOCATION.size == SBO_RELOCATION_ENTRY_SIZE


class ObjectSegment(IntEnum):
    CODE = 0
    DATA = 1


class SymbolBinding(IntEnum):
    LOCAL = 0
    GLOBAL = 1
    WEAK = 2


class SymbolType(IntEnum):
    NOTYPE = 0
    FUNCTION = 1
    OBJECT = 2


class SymbolFlags(IntFlag):
    NONE = 0
    UNDEFINED = 1


class RelocationType(IntEnum):
    ABS8 = 0
    PCREL8 = 1


@dataclass
class ObjectSymbol:
    name: str
    value: int
    size: int
    segment: ObjectSegment
    binding: SymbolBinding
    typ: SymbolType
    flags: SymbolFlags = SymbolFlags.NONE

    @property
    def is_undefined(self) -> bool:
        return bool(self.flags & SymbolFlags.UNDEFINED)


@dataclass
class ObjectRelocation:
    offset: int
    symbol_index: int
    segment: ObjectSegment
    typ: RelocationType


@dataclass
class StackVMObject:
    code: bytes = b""
    data: bytes = b""
    symbols: List[ObjectSymbol] = field(default_factory=list)
    relocations: List[ObjectRelocation] = field(default_factory=list)
    default_alignment: int = 0
    data_alignment: int = 1


def _is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def _validate_alignment(name: str, value: int, allow_zero: bool = False) -> None:
    if allow_zero and value == 0:
        return
    if not _is_power_of_two(value):
        raise ValueError("%s must be a power of two" % name)


def _validate_object(obj: StackVMObject) -> None:
    _validate_alignment("default alignment", obj.default_alignment, True)
    _validate_alignment("data alignment", obj.data_alignment)
    segments = {
        ObjectSegment.CODE: obj.code,
        ObjectSegment.DATA: obj.data,
    }
    for symbol in obj.symbols:
        if not isinstance(symbol.segment, ObjectSegment):
            raise ValueError("invalid symbol segment")
        if not isinstance(symbol.binding, SymbolBinding):
            raise ValueError("invalid symbol binding")
        if not isinstance(symbol.typ, SymbolType):
            raise ValueError("invalid symbol type")
        if int(symbol.flags) & ~int(SymbolFlags.UNDEFINED):
            raise ValueError("invalid symbol flags")
        if symbol.value < 0 or symbol.size < 0:
            raise ValueError("symbol value and size must be non-negative")
        if symbol.is_undefined:
            if symbol.value != 0 or symbol.size != 0:
                raise ValueError("undefined symbols must have zero value and size")
        elif symbol.value + symbol.size > len(segments[symbol.segment]):
            raise ValueError("defined symbol is outside its segment")
        if "\0" in symbol.name:
            raise ValueError("symbol names cannot contain null bytes")
        symbol.name.encode("utf-8")
    for relocation in obj.relocations:
        if not isinstance(relocation.segment, ObjectSegment):
            raise ValueError("invalid relocation segment")
        if not isinstance(relocation.typ, RelocationType):
            raise ValueError("invalid relocation type")
        if relocation.symbol_index < 0 or relocation.symbol_index >= len(obj.symbols):
            raise ValueError("relocation symbol index is out of range")
        if relocation.offset < 0 or relocation.offset + 8 > len(segments[relocation.segment]):
            raise ValueError("relocation patch is outside its segment")


def validate_object(obj: StackVMObject) -> None:
    _validate_object(obj)


def dumps_sbo(obj: StackVMObject) -> bytes:
    _validate_object(obj)
    code = bytes(obj.code)
    data = bytes(obj.data)
    string_table = bytearray()
    name_offsets = []
    for symbol in obj.symbols:
        name_offsets.append(len(string_table))
        string_table.extend(symbol.name.encode("utf-8"))
        string_table.append(0)

    symbol_table_offset = SBO_HEADER_SIZE + len(code) + len(data)
    relocation_table_offset = (
        symbol_table_offset + len(obj.symbols) * SBO_SYMBOL_ENTRY_SIZE
    )
    out = bytearray(
        _HEADER.pack(
            SBO_MAGIC,
            SBO_VERSION,
            obj.default_alignment,
            obj.data_alignment,
            len(code),
            len(data),
            symbol_table_offset,
            len(obj.symbols),
            relocation_table_offset,
            len(obj.relocations),
        )
    )
    out.extend(code)
    out.extend(data)
    for name_offset, symbol in zip(name_offsets, obj.symbols):
        out.extend(
            _SYMBOL.pack(
                name_offset,
                symbol.value,
                symbol.size,
                int(symbol.segment),
                int(symbol.binding),
                int(symbol.typ),
                int(symbol.flags),
                b"\0" * 12,
            )
        )
    for relocation in obj.relocations:
        out.extend(
            _RELOCATION.pack(
                relocation.offset,
                relocation.symbol_index,
                int(relocation.segment),
                int(relocation.typ),
                b"\0" * 6,
            )
        )
    out.extend(string_table)
    return bytes(out)


def write_sbo(obj: StackVMObject, target: Union[str, BinaryIO]) -> None:
    data = dumps_sbo(obj)
    if hasattr(target, "write"):
        target.write(data)
        return
    with open(target, "wb") as fl:
        fl.write(data)


def _decode_name(string_table: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(string_table):
        raise ValueError("symbol name offset is outside the string table")
    end = string_table.find(b"\0", offset)
    if end < 0:
        raise ValueError("symbol name is not null-terminated")
    try:
        return string_table[offset:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("symbol name is not valid UTF-8") from exc


def loads_sbo(data: bytes) -> StackVMObject:
    if len(data) < SBO_HEADER_SIZE:
        raise ValueError("object file is too short to contain a header")
    (
        magic,
        version,
        default_alignment,
        data_alignment,
        code_size,
        data_size,
        symbol_table_offset,
        symbol_count,
        relocation_table_offset,
        relocation_count,
    ) = _HEADER.unpack_from(data)
    if magic != SBO_MAGIC:
        raise ValueError("invalid .sbo magic")
    if version != SBO_VERSION:
        raise ValueError("unsupported .sbo version: %u" % version)
    _validate_alignment("default alignment", default_alignment, True)
    _validate_alignment("data alignment", data_alignment)

    expected_symbol_offset = SBO_HEADER_SIZE + code_size + data_size
    if symbol_table_offset != expected_symbol_offset:
        raise ValueError("symbol table is not at the canonical offset")
    expected_relocation_offset = (
        symbol_table_offset + symbol_count * SBO_SYMBOL_ENTRY_SIZE
    )
    if relocation_table_offset != expected_relocation_offset:
        raise ValueError("relocation table is not at the canonical offset")
    string_table_offset = (
        relocation_table_offset + relocation_count * SBO_RELOCATION_ENTRY_SIZE
    )
    if string_table_offset > len(data):
        raise ValueError("object file tables extend past the end of the file")

    code_start = SBO_HEADER_SIZE
    data_start = code_start + code_size
    code = data[code_start:data_start]
    data_segment = data[data_start:symbol_table_offset]
    string_table = data[string_table_offset:]

    symbols = []
    for index in range(symbol_count):
        offset = symbol_table_offset + index * SBO_SYMBOL_ENTRY_SIZE
        (
            name_offset,
            value,
            size,
            segment_value,
            binding_value,
            type_value,
            flags_value,
            reserved,
        ) = _SYMBOL.unpack_from(data, offset)
        if reserved != b"\0" * 12:
            raise ValueError("symbol reserved bytes must be zero")
        try:
            segment = ObjectSegment(segment_value)
            binding = SymbolBinding(binding_value)
            typ = SymbolType(type_value)
            flags = SymbolFlags(flags_value)
        except ValueError as exc:
            raise ValueError("invalid symbol enum value") from exc
        if flags_value & ~int(SymbolFlags.UNDEFINED):
            raise ValueError("invalid symbol flags")
        symbols.append(
            ObjectSymbol(
                _decode_name(string_table, name_offset),
                value,
                size,
                segment,
                binding,
                typ,
                flags,
            )
        )

    relocations = []
    for index in range(relocation_count):
        offset = relocation_table_offset + index * SBO_RELOCATION_ENTRY_SIZE
        (
            patch_offset,
            symbol_index,
            segment_value,
            type_value,
            reserved,
        ) = _RELOCATION.unpack_from(data, offset)
        if reserved != b"\0" * 6:
            raise ValueError("relocation reserved bytes must be zero")
        try:
            segment = ObjectSegment(segment_value)
            typ = RelocationType(type_value)
        except ValueError as exc:
            raise ValueError("invalid relocation enum value") from exc
        relocations.append(ObjectRelocation(patch_offset, symbol_index, segment, typ))

    obj = StackVMObject(
        code,
        data_segment,
        symbols,
        relocations,
        default_alignment,
        data_alignment,
    )
    _validate_object(obj)
    return obj


def load_sbo(source: Union[str, BinaryIO]) -> StackVMObject:
    if hasattr(source, "read"):
        return loads_sbo(source.read())
    with open(source, "rb") as fl:
        return loads_sbo(fl.read())
