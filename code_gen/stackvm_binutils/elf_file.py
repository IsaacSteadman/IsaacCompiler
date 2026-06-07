"""ELF64 read/write support for StackVM objects and executables.

The native StackVM formats (``.sbo``/``.sbc``) remain the compact internal
representation.  This module maps the same in-memory dataclasses to a small,
standard ELF64 little-endian ABI so external build systems can exchange
relocatable ``.o`` files and linked ELF images.
"""

from dataclasses import dataclass
import os
import struct
from typing import BinaryIO, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .debug_info import DEBUG_SECTION_NAME, STACKVM_DEBUG_MAGIC, loads_debug
from .executable_file import StackVMExecutable
from .object_file import (
    ObjectRelocation,
    ObjectSection,
    ObjectSegment,
    ObjectSymbol,
    RelocationType,
    SectionFlags,
    StackVMObject,
    SymbolBinding,
    SymbolFlags,
    SymbolType,
    validate_object,
)


ELF_MAGIC = b"\x7fELF"
EM_STACKVM = 0x5356

R_STACKVM_NONE = 0
R_STACKVM_64 = 1
R_STACKVM_PC64 = 2
R_STACKVM_RELATIVE = 3

EI_CLASS = 4
EI_DATA = 5
EI_VERSION = 6
ELFCLASS64 = 2
ELFDATA2LSB = 1
EV_CURRENT = 1

ET_REL = 1
ET_EXEC = 2

PT_LOAD = 1

PF_X = 1
PF_W = 2
PF_R = 4

SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_RELA = 4
SHT_NOTE = 7
SHT_NOBITS = 8

SHF_WRITE = 1
SHF_ALLOC = 2
SHF_EXECINSTR = 4

STB_LOCAL = 0
STB_GLOBAL = 1
STB_WEAK = 2

STT_NOTYPE = 0
STT_OBJECT = 1
STT_FUNC = 2
STT_SECTION = 3
STT_FILE = 4

SHN_UNDEF = 0
SHN_ABS = 0xFFF1

_ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
_SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")
_PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
_SYMBOL = struct.Struct("<IBBHQQ")
_RELA = struct.Struct("<QQq")
_NOTE_HEADER = struct.Struct("<III")
_STACKVM_NOTE_DESC = struct.Struct("<8sQQQQQQQ")
_SYMMETA_HEADER = struct.Struct("<8sQ")
_SYMMETA_ENTRY = struct.Struct("<IBBHI")

_STACKVM_NOTE_NAME = b"StackVM\0"
_STACKVM_NOTE_TYPE = 1
_STACKVM_NOTE_MAGIC = b"SVMEF\0\0\0"
_STACKVM_NOTE_VERSION = 1
_STACKVM_NOTE_OBJECT = 1
_STACKVM_NOTE_EXECUTABLE = 2
_SYMMETA_MAGIC = b"SVMSYM\0\0"

_STACKVM_META_SECTION = ".note.stackvm"
_STACKVM_SYMMETA_SECTION = ".stackvm.symmeta"


@dataclass
class _ElfSection:
    name: str
    typ: int
    flags: int = 0
    addr: int = 0
    data: bytes = b""
    size: Optional[int] = None
    align: int = 1
    entsize: int = 0
    link: int = 0
    info: int = 0
    offset: int = 0
    name_offset: int = 0

    @property
    def sh_size(self) -> int:
        if self.size is not None:
            return self.size
        return len(self.data)


@dataclass
class _ProgramHeader:
    typ: int
    flags: int
    offset: int
    vaddr: int
    filesz: int
    memsz: int
    align: int = 0x1000


class _StringTable:
    def __init__(self) -> None:
        self.data = bytearray(b"\0")
        self.offsets: Dict[str, int] = {"": 0}

    def add(self, value: str) -> int:
        offset = self.offsets.get(value)
        if offset is not None:
            return offset
        offset = len(self.data)
        self.data.extend(value.encode("utf-8"))
        self.data.append(0)
        self.offsets[value] = offset
        return offset


def _align_up(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    return (value + alignment - 1) & ~(alignment - 1)


def _is_debug_section(name: str) -> bool:
    return name == DEBUG_SECTION_NAME or name.startswith(DEBUG_SECTION_NAME + ".")


def _pad4(data: bytes) -> bytes:
    return data + b"\0" * (_align_up(len(data), 4) - len(data))


def _make_stackvm_note(
    kind: int,
    default_alignment: int = 0,
    data_alignment: int = 1,
    code_segment_end: int = 0,
    data_segment_start: int = 0,
    file_size: int = 0,
) -> bytes:
    desc = _STACKVM_NOTE_DESC.pack(
        _STACKVM_NOTE_MAGIC,
        _STACKVM_NOTE_VERSION,
        kind,
        default_alignment,
        data_alignment,
        code_segment_end,
        data_segment_start,
        file_size,
    )
    return (
        _NOTE_HEADER.pack(len(_STACKVM_NOTE_NAME), len(desc), _STACKVM_NOTE_TYPE)
        + _pad4(_STACKVM_NOTE_NAME)
        + _pad4(desc)
    )


def _parse_stackvm_note(data: bytes) -> Optional[Tuple[int, int, int, int, int, int]]:
    offset = 0
    while offset + _NOTE_HEADER.size <= len(data):
        namesz, descsz, note_type = _NOTE_HEADER.unpack_from(data, offset)
        offset += _NOTE_HEADER.size
        name_start = offset
        name_end = name_start + namesz
        offset = _align_up(name_end, 4)
        desc_start = offset
        desc_end = desc_start + descsz
        offset = _align_up(desc_end, 4)
        if desc_end > len(data):
            return None
        if data[name_start:name_end] != _STACKVM_NOTE_NAME:
            continue
        if note_type != _STACKVM_NOTE_TYPE:
            continue
        if descsz != _STACKVM_NOTE_DESC.size:
            continue
        (
            magic,
            version,
            kind,
            default_alignment,
            data_alignment,
            code_segment_end,
            data_segment_start,
            file_size,
        ) = _STACKVM_NOTE_DESC.unpack_from(data, desc_start)
        if magic != _STACKVM_NOTE_MAGIC or version != _STACKVM_NOTE_VERSION:
            continue
        return (
            kind,
            default_alignment,
            data_alignment,
            code_segment_end,
            data_segment_start,
            file_size,
        )
    return None


def _ident() -> bytes:
    ident = bytearray(16)
    ident[0:4] = ELF_MAGIC
    ident[EI_CLASS] = ELFCLASS64
    ident[EI_DATA] = ELFDATA2LSB
    ident[EI_VERSION] = EV_CURRENT
    return bytes(ident)


def _check_ident_and_header(data: bytes) -> Tuple[int, int, int, int, int, int]:
    if len(data) < _ELF_HEADER.size:
        raise ValueError("ELF file is too short to contain a header")
    (
        ident,
        e_type,
        e_machine,
        e_version,
        _entry,
        e_phoff,
        e_shoff,
        _flags,
        e_ehsize,
        e_phentsize,
        e_phnum,
        e_shentsize,
        e_shnum,
        e_shstrndx,
    ) = _ELF_HEADER.unpack_from(data)
    if ident[:4] != ELF_MAGIC:
        raise ValueError("invalid ELF magic")
    if ident[EI_CLASS] != ELFCLASS64 or ident[EI_DATA] != ELFDATA2LSB:
        raise ValueError("only ELF64 little-endian files are supported")
    if ident[EI_VERSION] != EV_CURRENT or e_version != EV_CURRENT:
        raise ValueError("unsupported ELF version")
    if e_machine != EM_STACKVM:
        raise ValueError("unsupported ELF machine: %#x" % e_machine)
    if e_ehsize != _ELF_HEADER.size:
        raise ValueError("unexpected ELF header size")
    if e_phnum and e_phentsize != _PROGRAM_HEADER.size:
        raise ValueError("unexpected ELF program-header entry size")
    if e_shnum and e_shentsize != _SECTION_HEADER.size:
        raise ValueError("unexpected ELF section-header entry size")
    return e_type, e_phoff, e_phnum, e_shoff, e_shnum, e_shstrndx


def _decode_c_string(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        raise ValueError("ELF string offset is outside its string table")
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError("ELF string is not null-terminated")
    try:
        return data[offset:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("ELF string is not valid UTF-8") from exc


def _section_flags_from_object(section: ObjectSection) -> int:
    if _is_debug_section(section.name):
        return 0
    flags = SHF_ALLOC
    if section.segment == ObjectSegment.CODE:
        flags |= SHF_EXECINSTR
    elif not section.flags & SectionFlags.READ_ONLY:
        flags |= SHF_WRITE
    return flags


def _section_flags_to_object(name: str, typ: int, flags: int) -> Tuple[ObjectSegment, SectionFlags]:
    if flags & SHF_EXECINSTR:
        segment = ObjectSegment.CODE
        section_flags = SectionFlags.EXECUTABLE
    else:
        segment = ObjectSegment.DATA
        section_flags = SectionFlags.NONE
        if not flags & SHF_WRITE:
            section_flags |= SectionFlags.READ_ONLY
    if typ == SHT_NOBITS:
        section_flags |= SectionFlags.NOBITS
    if _is_debug_section(name):
        segment = ObjectSegment.DATA
        section_flags |= SectionFlags.READ_ONLY
        section_flags &= ~SectionFlags.NOBITS
    return segment, section_flags


def _elf_symbol_binding(binding: SymbolBinding) -> int:
    if binding == SymbolBinding.LOCAL:
        return STB_LOCAL
    if binding == SymbolBinding.WEAK:
        return STB_WEAK
    return STB_GLOBAL


def _object_symbol_binding(binding: int) -> SymbolBinding:
    if binding == STB_LOCAL:
        return SymbolBinding.LOCAL
    if binding == STB_WEAK:
        return SymbolBinding.WEAK
    return SymbolBinding.GLOBAL


def _elf_symbol_type(typ: SymbolType) -> int:
    if typ == SymbolType.FUNCTION:
        return STT_FUNC
    if typ == SymbolType.OBJECT:
        return STT_OBJECT
    return STT_NOTYPE


def _object_symbol_type(typ: int) -> SymbolType:
    if typ == STT_FUNC:
        return SymbolType.FUNCTION
    if typ == STT_OBJECT:
        return SymbolType.OBJECT
    return SymbolType.NOTYPE


def _elf_relocation_type(typ: RelocationType) -> int:
    if typ == RelocationType.ABS8:
        return R_STACKVM_64
    if typ == RelocationType.PCREL8:
        return R_STACKVM_PC64
    raise ValueError("unsupported StackVM relocation type: %r" % (typ,))


def _object_relocation_type(typ: int) -> RelocationType:
    if typ == R_STACKVM_64:
        return RelocationType.ABS8
    if typ == R_STACKVM_PC64:
        return RelocationType.PCREL8
    raise ValueError("unsupported StackVM ELF relocation type: %r" % (typ,))


def _read_i64(memory: bytes, offset: int) -> int:
    return int.from_bytes(memory[offset : offset + 8], "little", signed=True)


def _write_i64(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 8] = (value & ((1 << 64) - 1)).to_bytes(8, "little")


def _uleb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _sleb(value: int) -> bytes:
    out = bytearray()
    more = True
    while more:
        byte = value & 0x7F
        value >>= 7
        sign = byte & 0x40
        if (value == 0 and not sign) or (value == -1 and sign):
            more = False
        else:
            byte |= 0x80
        out.append(byte)
    return bytes(out)


class _DwarfStrings:
    def __init__(self) -> None:
        self.data = bytearray(b"\0")
        self.offsets: Dict[str, int] = {"": 0}

    def add(self, value: str) -> int:
        offset = self.offsets.get(value)
        if offset is not None:
            return offset
        offset = len(self.data)
        self.data.extend(value.encode("utf-8", "replace"))
        self.data.append(0)
        self.offsets[value] = offset
        return offset


def _dwarf_abbrev() -> bytes:
    # DWARF v4 abbrev table:
    #   1: compile_unit with children
    #   2: subprogram without children
    out = bytearray()
    out.extend(_uleb(1))
    out.extend(_uleb(0x11))  # DW_TAG_compile_unit
    out.append(1)  # DW_CHILDREN_yes
    for attr, form in (
        (0x25, 0x0E),  # DW_AT_producer, DW_FORM_strp
        (0x13, 0x05),  # DW_AT_language, DW_FORM_data2
        (0x03, 0x0E),  # DW_AT_name, DW_FORM_strp
        (0x1B, 0x0E),  # DW_AT_comp_dir, DW_FORM_strp
        (0x11, 0x01),  # DW_AT_low_pc, DW_FORM_addr
        (0x12, 0x01),  # DW_AT_high_pc, DW_FORM_addr
        (0x10, 0x17),  # DW_AT_stmt_list, DW_FORM_sec_offset
    ):
        out.extend(_uleb(attr))
        out.extend(_uleb(form))
    out.extend(b"\0\0")
    out.extend(_uleb(2))
    out.extend(_uleb(0x2E))  # DW_TAG_subprogram
    out.append(0)  # DW_CHILDREN_no
    for attr, form in (
        (0x03, 0x0E),  # DW_AT_name, DW_FORM_strp
        (0x11, 0x01),  # DW_AT_low_pc, DW_FORM_addr
        (0x12, 0x01),  # DW_AT_high_pc, DW_FORM_addr
        (0x3F, 0x0B),  # DW_AT_external, DW_FORM_data1
    ):
        out.extend(_uleb(attr))
        out.extend(_uleb(form))
    out.extend(b"\0\0")
    out.append(0)
    return bytes(out)


def _dwarf_info(debug_payload: bytes, strings: _DwarfStrings) -> bytes:
    info = loads_debug(debug_payload)
    all_addresses = [record.address for record in info.lines]
    for function in info.functions:
        all_addresses.append(function.address)
        all_addresses.append(function.address + function.size)
    low_pc = min(all_addresses) if all_addresses else 0
    high_pc = max(all_addresses) if all_addresses else 0
    first_file = info.lines[0].file if info.lines else ""
    cu_name = os.path.basename(first_file) if first_file else "stackvm"
    comp_dir = os.path.dirname(first_file) if first_file else ""

    body = bytearray()
    body.append(1)
    body.extend(struct.pack("<I", strings.add("IsaacCompiler StackVM ELF")))
    body.extend(struct.pack("<H", 0x001D))  # DW_LANG_C11
    body.extend(struct.pack("<I", strings.add(cu_name)))
    body.extend(struct.pack("<I", strings.add(comp_dir)))
    body.extend(struct.pack("<QQI", low_pc, high_pc, 0))
    for function in info.functions:
        body.append(2)
        body.extend(struct.pack("<I", strings.add(function.name)))
        body.extend(
            struct.pack(
                "<QQB",
                function.address,
                function.address + function.size,
                1,
            )
        )
    body.append(0)
    # The actual unit header is emitted below after the length is known:
    # unit_length, version, abbrev_offset, address_size.
    header = struct.pack("<HI B".replace(" ", ""), 4, 0, 8)
    return struct.pack("<I", len(header) + len(body)) + header + bytes(body)


def _dwarf_line(debug_payload: bytes) -> bytes:
    info = loads_debug(debug_payload)
    lines = sorted(
        info.lines,
        key=lambda record: (record.address, record.file, record.line),
    )
    files = []
    seen = set()
    for record in lines:
        if record.file not in seen:
            seen.add(record.file)
            files.append(record.file)
    file_index = {name: index + 1 for index, name in enumerate(files)}

    header = bytearray()
    header.append(1)  # minimum_instruction_length
    header.append(1)  # maximum_operations_per_instruction
    header.append(1)  # default_is_stmt
    header.extend(struct.pack("<bBB", -5, 14, 13))
    header.extend(bytes([0, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1]))
    header.append(0)  # include_directories terminator
    for path in files:
        header.extend(path.encode("utf-8", "replace") + b"\0")
        header.extend(_uleb(0))  # directory index
        header.extend(_uleb(0))  # mtime
        header.extend(_uleb(0))  # size
    header.append(0)

    program = bytearray()
    cur_line = 1
    cur_file = 1
    for record in lines:
        program.extend(b"\0")
        program.extend(_uleb(1 + 8))
        program.append(2)  # DW_LNE_set_address
        program.extend(struct.pack("<Q", record.address))
        next_file = file_index[record.file]
        if next_file != cur_file:
            program.append(4)  # DW_LNS_set_file
            program.extend(_uleb(next_file))
            cur_file = next_file
        delta = record.line - cur_line
        if delta:
            program.append(3)  # DW_LNS_advance_line
            program.extend(_sleb(delta))
            cur_line = record.line
        program.append(1)  # DW_LNS_copy
    program.extend(b"\0")
    program.extend(_uleb(1))
    program.append(1)  # DW_LNE_end_sequence

    unit_body = (
        struct.pack("<H", 4)
        + struct.pack("<I", len(header))
        + bytes(header)
        + bytes(program)
    )
    return struct.pack("<I", len(unit_body)) + unit_body


def _dwarf_sections(debug_payload: bytes) -> List[_ElfSection]:
    if not debug_payload.startswith(STACKVM_DEBUG_MAGIC):
        return []
    try:
        strings = _DwarfStrings()
        debug_info = _dwarf_info(debug_payload, strings)
        debug_line = _dwarf_line(debug_payload)
    except ValueError:
        return []
    return [
        _ElfSection(".debug_abbrev", SHT_PROGBITS, 0, 0, _dwarf_abbrev(), align=1),
        _ElfSection(".debug_info", SHT_PROGBITS, 0, 0, debug_info, align=1),
        _ElfSection(".debug_line", SHT_PROGBITS, 0, 0, debug_line, align=1),
        _ElfSection(".debug_str", SHT_PROGBITS, 0, 0, bytes(strings.data), align=1),
    ]


def _needs_legacy_section(
    obj: StackVMObject,
    segment: ObjectSegment,
    data: bytes,
) -> bool:
    return (
        bool(data)
        or any(not symbol.is_undefined and symbol.segment == segment for symbol in obj.symbols)
        or any(relocation.segment == segment for relocation in obj.relocations)
    )


def _object_with_sections_for_elf(obj: StackVMObject) -> StackVMObject:
    validate_object(obj)
    if obj.sections:
        return obj
    sections: List[ObjectSection] = []
    code_index = None
    data_index = None
    if _needs_legacy_section(obj, ObjectSegment.CODE, obj.code):
        code_index = len(sections)
        sections.append(
            ObjectSection(
                ".text",
                0,
                len(obj.code),
                1,
                ObjectSegment.CODE,
                SectionFlags.EXECUTABLE,
            )
        )
    if _needs_legacy_section(obj, ObjectSegment.DATA, obj.data):
        data_index = len(sections)
        sections.append(
            ObjectSection(
                ".data",
                0,
                len(obj.data),
                obj.data_alignment,
                ObjectSegment.DATA,
                SectionFlags.NONE,
            )
        )
    symbols = []
    for symbol in obj.symbols:
        if symbol.is_undefined:
            section_index = None
        elif symbol.segment == ObjectSegment.CODE:
            section_index = code_index
        else:
            section_index = data_index
        symbols.append(
            ObjectSymbol(
                symbol.name,
                symbol.value,
                symbol.size,
                symbol.segment,
                symbol.binding,
                symbol.typ,
                symbol.flags,
                section_index,
            )
        )
    relocations = []
    for relocation in obj.relocations:
        section_index = code_index if relocation.segment == ObjectSegment.CODE else data_index
        relocations.append(
            ObjectRelocation(
                relocation.offset,
                relocation.symbol_index,
                relocation.segment,
                relocation.typ,
                section_index,
            )
        )
    normalized = StackVMObject(
        obj.code,
        obj.data,
        symbols,
        relocations,
        obj.default_alignment,
        obj.data_alignment,
        sections,
    )
    validate_object(normalized)
    return normalized


def _make_symmeta(symbol_order: Sequence[int], obj: StackVMObject) -> bytes:
    out = bytearray(_SYMMETA_HEADER.pack(_SYMMETA_MAGIC, len(symbol_order)))
    for original_index in symbol_order:
        symbol = obj.symbols[original_index]
        out.extend(
            _SYMMETA_ENTRY.pack(
                original_index,
                int(symbol.segment),
                int(symbol.flags),
                0,
                0,
            )
        )
    return bytes(out)


def _parse_symmeta(data: bytes) -> Dict[int, Tuple[int, ObjectSegment, SymbolFlags]]:
    if len(data) < _SYMMETA_HEADER.size:
        return {}
    magic, count = _SYMMETA_HEADER.unpack_from(data)
    if magic != _SYMMETA_MAGIC:
        return {}
    expected = _SYMMETA_HEADER.size + count * _SYMMETA_ENTRY.size
    if expected != len(data):
        return {}
    result = {}
    offset = _SYMMETA_HEADER.size
    for index in range(count):
        original_index, segment_value, flags_value, _reserved16, _reserved32 = (
            _SYMMETA_ENTRY.unpack_from(data, offset)
        )
        offset += _SYMMETA_ENTRY.size
        try:
            segment = ObjectSegment(segment_value)
            flags = SymbolFlags(flags_value)
        except ValueError:
            continue
        result[index + 1] = (original_index, segment, flags)
    return result


def dumps_elf_object(obj: StackVMObject) -> bytes:
    obj = _object_with_sections_for_elf(obj)
    strtab = _StringTable()
    shstrtab = _StringTable()

    sections: List[_ElfSection] = [_ElfSection("", SHT_NULL)]
    object_section_to_elf_index: Dict[int, int] = {}

    for section_index, section in enumerate(obj.sections):
        segment_data = obj.code if section.segment == ObjectSegment.CODE else obj.data
        section_data = (
            b""
            if section.is_nobits
            else segment_data[section.offset : section.offset + section.size]
        )
        object_section_to_elf_index[section_index] = len(sections)
        sections.append(
            _ElfSection(
                section.name,
                SHT_NOBITS if section.is_nobits else SHT_PROGBITS,
                _section_flags_from_object(section),
                0,
                section_data,
                section.size,
                section.alignment,
            )
        )

    symbol_order = sorted(
        range(len(obj.symbols)),
        key=lambda index: (
            obj.symbols[index].binding != SymbolBinding.LOCAL,
            index,
        ),
    )
    elf_symbol_index: Dict[int, int] = {
        object_index: index + 1 for index, object_index in enumerate(symbol_order)
    }
    local_count = sum(
        1 for index in symbol_order if obj.symbols[index].binding == SymbolBinding.LOCAL
    )
    symtab = bytearray(_SYMBOL.pack(0, 0, 0, SHN_UNDEF, 0, 0))
    for object_index in symbol_order:
        symbol = obj.symbols[object_index]
        st_name = strtab.add(symbol.name)
        st_info = (_elf_symbol_binding(symbol.binding) << 4) | _elf_symbol_type(symbol.typ)
        if symbol.is_undefined:
            st_shndx = SHN_UNDEF
            st_value = 0
        else:
            if symbol.section_index is None:
                raise ValueError("defined ELF symbols must have a section")
            st_shndx = object_section_to_elf_index[symbol.section_index]
            st_value = symbol.value - obj.sections[symbol.section_index].offset
        symtab.extend(_SYMBOL.pack(st_name, st_info, 0, st_shndx, st_value, symbol.size))

    relocation_sections: Dict[int, bytearray] = {}
    for relocation in obj.relocations:
        if relocation.section_index is None:
            raise ValueError("ELF relocations must reference a section")
        target_section = obj.sections[relocation.section_index]
        target_elf_index = object_section_to_elf_index[relocation.section_index]
        segment_data = obj.code if relocation.segment == ObjectSegment.CODE else obj.data
        r_offset = relocation.offset - target_section.offset
        r_type = _elf_relocation_type(relocation.typ)
        r_sym = elf_symbol_index[relocation.symbol_index]
        r_info = (r_sym << 32) | r_type
        r_addend = _read_i64(segment_data, relocation.offset)
        relocation_sections.setdefault(target_elf_index, bytearray()).extend(
            _RELA.pack(r_offset, r_info, r_addend)
        )

    symmeta_index = len(sections)
    sections.append(
        _ElfSection(
            _STACKVM_SYMMETA_SECTION,
            SHT_PROGBITS,
            0,
            0,
            _make_symmeta(symbol_order, obj),
            align=1,
        )
    )
    note_index = len(sections)
    sections.append(
        _ElfSection(
            _STACKVM_META_SECTION,
            SHT_NOTE,
            0,
            0,
            _make_stackvm_note(
                _STACKVM_NOTE_OBJECT,
                obj.default_alignment,
                obj.data_alignment,
            ),
            align=4,
        )
    )
    _ = symmeta_index, note_index

    rela_indices = []
    for target_elf_index, data in sorted(relocation_sections.items()):
        rela_indices.append(len(sections))
        sections.append(
            _ElfSection(
                ".rela" + sections[target_elf_index].name,
                SHT_RELA,
                0,
                0,
                bytes(data),
                align=8,
                entsize=_RELA.size,
                info=target_elf_index,
            )
        )

    symtab_index = len(sections)
    sections.append(
        _ElfSection(
            ".symtab",
            SHT_SYMTAB,
            0,
            0,
            bytes(symtab),
            align=8,
            entsize=_SYMBOL.size,
            info=local_count + 1,
        )
    )
    strtab_index = len(sections)
    sections.append(_ElfSection(".strtab", SHT_STRTAB, 0, 0, bytes(strtab.data), align=1))
    shstrtab_index = len(sections)
    sections.append(_ElfSection(".shstrtab", SHT_STRTAB, 0, 0, b"", align=1))
    sections[symtab_index].link = strtab_index
    for rela_index in rela_indices:
        sections[rela_index].link = symtab_index

    return _finalize_elf(ET_REL, sections, [], 0, shstrtab, shstrtab_index)


def write_elf_object(obj: StackVMObject, target: Union[str, BinaryIO]) -> None:
    data = dumps_elf_object(obj)
    if hasattr(target, "write"):
        target.write(data)
        return
    with open(target, "wb") as fl:
        fl.write(data)


def _read_section_headers(data: bytes, e_shoff: int, e_shnum: int) -> List[dict]:
    if e_shoff == 0 and e_shnum == 0:
        return []
    end = e_shoff + e_shnum * _SECTION_HEADER.size
    if end > len(data):
        raise ValueError("ELF section headers extend past end of file")
    headers = []
    for index in range(e_shnum):
        offset = e_shoff + index * _SECTION_HEADER.size
        (
            sh_name,
            sh_type,
            sh_flags,
            sh_addr,
            sh_offset,
            sh_size,
            sh_link,
            sh_info,
            sh_addralign,
            sh_entsize,
        ) = _SECTION_HEADER.unpack_from(data, offset)
        if sh_type != SHT_NOBITS and sh_offset + sh_size > len(data):
            raise ValueError("ELF section payload extends past end of file")
        headers.append(
            {
                "name_offset": sh_name,
                "type": sh_type,
                "flags": sh_flags,
                "addr": sh_addr,
                "offset": sh_offset,
                "size": sh_size,
                "link": sh_link,
                "info": sh_info,
                "align": max(1, sh_addralign),
                "entsize": sh_entsize,
                "name": "",
            }
        )
    return headers


def _attach_section_names(data: bytes, headers: List[dict], shstrndx: int) -> None:
    if not headers:
        return
    if shstrndx >= len(headers):
        raise ValueError("ELF section-name string table index is out of range")
    shstr = headers[shstrndx]
    if shstr["type"] != SHT_STRTAB:
        raise ValueError("ELF section-name table is not a string table")
    shstr_data = data[shstr["offset"] : shstr["offset"] + shstr["size"]]
    for header in headers:
        header["name"] = _decode_c_string(shstr_data, header["name_offset"])


def _section_payload(data: bytes, header: dict) -> bytes:
    if header["type"] == SHT_NOBITS:
        return b""
    return data[header["offset"] : header["offset"] + header["size"]]


def loads_elf_object(data: bytes) -> StackVMObject:
    e_type, _phoff, _phnum, e_shoff, e_shnum, e_shstrndx = _check_ident_and_header(data)
    if e_type != ET_REL:
        raise ValueError("ELF file is not a relocatable StackVM object")
    headers = _read_section_headers(data, e_shoff, e_shnum)
    _attach_section_names(data, headers, e_shstrndx)

    note = None
    symmeta: Dict[int, Tuple[int, ObjectSegment, SymbolFlags]] = {}
    for header in headers:
        if header["name"] == _STACKVM_META_SECTION:
            note = _parse_stackvm_note(_section_payload(data, header))
        elif header["name"] == _STACKVM_SYMMETA_SECTION:
            symmeta = _parse_symmeta(_section_payload(data, header))
    default_alignment = 0
    data_alignment = 1
    if note is not None and note[0] == _STACKVM_NOTE_OBJECT:
        default_alignment = note[1]
        data_alignment = note[2]

    support_section_names = {
        "",
        ".symtab",
        ".strtab",
        ".shstrtab",
        _STACKVM_META_SECTION,
        _STACKVM_SYMMETA_SECTION,
    }
    object_elf_indices = []
    for index, header in enumerate(headers):
        if header["name"] in support_section_names:
            continue
        if header["type"] == SHT_RELA:
            continue
        if header["type"] not in {SHT_PROGBITS, SHT_NOBITS}:
            continue
        object_elf_indices.append(index)

    section_infos = []
    for elf_index in object_elf_indices:
        header = headers[elf_index]
        segment, flags = _section_flags_to_object(
            header["name"],
            header["type"],
            header["flags"],
        )
        section_infos.append((elf_index, header, segment, flags))

    section_offsets: Dict[int, int] = {}
    object_section_index_by_elf: Dict[int, int] = {}
    code = bytearray()
    data_segment = bytearray()
    sections: List[ObjectSection] = []
    for segment, blob in (
        (ObjectSegment.CODE, code),
        (ObjectSegment.DATA, data_segment),
    ):
        logical_end = len(blob)
        for elf_index, header, sec_segment, flags in section_infos:
            if sec_segment != segment or flags & SectionFlags.NOBITS:
                continue
            offset = _align_up(len(blob), header["align"])
            blob.extend(b"\0" * (offset - len(blob)))
            section_offsets[elf_index] = offset
            blob.extend(_section_payload(data, header))
        logical_end = len(blob)
        for elf_index, header, sec_segment, flags in section_infos:
            if sec_segment != segment or not flags & SectionFlags.NOBITS:
                continue
            logical_end = _align_up(logical_end, header["align"])
            section_offsets[elf_index] = logical_end
            logical_end += header["size"]

    for elf_index, header, segment, flags in section_infos:
        object_section_index_by_elf[elf_index] = len(sections)
        sections.append(
            ObjectSection(
                header["name"],
                section_offsets[elf_index],
                header["size"],
                header["align"],
                segment,
                flags,
            )
        )

    symtab_header = next((header for header in headers if header["type"] == SHT_SYMTAB), None)
    symbols: List[ObjectSymbol] = []
    object_symbol_index_by_elf: Dict[int, int] = {}
    pending_symbols = []
    if symtab_header is not None:
        if symtab_header["entsize"] not in {0, _SYMBOL.size}:
            raise ValueError("unsupported ELF symbol entry size")
        if symtab_header["link"] >= len(headers):
            raise ValueError("ELF symbol table string-table link is out of range")
        strtab_header = headers[symtab_header["link"]]
        strtab = _section_payload(data, strtab_header)
        symtab_data = _section_payload(data, symtab_header)
        if len(symtab_data) % _SYMBOL.size:
            raise ValueError("ELF symbol table is truncated")
        for elf_symbol_index in range(1, len(symtab_data) // _SYMBOL.size):
            offset = elf_symbol_index * _SYMBOL.size
            st_name, st_info, _st_other, st_shndx, st_value, st_size = _SYMBOL.unpack_from(
                symtab_data,
                offset,
            )
            typ = st_info & 0xF
            if typ in {STT_SECTION, STT_FILE}:
                continue
            name = _decode_c_string(strtab, st_name)
            if not name:
                continue
            binding = _object_symbol_binding(st_info >> 4)
            symbol_type = _object_symbol_type(typ)
            meta = symmeta.get(elf_symbol_index)
            original_index = meta[0] if meta is not None else len(pending_symbols)
            if st_shndx == SHN_UNDEF:
                segment = meta[1] if meta is not None else ObjectSegment.CODE
                flags = SymbolFlags.UNDEFINED
                value = 0
                size = 0
                section_index = None
            else:
                if st_shndx not in object_section_index_by_elf:
                    continue
                section_index = object_section_index_by_elf[st_shndx]
                section = sections[section_index]
                segment = section.segment
                flags = SymbolFlags.NONE
                value = section.offset + st_value
                size = st_size
            pending_symbols.append(
                (
                    original_index,
                    elf_symbol_index,
                    ObjectSymbol(
                        name,
                        value,
                        size,
                        segment,
                        binding,
                        symbol_type,
                        flags,
                        section_index,
                    ),
                )
            )
    pending_symbols.sort(key=lambda item: item[0])
    for new_index, (_original, elf_symbol_index, symbol) in enumerate(pending_symbols):
        symbols.append(symbol)
        object_symbol_index_by_elf[elf_symbol_index] = new_index

    relocations: List[ObjectRelocation] = []
    for header in headers:
        if header["type"] != SHT_RELA:
            continue
        target_elf_index = header["info"]
        if target_elf_index not in object_section_index_by_elf:
            continue
        if header["entsize"] not in {0, _RELA.size}:
            raise ValueError("unsupported ELF relocation entry size")
        target_section = sections[object_section_index_by_elf[target_elf_index]]
        payload = _section_payload(data, header)
        if len(payload) % _RELA.size:
            raise ValueError("ELF relocation section is truncated")
        for offset in range(0, len(payload), _RELA.size):
            r_offset, r_info, r_addend = _RELA.unpack_from(payload, offset)
            elf_symbol_index = r_info >> 32
            r_type = r_info & 0xFFFFFFFF
            if elf_symbol_index not in object_symbol_index_by_elf:
                raise ValueError("ELF relocation references an unknown symbol")
            relocation_offset = target_section.offset + r_offset
            blob = code if target_section.segment == ObjectSegment.CODE else data_segment
            _write_i64(blob, relocation_offset, r_addend)
            relocations.append(
                ObjectRelocation(
                    relocation_offset,
                    object_symbol_index_by_elf[elf_symbol_index],
                    target_section.segment,
                    _object_relocation_type(r_type),
                    object_section_index_by_elf[target_elf_index],
                )
            )

    obj = StackVMObject(
        bytes(code),
        bytes(data_segment),
        symbols,
        relocations,
        default_alignment,
        data_alignment,
        sections,
    )
    validate_object(obj)
    return obj


def load_elf_object(source: Union[str, BinaryIO]) -> StackVMObject:
    if hasattr(source, "read"):
        return loads_elf_object(source.read())
    with open(source, "rb") as fl:
        return loads_elf_object(fl.read())


def _section_flags_for_executable(name: str, segment: ObjectSegment) -> int:
    if _is_debug_section(name):
        return 0
    flags = SHF_ALLOC
    if segment == ObjectSegment.CODE:
        flags |= SHF_EXECINSTR
    elif not (name == ".rodata" or name.startswith(".rodata.")):
        flags |= SHF_WRITE
    return flags


def _layout_sections_from_executable(
    executable: StackVMExecutable,
    section_layouts: Optional[Sequence[object]],
) -> List[_ElfSection]:
    memory = bytes(executable.memory)
    file_size = len(memory) if executable.file_size is None else executable.file_size
    result: List[_ElfSection] = []
    if section_layouts is None:
        if executable.code_segment_end:
            result.append(
                _ElfSection(
                    ".text",
                    SHT_PROGBITS,
                    SHF_ALLOC | SHF_EXECINSTR,
                    0,
                    memory[: executable.code_segment_end],
                    executable.code_segment_end,
                    1,
                )
            )
        if file_size > executable.data_segment_start:
            result.append(
                _ElfSection(
                    ".data",
                    SHT_PROGBITS,
                    SHF_ALLOC | SHF_WRITE,
                    executable.data_segment_start,
                    memory[executable.data_segment_start : file_size],
                    file_size - executable.data_segment_start,
                    1,
                )
            )
        if len(memory) > file_size:
            result.append(
                _ElfSection(
                    ".bss",
                    SHT_NOBITS,
                    SHF_ALLOC | SHF_WRITE,
                    file_size,
                    b"",
                    len(memory) - file_size,
                    1,
                )
            )
        return result

    for layout in section_layouts:
        name = layout.name
        segment = layout.segment
        typ = SHT_NOBITS if name == ".bss" and layout.size > 0 else SHT_PROGBITS
        if typ == SHT_NOBITS:
            data = b""
        else:
            data = memory[layout.address : layout.address + layout.size]
        result.append(
            _ElfSection(
                name,
                typ,
                _section_flags_for_executable(name, segment),
                layout.address,
                data,
                layout.size,
                1,
            )
        )
    return result


def _symbol_section_index(symbol: object, sections: Sequence[_ElfSection]) -> int:
    section_name = getattr(symbol, "section_name", "")
    if section_name:
        for index, section in enumerate(sections):
            if section.name == section_name:
                return index
    address = getattr(symbol, "address", 0)
    for index, section in enumerate(sections):
        if section.flags & SHF_ALLOC and section.addr <= address < section.addr + section.sh_size:
            return index
    return SHN_ABS


def _make_exec_symtab(
    symbols: Optional[Sequence[object]],
    sections: Sequence[_ElfSection],
) -> Tuple[bytes, bytes, int]:
    strtab = _StringTable()
    if not symbols:
        return _SYMBOL.pack(0, 0, 0, SHN_UNDEF, 0, 0), bytes(strtab.data), 1
    ordered = sorted(
        range(len(symbols)),
        key=lambda index: (
            getattr(symbols[index], "binding", SymbolBinding.GLOBAL)
            != SymbolBinding.LOCAL,
            getattr(symbols[index], "address", 0),
            getattr(symbols[index], "name", ""),
        ),
    )
    local_count = sum(
        1
        for index in ordered
        if getattr(symbols[index], "binding", SymbolBinding.GLOBAL)
        == SymbolBinding.LOCAL
    )
    symtab = bytearray(_SYMBOL.pack(0, 0, 0, SHN_UNDEF, 0, 0))
    for index in ordered:
        symbol = symbols[index]
        binding = getattr(symbol, "binding", SymbolBinding.GLOBAL)
        typ = getattr(symbol, "typ", SymbolType.NOTYPE)
        st_info = (_elf_symbol_binding(binding) << 4) | _elf_symbol_type(typ)
        st_shndx = _symbol_section_index(symbol, sections)
        if st_shndx != SHN_ABS:
            st_shndx += 1
        symtab.extend(
            _SYMBOL.pack(
                strtab.add(getattr(symbol, "name", "")),
                st_info,
                0,
                st_shndx,
                getattr(symbol, "address", 0),
                getattr(symbol, "size", 0),
            )
        )
    return bytes(symtab), bytes(strtab.data), local_count + 1


def dumps_elf_executable(
    executable: StackVMExecutable,
    section_layouts: Optional[Sequence[object]] = None,
    symbols: Optional[Sequence[object]] = None,
) -> bytes:
    memory = bytes(executable.memory)
    file_size = len(memory) if executable.file_size is None else executable.file_size
    sections: List[_ElfSection] = [_ElfSection("", SHT_NULL)]
    alloc_sections = _layout_sections_from_executable(executable, section_layouts)
    sections.extend(alloc_sections)

    code_filesz = min(executable.code_segment_end, file_size)
    data_filesz = max(0, file_size - executable.data_segment_start)
    phdrs: List[_ProgramHeader] = []
    if executable.code_segment_end:
        phdrs.append(
            _ProgramHeader(
                PT_LOAD,
                PF_R | PF_X,
                0,
                0,
                code_filesz,
                executable.code_segment_end,
            )
        )
    if len(memory) > executable.data_segment_start:
        phdrs.append(
            _ProgramHeader(
                PT_LOAD,
                PF_R | PF_W,
                0,
                executable.data_segment_start,
                data_filesz,
                len(memory) - executable.data_segment_start,
            )
        )

    if executable.base_relocations:
        rela = bytearray()
        for offset in executable.base_relocations:
            addend = _read_i64(memory, offset)
            rela.extend(_RELA.pack(offset, R_STACKVM_RELATIVE, addend))
        sections.append(
            _ElfSection(
                ".rela.dyn",
                SHT_RELA,
                0,
                0,
                bytes(rela),
                align=8,
                entsize=_RELA.size,
            )
        )

    if executable.debug_info:
        sections.append(
            _ElfSection(
                DEBUG_SECTION_NAME + ".stackvm",
                SHT_PROGBITS,
                0,
                0,
                bytes(executable.debug_info),
                align=1,
            )
        )
        sections.extend(_dwarf_sections(bytes(executable.debug_info)))

    sections.append(
        _ElfSection(
            _STACKVM_META_SECTION,
            SHT_NOTE,
            0,
            0,
            _make_stackvm_note(
                _STACKVM_NOTE_EXECUTABLE,
                0,
                1,
                executable.code_segment_end,
                executable.data_segment_start,
                file_size,
            ),
            align=4,
        )
    )

    symtab, strtab, sym_info = _make_exec_symtab(symbols, alloc_sections)
    symtab_index = len(sections)
    sections.append(
        _ElfSection(
            ".symtab",
            SHT_SYMTAB,
            0,
            0,
            symtab,
            align=8,
            entsize=_SYMBOL.size,
            info=sym_info,
        )
    )
    strtab_index = len(sections)
    sections.append(_ElfSection(".strtab", SHT_STRTAB, 0, 0, strtab, align=1))
    sections[symtab_index].link = strtab_index
    for section in sections:
        if section.typ == SHT_RELA:
            section.link = symtab_index

    shstrtab = _StringTable()
    shstrtab_index = len(sections)
    sections.append(_ElfSection(".shstrtab", SHT_STRTAB, 0, 0, b"", align=1))

    entry = 0
    if symbols:
        for symbol in symbols:
            if getattr(symbol, "name", "") == "_start":
                entry = getattr(symbol, "address", 0)
                break

    return _finalize_elf(
        ET_EXEC,
        sections,
        phdrs,
        entry,
        shstrtab,
        shstrtab_index,
        memory,
        executable.code_segment_end,
        executable.data_segment_start,
        file_size,
    )


def write_elf_executable(
    executable: StackVMExecutable,
    target: Union[str, BinaryIO],
    section_layouts: Optional[Sequence[object]] = None,
    symbols: Optional[Sequence[object]] = None,
) -> None:
    data = dumps_elf_executable(executable, section_layouts, symbols)
    if hasattr(target, "write"):
        target.write(data)
        return
    with open(target, "wb") as fl:
        fl.write(data)


def _finalize_elf(
    e_type: int,
    sections: List[_ElfSection],
    phdrs: List[_ProgramHeader],
    entry: int,
    shstrtab: _StringTable,
    shstrtab_index: int,
    memory: bytes = b"",
    code_segment_end: int = 0,
    data_segment_start: int = 0,
    file_size: int = 0,
) -> bytes:
    for section in sections:
        section.name_offset = shstrtab.add(section.name)
    sections[shstrtab_index].data = bytes(shstrtab.data)
    sections[shstrtab_index].size = len(sections[shstrtab_index].data)

    offset = _ELF_HEADER.size + len(phdrs) * _PROGRAM_HEADER.size
    if e_type == ET_EXEC:
        offset = _align_up(offset, 0x1000)
        for phdr in phdrs:
            if phdr.vaddr == 0:
                phdr.offset = offset
                offset += phdr.filesz
            else:
                offset = _align_up(offset, phdr.align)
                phdr.offset = offset
                offset += phdr.filesz
        out = bytearray(b"\0" * offset)
        for phdr in phdrs:
            if phdr.filesz == 0:
                continue
            src_start = phdr.vaddr
            src_end = src_start + phdr.filesz
            out[phdr.offset : phdr.offset + phdr.filesz] = memory[src_start:src_end]
        for section in sections:
            if section.flags & SHF_ALLOC:
                if section.typ == SHT_NOBITS:
                    section.offset = 0
                elif section.addr < data_segment_start:
                    section.offset = phdrs[0].offset + section.addr
                else:
                    data_phdr = next(
                        (phdr for phdr in phdrs if phdr.vaddr == data_segment_start),
                        None,
                    )
                    if data_phdr is None:
                        section.offset = 0
                    else:
                        section.offset = data_phdr.offset + section.addr - data_segment_start
            elif section.typ != SHT_NULL:
                offset = _align_up(len(out), section.align)
                out.extend(b"\0" * (offset - len(out)))
                section.offset = offset
                out.extend(section.data)
    else:
        out = bytearray(b"\0" * _ELF_HEADER.size)
        for section in sections:
            if section.typ == SHT_NULL:
                continue
            offset = _align_up(len(out), section.align)
            out.extend(b"\0" * (offset - len(out)))
            section.offset = offset
            if section.typ != SHT_NOBITS:
                out.extend(section.data)

    shoff = _align_up(len(out), 8)
    out.extend(b"\0" * (shoff - len(out)))
    for section in sections:
        out.extend(
            _SECTION_HEADER.pack(
                section.name_offset,
                section.typ,
                section.flags,
                section.addr,
                section.offset,
                section.sh_size,
                section.link,
                section.info,
                section.align,
                section.entsize,
            )
        )

    phoff = _ELF_HEADER.size if phdrs else 0
    header = _ELF_HEADER.pack(
        _ident(),
        e_type,
        EM_STACKVM,
        EV_CURRENT,
        entry,
        phoff,
        shoff,
        0,
        _ELF_HEADER.size,
        _PROGRAM_HEADER.size if phdrs else 0,
        len(phdrs),
        _SECTION_HEADER.size,
        len(sections),
        shstrtab_index,
    )
    out[: _ELF_HEADER.size] = header
    for index, phdr in enumerate(phdrs):
        out[
            _ELF_HEADER.size
            + index * _PROGRAM_HEADER.size : _ELF_HEADER.size
            + (index + 1) * _PROGRAM_HEADER.size
        ] = _PROGRAM_HEADER.pack(
            phdr.typ,
            phdr.flags,
            phdr.offset,
            phdr.vaddr,
            phdr.vaddr,
            phdr.filesz,
            phdr.memsz,
            phdr.align,
        )
    return bytes(out)


def loads_elf_executable(data: bytes) -> StackVMExecutable:
    e_type, e_phoff, e_phnum, e_shoff, e_shnum, e_shstrndx = _check_ident_and_header(data)
    if e_type != ET_EXEC:
        raise ValueError("ELF file is not a StackVM executable")
    phdrs = []
    for index in range(e_phnum):
        offset = e_phoff + index * _PROGRAM_HEADER.size
        if offset + _PROGRAM_HEADER.size > len(data):
            raise ValueError("ELF program headers extend past end of file")
        (
            p_type,
            p_flags,
            p_offset,
            p_vaddr,
            _p_paddr,
            p_filesz,
            p_memsz,
            _p_align,
        ) = _PROGRAM_HEADER.unpack_from(data, offset)
        if p_type != PT_LOAD:
            continue
        if p_offset + p_filesz > len(data):
            raise ValueError("ELF segment payload extends past end of file")
        phdrs.append((p_flags, p_offset, p_vaddr, p_filesz, p_memsz))
    if not phdrs:
        raise ValueError("ELF executable has no loadable segments")
    memory_size = max(vaddr + memsz for _flags, _off, vaddr, _filesz, memsz in phdrs)
    memory = bytearray(memory_size)
    for _flags, p_offset, p_vaddr, p_filesz, _p_memsz in phdrs:
        memory[p_vaddr : p_vaddr + p_filesz] = data[p_offset : p_offset + p_filesz]

    headers = _read_section_headers(data, e_shoff, e_shnum)
    _attach_section_names(data, headers, e_shstrndx)

    note = None
    debug_info = b""
    base_relocations = []
    for header in headers:
        if header["name"] == _STACKVM_META_SECTION:
            note = _parse_stackvm_note(_section_payload(data, header))
        elif _is_debug_section(header["name"]) and header["type"] == SHT_PROGBITS:
            payload = _section_payload(data, header)
            if payload.startswith(STACKVM_DEBUG_MAGIC):
                debug_info += payload
        elif header["type"] == SHT_RELA:
            payload = _section_payload(data, header)
            if len(payload) % _RELA.size:
                raise ValueError("ELF relocation section is truncated")
            for offset in range(0, len(payload), _RELA.size):
                r_offset, r_info, _r_addend = _RELA.unpack_from(payload, offset)
                r_type = r_info & 0xFFFFFFFF
                if r_type == R_STACKVM_RELATIVE:
                    base_relocations.append(r_offset)

    if note is not None and note[0] == _STACKVM_NOTE_EXECUTABLE:
        code_segment_end = note[3]
        data_segment_start = note[4]
        file_size = note[5]
    else:
        code_segments = [
            (vaddr, memsz)
            for flags, _off, vaddr, _filesz, memsz in phdrs
            if flags & PF_X
        ]
        data_segments = [
            (vaddr, memsz)
            for flags, _off, vaddr, _filesz, memsz in phdrs
            if flags & PF_W and not flags & PF_X
        ]
        code_segment_end = (
            max(vaddr + memsz for vaddr, memsz in code_segments)
            if code_segments
            else 0
        )
        data_segment_start = min((vaddr for vaddr, _memsz in data_segments), default=code_segment_end)
        file_size = max(
            vaddr + filesz for _flags, _off, vaddr, filesz, _memsz in phdrs
        )

    executable = StackVMExecutable(
        bytes(memory),
        code_segment_end,
        data_segment_start,
        file_size,
        tuple(sorted(base_relocations)),
        debug_info,
    )
    return executable


def load_elf_executable(source: Union[str, BinaryIO]) -> StackVMExecutable:
    if hasattr(source, "read"):
        return loads_elf_executable(source.read())
    with open(source, "rb") as fl:
        return loads_elf_executable(fl.read())


def is_elf_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".o", ".elf"} or os.path.basename(path) == "vmlinux"
