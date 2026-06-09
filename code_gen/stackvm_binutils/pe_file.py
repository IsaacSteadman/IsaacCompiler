"""PE32+/COFF read/write support for StackVM UEFI images (workstream D1b.1).

UEFI images are **PE32+/COFF** with an EFI subsystem type (application /
boot-service-driver / runtime-driver), not ELF.  This module writes a small,
self-consistent PE32+ image (``.efi``) from a linked
:class:`~.executable_file.StackVMExecutable` and reads it back, and provides a
read-only structural inspector (:func:`read_pe_image`) so the host binutils
CLIs can render PE headers / sections / base relocations the way they render
ELF.

Design notes
------------
* The image is **position independent** through a PE base-relocation
  (``.reloc``) table, exactly the way real UEFI images are: the loader maps the
  image at an arbitrary base and walks ``.reloc`` to fix up absolute pointers.
  The StackVM linker already produces an ``R_STACKVM_RELATIVE`` base-relocation
  stream (the list of 8-byte image offsets that hold absolute addresses); the PE
  writer reuses that stream directly -- each offset becomes an
  ``IMAGE_REL_BASED_DIR64`` entry -- and reuses
  :func:`~.executable_file.apply_base_fixups` to bias the stored pointer values
  to ``ImageBase``.  No GOT/PLT (the ELF dynamic-linking path) is needed: PE
  base relocations are simpler and are what the firmware loader consumes.
* The PE in-memory image's RVA space is the StackVM address space shifted up by
  ``section_base_rva`` (the RVA of the first section, after the headers).  A
  StackVM address ``A`` maps to RVA ``section_base_rva + A``; an absolute
  pointer that held ``A`` (linked at base 0) is stored as
  ``ImageBase + section_base_rva + A`` and is fixed up by ``.reloc``.  Reading an
  image undoes that bias, so ``write -> read`` round-trips the executable
  (memory bytes, code/data boundaries, and the base-relocation offsets).
* A discardable ``.svmmeta`` section records the StackVM segment boundaries
  (and the native StackVM debug payload) so the reader recovers them exactly,
  mirroring the ``.note.stackvm`` the ELF writer emits.
"""

from dataclasses import dataclass, field
import os
import struct
from collections import OrderedDict
from typing import BinaryIO, Dict, List, Optional, Sequence, Tuple, Union

from .executable_file import StackVMExecutable, apply_base_fixups


# ---------------------------------------------------------------------------
# PE/COFF constants
# ---------------------------------------------------------------------------

DOS_MAGIC = b"MZ"
PE_SIGNATURE = b"PE\0\0"

# Custom COFF machine id for StackVM, matching ``EM_STACKVM`` (0x5356) used by
# the ELF path.  PE machine ids are 16-bit; 0x5356 ('SV') does not collide with
# any architecture Microsoft has assigned.
IMAGE_FILE_MACHINE_STACKVM = 0x5356

PE32PLUS_MAGIC = 0x20B

# COFF file-header characteristics.
IMAGE_FILE_RELOCS_STRIPPED = 0x0001
IMAGE_FILE_EXECUTABLE_IMAGE = 0x0002
IMAGE_FILE_LINE_NUMS_STRIPPED = 0x0004
IMAGE_FILE_LOCAL_SYMS_STRIPPED = 0x0008
IMAGE_FILE_LARGE_ADDRESS_AWARE = 0x0020
IMAGE_FILE_DEBUG_STRIPPED = 0x0200
IMAGE_FILE_DLL = 0x2000

# Subsystem ids (the EFI image types).
IMAGE_SUBSYSTEM_EFI_APPLICATION = 10
IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER = 11
IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER = 12
IMAGE_SUBSYSTEM_EFI_ROM = 13

_SUBSYSTEM_BY_NAME = {
    "efi-application": IMAGE_SUBSYSTEM_EFI_APPLICATION,
    "efi-app": IMAGE_SUBSYSTEM_EFI_APPLICATION,
    "application": IMAGE_SUBSYSTEM_EFI_APPLICATION,
    "efi-boot-service-driver": IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER,
    "efi-bsd": IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER,
    "efi-runtime-driver": IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER,
    "efi-rtd": IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER,
    "efi-rom": IMAGE_SUBSYSTEM_EFI_ROM,
}

SUBSYSTEM_NAMES = {
    IMAGE_SUBSYSTEM_EFI_APPLICATION: "EFI Application",
    IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER: "EFI Boot Service Driver",
    IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER: "EFI Runtime Driver",
    IMAGE_SUBSYSTEM_EFI_ROM: "EFI ROM",
}

# Section characteristics.
IMAGE_SCN_CNT_CODE = 0x00000020
IMAGE_SCN_CNT_INITIALIZED_DATA = 0x00000040
IMAGE_SCN_CNT_UNINITIALIZED_DATA = 0x00000080
IMAGE_SCN_MEM_DISCARDABLE = 0x02000000
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_WRITE = 0x80000000

# Data-directory indices.
IMAGE_DIRECTORY_ENTRY_BASERELOC = 5
IMAGE_DIRECTORY_ENTRY_DEBUG = 6
IMAGE_NUMBEROF_DIRECTORY_ENTRIES = 16

# Base-relocation entry types.
IMAGE_REL_BASED_ABSOLUTE = 0
IMAGE_REL_BASED_DIR64 = 10

DEFAULT_IMAGE_BASE = 0x140000000
SECTION_ALIGNMENT = 0x1000
FILE_ALIGNMENT = 0x200

_DEFAULT_ENTRY_SYMBOLS = ("efi_main", "_start", "EfiMain", "_ModuleEntryPoint")

_SVM_META_SECTION = ".svmmeta"
_SVM_META_MAGIC = b"SVMPE\0\0\0"

# struct layouts (all little-endian)
_DOS_HEADER = struct.Struct("<2s58xI")  # 'MZ', reserved, e_lfanew at 0x3C
_COFF_HEADER = struct.Struct("<HHIIIHH")
_OPTIONAL_HEADER = struct.Struct("<HBBIIIIIQIIHHHHHHIIIIHHQQQQII")
_DATA_DIRECTORY = struct.Struct("<II")
_SECTION_HEADER = struct.Struct("<8sIIIIIIHHI")
_RELOC_BLOCK_HEADER = struct.Struct("<II")
_SVM_META = struct.Struct("<8sQQQQQ")

_DOS_HEADER_SIZE = 64
assert _DOS_HEADER.size == _DOS_HEADER_SIZE
assert _COFF_HEADER.size == 20
assert _OPTIONAL_HEADER.size == 112
assert _SECTION_HEADER.size == 40


def _align_up(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    return (value + alignment - 1) & ~(alignment - 1)


def subsystem_from_name(name: Union[str, int, None]) -> int:
    """Resolve a subsystem *name* (or numeric id) to an EFI subsystem id."""
    if name is None:
        return IMAGE_SUBSYSTEM_EFI_APPLICATION
    if isinstance(name, int):
        return name
    key = name.strip().lower()
    if key not in _SUBSYSTEM_BY_NAME:
        raise ValueError("unknown EFI subsystem: %r" % (name,))
    return _SUBSYSTEM_BY_NAME[key]


def is_pe_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".efi", ".pe"}


def is_pe_bytes(data: bytes) -> bool:
    return len(data) >= 2 and data[:2] == DOS_MAGIC


# ---------------------------------------------------------------------------
# Base-relocation (.reloc) encode/decode
# ---------------------------------------------------------------------------


def build_reloc_section(base_relocations: Sequence[int], section_base_rva: int) -> bytes:
    """Encode *base_relocations* (StackVM image offsets) as a PE ``.reloc``
    section: ``IMAGE_BASE_RELOCATION`` blocks of ``IMAGE_REL_BASED_DIR64``
    entries, grouped by the 4 KiB page of their RVA."""

    pages: "OrderedDict[int, List[int]]" = OrderedDict()
    for offset in sorted(base_relocations):
        rva = section_base_rva + offset
        page = rva & ~0xFFF
        pages.setdefault(page, []).append(rva - page)
    out = bytearray()
    for page, offsets in pages.items():
        entries = [(IMAGE_REL_BASED_DIR64 << 12) | off for off in offsets]
        if len(entries) % 2:
            # Pad to a 4-byte boundary with an ABSOLUTE (no-op) entry.
            entries.append(IMAGE_REL_BASED_ABSOLUTE << 12)
        block_size = _RELOC_BLOCK_HEADER.size + len(entries) * 2
        out.extend(_RELOC_BLOCK_HEADER.pack(page, block_size))
        for entry in entries:
            out.extend(struct.pack("<H", entry))
    return bytes(out)


def parse_reloc_section(data: bytes) -> List[Tuple[int, int]]:
    """Decode a ``.reloc`` blob into a list of ``(rva, type)`` pairs."""
    result: List[Tuple[int, int]] = []
    offset = 0
    while offset + _RELOC_BLOCK_HEADER.size <= len(data):
        page, block_size = _RELOC_BLOCK_HEADER.unpack_from(data, offset)
        if block_size < _RELOC_BLOCK_HEADER.size:
            break
        entry_bytes = block_size - _RELOC_BLOCK_HEADER.size
        entry_start = offset + _RELOC_BLOCK_HEADER.size
        if entry_start + entry_bytes > len(data):
            break
        for pos in range(entry_start, entry_start + entry_bytes, 2):
            (value,) = struct.unpack_from("<H", data, pos)
            reloc_type = value >> 12
            reloc_off = value & 0xFFF
            if reloc_type == IMAGE_REL_BASED_ABSOLUTE:
                continue  # padding
            result.append((page + reloc_off, reloc_type))
        offset += block_size
    return result


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


@dataclass
class _PeSection:
    name: str
    virtual_size: int
    virtual_address: int
    raw: bytes
    characteristics: int
    raw_pointer: int = 0
    raw_size: int = 0


def _entry_address(symbols: Optional[Sequence[object]]) -> Optional[int]:
    if not symbols:
        return None
    by_name = {}
    for symbol in symbols:
        name = getattr(symbol, "name", "")
        by_name.setdefault(name, getattr(symbol, "address", 0))
    for candidate in _DEFAULT_ENTRY_SYMBOLS:
        if candidate in by_name:
            return by_name[candidate]
    return None


def dumps_pe_executable(
    executable: StackVMExecutable,
    section_layouts: Optional[Sequence[object]] = None,
    symbols: Optional[Sequence[object]] = None,
    *,
    subsystem: Union[str, int, None] = IMAGE_SUBSYSTEM_EFI_APPLICATION,
    image_base: int = DEFAULT_IMAGE_BASE,
    entry: Optional[int] = None,
    dll: Optional[bool] = None,
) -> bytes:
    """Serialise *executable* to a PE32+ ``.efi`` image.

    ``section_layouts`` is accepted for signature parity with the ELF writer but
    the segment split is taken from the executable's code/data boundaries.
    ``symbols`` is consulted to locate the entry point (``efi_main``/``_start``)
    when *entry* is not given.
    """

    subsystem_id = subsystem_from_name(subsystem)
    if dll is None:
        dll = subsystem_id in (
            IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER,
            IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER,
        )

    memory = bytes(executable.memory)
    mem_size = len(memory)
    file_size = mem_size if executable.file_size is None else executable.file_size
    code_end = executable.code_segment_end
    data_start = executable.data_segment_start
    base_relocations = tuple(sorted(executable.base_relocations))

    # Decide the loadable-section split.  Use distinct .text/.data when the data
    # segment is section-aligned and the inter-segment gap is zero padding;
    # otherwise fall back to a single .image section that maps the whole image.
    gap_is_zero = not any(memory[code_end:data_start]) if data_start >= code_end else False
    can_split = (
        data_start >= code_end
        and (data_start % SECTION_ALIGNMENT == 0)
        and gap_is_zero
    )

    # Build the logical section list (names + characteristics) so we can count
    # them; raw bytes / RVAs are filled once section_base_rva is known.
    if can_split:
        loadable_names: List[Tuple[str, int]] = []
        if code_end > 0:
            loadable_names.append(
                (".text", IMAGE_SCN_CNT_CODE | IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ)
            )
        if mem_size > data_start:
            loadable_names.append(
                (
                    ".data",
                    IMAGE_SCN_CNT_INITIALIZED_DATA
                    | IMAGE_SCN_MEM_READ
                    | IMAGE_SCN_MEM_WRITE,
                )
            )
    else:
        loadable_names = [
            (
                ".image",
                IMAGE_SCN_CNT_CODE
                | IMAGE_SCN_CNT_INITIALIZED_DATA
                | IMAGE_SCN_MEM_EXECUTE
                | IMAGE_SCN_MEM_READ
                | IMAGE_SCN_MEM_WRITE,
            )
        ]

    has_reloc = bool(base_relocations)
    section_count = len(loadable_names) + (1 if has_reloc else 0) + 1  # + .svmmeta

    headers_size = (
        _DOS_HEADER_SIZE
        + len(PE_SIGNATURE)
        + _COFF_HEADER.size
        + _OPTIONAL_HEADER.size
        + IMAGE_NUMBEROF_DIRECTORY_ENTRIES * _DATA_DIRECTORY.size
        + section_count * _SECTION_HEADER.size
    )
    size_of_headers = _align_up(headers_size, FILE_ALIGNMENT)
    section_base_rva = _align_up(size_of_headers, SECTION_ALIGNMENT)

    # Bias absolute pointers to (ImageBase + section_base_rva) using the existing
    # base-fixup machinery, then slice the relocated image into sections.
    relocated = bytearray(memory)
    apply_base_fixups(relocated, base_relocations, image_base + section_base_rva)
    relocated = bytes(relocated)

    sections: List[_PeSection] = []
    if can_split:
        if code_end > 0:
            sections.append(
                _PeSection(
                    ".text",
                    code_end,
                    section_base_rva,
                    relocated[:code_end],
                    IMAGE_SCN_CNT_CODE | IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ,
                )
            )
        if mem_size > data_start:
            sections.append(
                _PeSection(
                    ".data",
                    mem_size - data_start,
                    section_base_rva + data_start,
                    relocated[data_start:file_size],
                    IMAGE_SCN_CNT_INITIALIZED_DATA
                    | IMAGE_SCN_MEM_READ
                    | IMAGE_SCN_MEM_WRITE,
                )
            )
    else:
        sections.append(
            _PeSection(
                ".image",
                mem_size,
                section_base_rva,
                relocated[:file_size],
                IMAGE_SCN_CNT_CODE
                | IMAGE_SCN_CNT_INITIALIZED_DATA
                | IMAGE_SCN_MEM_EXECUTE
                | IMAGE_SCN_MEM_READ
                | IMAGE_SCN_MEM_WRITE,
            )
        )

    image_end_rva = section_base_rva + mem_size
    next_rva = _align_up(image_end_rva, SECTION_ALIGNMENT)

    reloc_rva = 0
    reloc_size = 0
    if has_reloc:
        reloc_blob = build_reloc_section(base_relocations, section_base_rva)
        reloc_rva = next_rva
        reloc_size = len(reloc_blob)
        sections.append(
            _PeSection(
                ".reloc",
                len(reloc_blob),
                next_rva,
                reloc_blob,
                IMAGE_SCN_CNT_INITIALIZED_DATA
                | IMAGE_SCN_MEM_READ
                | IMAGE_SCN_MEM_DISCARDABLE,
            )
        )
        next_rva = _align_up(next_rva + len(reloc_blob), SECTION_ALIGNMENT)

    debug_info = bytes(executable.debug_info)
    meta_blob = _SVM_META.pack(
        _SVM_META_MAGIC, code_end, data_start, file_size, mem_size, len(debug_info)
    ) + debug_info
    sections.append(
        _PeSection(
            _SVM_META_SECTION,
            len(meta_blob),
            next_rva,
            meta_blob,
            IMAGE_SCN_CNT_INITIALIZED_DATA
            | IMAGE_SCN_MEM_READ
            | IMAGE_SCN_MEM_DISCARDABLE,
        )
    )
    next_rva = _align_up(next_rva + len(meta_blob), SECTION_ALIGNMENT)

    size_of_image = next_rva

    # Assign file offsets to the raw payloads.
    cursor = size_of_headers
    for section in sections:
        if section.raw:
            section.raw_pointer = cursor
            section.raw_size = _align_up(len(section.raw), FILE_ALIGNMENT)
            cursor += section.raw_size
        else:
            section.raw_pointer = 0
            section.raw_size = 0
    file_total = cursor

    size_of_code = sum(
        s.raw_size for s in sections if s.characteristics & IMAGE_SCN_MEM_EXECUTE
    )
    size_of_initialized = sum(
        s.raw_size
        for s in sections
        if s.characteristics & IMAGE_SCN_CNT_INITIALIZED_DATA
        and not s.characteristics & IMAGE_SCN_MEM_EXECUTE
    )
    size_of_uninitialized = max(0, mem_size - file_size)

    base_of_code = sections[0].virtual_address if loadable_names else section_base_rva
    if entry is None:
        entry = _entry_address(symbols)
    entry_rva = section_base_rva + (entry if entry is not None else 0)

    characteristics = (
        IMAGE_FILE_EXECUTABLE_IMAGE
        | IMAGE_FILE_LARGE_ADDRESS_AWARE
        | IMAGE_FILE_LINE_NUMS_STRIPPED
        | IMAGE_FILE_LOCAL_SYMS_STRIPPED
    )
    if dll:
        characteristics |= IMAGE_FILE_DLL

    out = bytearray(size_of_headers)
    out[0:_DOS_HEADER_SIZE] = _DOS_HEADER.pack(DOS_MAGIC, _DOS_HEADER_SIZE)
    pos = _DOS_HEADER_SIZE
    out[pos : pos + len(PE_SIGNATURE)] = PE_SIGNATURE
    pos += len(PE_SIGNATURE)
    out[pos : pos + _COFF_HEADER.size] = _COFF_HEADER.pack(
        IMAGE_FILE_MACHINE_STACKVM,
        len(sections),
        0,  # TimeDateStamp
        0,  # PointerToSymbolTable
        0,  # NumberOfSymbols
        _OPTIONAL_HEADER.size + IMAGE_NUMBEROF_DIRECTORY_ENTRIES * _DATA_DIRECTORY.size,
        characteristics,
    )
    pos += _COFF_HEADER.size
    out[pos : pos + _OPTIONAL_HEADER.size] = _OPTIONAL_HEADER.pack(
        PE32PLUS_MAGIC,
        14,  # MajorLinkerVersion
        0,  # MinorLinkerVersion
        size_of_code,
        size_of_initialized,
        size_of_uninitialized,
        entry_rva,
        base_of_code,
        image_base,
        SECTION_ALIGNMENT,
        FILE_ALIGNMENT,
        0,  # MajorOperatingSystemVersion
        0,  # MinorOperatingSystemVersion
        0,  # MajorImageVersion
        0,  # MinorImageVersion
        0,  # MajorSubsystemVersion
        0,  # MinorSubsystemVersion
        0,  # Win32VersionValue
        size_of_image,
        size_of_headers,
        0,  # CheckSum
        subsystem_id,
        0,  # DllCharacteristics
        0,  # SizeOfStackReserve
        0,  # SizeOfStackCommit
        0,  # SizeOfHeapReserve
        0,  # SizeOfHeapCommit
        0,  # LoaderFlags
        IMAGE_NUMBEROF_DIRECTORY_ENTRIES,
    )
    pos += _OPTIONAL_HEADER.size
    directories = [(0, 0)] * IMAGE_NUMBEROF_DIRECTORY_ENTRIES
    if has_reloc:
        directories[IMAGE_DIRECTORY_ENTRY_BASERELOC] = (reloc_rva, reloc_size)
    for rva, size in directories:
        out[pos : pos + _DATA_DIRECTORY.size] = _DATA_DIRECTORY.pack(rva, size)
        pos += _DATA_DIRECTORY.size
    for section in sections:
        out[pos : pos + _SECTION_HEADER.size] = _SECTION_HEADER.pack(
            section.name.encode("ascii")[:8].ljust(8, b"\0"),
            section.virtual_size,
            section.virtual_address,
            section.raw_size,
            section.raw_pointer,
            0,  # PointerToRelocations
            0,  # PointerToLinenumbers
            0,  # NumberOfRelocations
            0,  # NumberOfLinenumbers
            section.characteristics,
        )
        pos += _SECTION_HEADER.size

    out.extend(b"\0" * (file_total - len(out)))
    for section in sections:
        if section.raw:
            out[section.raw_pointer : section.raw_pointer + len(section.raw)] = section.raw
    return bytes(out)


def write_pe_executable(
    executable: StackVMExecutable,
    target: Union[str, BinaryIO],
    section_layouts: Optional[Sequence[object]] = None,
    symbols: Optional[Sequence[object]] = None,
    *,
    subsystem: Union[str, int, None] = IMAGE_SUBSYSTEM_EFI_APPLICATION,
    image_base: int = DEFAULT_IMAGE_BASE,
    entry: Optional[int] = None,
    dll: Optional[bool] = None,
) -> None:
    data = dumps_pe_executable(
        executable,
        section_layouts,
        symbols,
        subsystem=subsystem,
        image_base=image_base,
        entry=entry,
        dll=dll,
    )
    if hasattr(target, "write"):
        target.write(data)
        return
    with open(target, "wb") as fl:
        fl.write(data)


# ---------------------------------------------------------------------------
# Reader: PE image -> StackVMExecutable
# ---------------------------------------------------------------------------


def _read_optional_header(data: bytes) -> Tuple[dict, int, int]:
    if len(data) < _DOS_HEADER_SIZE:
        raise ValueError("PE file is too short to contain a DOS header")
    dos_magic, e_lfanew = _DOS_HEADER.unpack_from(data)
    if dos_magic != DOS_MAGIC:
        raise ValueError("invalid DOS (MZ) magic")
    if data[e_lfanew : e_lfanew + len(PE_SIGNATURE)] != PE_SIGNATURE:
        raise ValueError("invalid PE signature")
    coff_off = e_lfanew + len(PE_SIGNATURE)
    (
        machine,
        num_sections,
        _timestamp,
        _ptr_symtab,
        _num_syms,
        size_optional,
        characteristics,
    ) = _COFF_HEADER.unpack_from(data, coff_off)
    opt_off = coff_off + _COFF_HEADER.size
    fields = _OPTIONAL_HEADER.unpack_from(data, opt_off)
    if fields[0] != PE32PLUS_MAGIC:
        raise ValueError("only PE32+ images are supported")
    header = {
        "machine": machine,
        "num_sections": num_sections,
        "characteristics": characteristics,
        "size_of_code": fields[3],
        "size_of_initialized_data": fields[4],
        "size_of_uninitialized_data": fields[5],
        "entry_point": fields[6],
        "base_of_code": fields[7],
        "image_base": fields[8],
        "section_alignment": fields[9],
        "file_alignment": fields[10],
        "size_of_image": fields[18],
        "size_of_headers": fields[19],
        "subsystem": fields[21],
        "dll_characteristics": fields[22],
        "number_of_rva_and_sizes": fields[28],
    }
    dir_off = opt_off + _OPTIONAL_HEADER.size
    directories: List[Tuple[int, int]] = []
    for index in range(header["number_of_rva_and_sizes"]):
        rva, size = _DATA_DIRECTORY.unpack_from(data, dir_off + index * _DATA_DIRECTORY.size)
        directories.append((rva, size))
    header["directories"] = directories
    section_off = dir_off + header["number_of_rva_and_sizes"] * _DATA_DIRECTORY.size
    return header, num_sections, section_off


def _read_sections(data: bytes, num_sections: int, section_off: int) -> List[dict]:
    sections: List[dict] = []
    for index in range(num_sections):
        offset = section_off + index * _SECTION_HEADER.size
        (
            name,
            virtual_size,
            virtual_address,
            raw_size,
            raw_pointer,
            _ptr_relocs,
            _ptr_lines,
            _num_relocs,
            _num_lines,
            characteristics,
        ) = _SECTION_HEADER.unpack_from(data, offset)
        raw = data[raw_pointer : raw_pointer + raw_size] if raw_size else b""
        sections.append(
            {
                "name": name.rstrip(b"\0").decode("ascii", "replace"),
                "virtual_size": virtual_size,
                "virtual_address": virtual_address,
                "raw_size": raw_size,
                "raw_pointer": raw_pointer,
                "characteristics": characteristics,
                "raw": raw,
            }
        )
    return sections


def loads_pe_executable(data: bytes) -> StackVMExecutable:
    header, num_sections, section_off = _read_optional_header(data)
    sections = _read_sections(data, num_sections, section_off)
    image_base = header["image_base"]

    meta = next((s for s in sections if s["name"] == _SVM_META_SECTION), None)
    if meta is None or not meta["raw"].startswith(_SVM_META_MAGIC):
        raise ValueError("PE image is missing its StackVM metadata section")
    (
        _magic,
        code_end,
        data_start,
        file_size,
        mem_size,
        debug_size,
    ) = _SVM_META.unpack_from(meta["raw"])
    debug_info = meta["raw"][_SVM_META.size : _SVM_META.size + debug_size]

    loadable = [
        s
        for s in sections
        if s["name"] not in (_SVM_META_SECTION, ".reloc")
        and not s["characteristics"] & IMAGE_SCN_MEM_DISCARDABLE
    ]
    if not loadable:
        raise ValueError("PE image has no loadable sections")
    section_base_rva = min(s["virtual_address"] for s in loadable)

    memory = bytearray(mem_size)
    for section in loadable:
        dest = section["virtual_address"] - section_base_rva
        if dest < 0:
            continue
        n = min(len(section["raw"]), section["virtual_size"], mem_size - dest)
        if n > 0:
            memory[dest : dest + n] = section["raw"][:n]

    reloc_section = next((s for s in sections if s["name"] == ".reloc"), None)
    base_relocations: List[int] = []
    if reloc_section is not None:
        for rva, reloc_type in parse_reloc_section(reloc_section["raw"]):
            if reloc_type == IMAGE_REL_BASED_DIR64:
                base_relocations.append(rva - section_base_rva)
    base_relocations.sort()

    # Undo the (ImageBase + section_base_rva) bias applied at write time.
    apply_base_fixups(memory, base_relocations, -(image_base + section_base_rva))

    executable = StackVMExecutable(
        bytes(memory),
        code_end,
        data_start,
        file_size,
        tuple(base_relocations),
        debug_info,
    )
    return executable


def load_pe_executable(source: Union[str, BinaryIO]) -> StackVMExecutable:
    if hasattr(source, "read"):
        return loads_pe_executable(source.read())
    with open(source, "rb") as fl:
        return loads_pe_executable(fl.read())


# ---------------------------------------------------------------------------
# Read-only structural inspection (for the host binutils CLIs)
# ---------------------------------------------------------------------------


@dataclass
class PeSectionInfo:
    name: str
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_pointer: int
    characteristics: int
    data: bytes

    @property
    def is_code(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_EXECUTE)

    @property
    def is_readable(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_READ)

    @property
    def is_writable(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_WRITE)

    @property
    def is_discardable(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_DISCARDABLE)

    @property
    def is_uninitialized(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_CNT_UNINITIALIZED_DATA)


@dataclass
class PeImage:
    machine: int
    characteristics: int
    subsystem: int
    dll_characteristics: int
    image_base: int
    entry_point: int
    section_alignment: int
    file_alignment: int
    size_of_image: int
    size_of_headers: int
    size_of_code: int
    size_of_initialized_data: int
    size_of_uninitialized_data: int
    sections: List[PeSectionInfo]
    data_directories: List[Tuple[int, int]]
    base_relocations: List[Tuple[int, int]] = field(default_factory=list)

    def section_by_name(self, name: str) -> Optional[PeSectionInfo]:
        for section in self.sections:
            if section.name == name:
                return section
        return None


def read_pe_image(data: bytes) -> PeImage:
    header, num_sections, section_off = _read_optional_header(data)
    raw_sections = _read_sections(data, num_sections, section_off)
    sections = [
        PeSectionInfo(
            s["name"],
            s["virtual_size"],
            s["virtual_address"],
            s["raw_size"],
            s["raw_pointer"],
            s["characteristics"],
            s["raw"],
        )
        for s in raw_sections
    ]
    base_relocations: List[Tuple[int, int]] = []
    reloc_dir = header["directories"][IMAGE_DIRECTORY_ENTRY_BASERELOC] if len(
        header["directories"]
    ) > IMAGE_DIRECTORY_ENTRY_BASERELOC else (0, 0)
    if reloc_dir[0]:
        reloc_section = next(
            (s for s in sections if s.virtual_address == reloc_dir[0]), None
        )
        if reloc_section is None:
            reloc_section = next((s for s in sections if s.name == ".reloc"), None)
        if reloc_section is not None:
            base_relocations = parse_reloc_section(reloc_section.data)
    return PeImage(
        header["machine"],
        header["characteristics"],
        header["subsystem"],
        header["dll_characteristics"],
        header["image_base"],
        header["entry_point"],
        header["section_alignment"],
        header["file_alignment"],
        header["size_of_image"],
        header["size_of_headers"],
        header["size_of_code"],
        header["size_of_initialized_data"],
        header["size_of_uninitialized_data"],
        sections,
        header["directories"],
        base_relocations,
    )


def read_pe(source: Union[str, BinaryIO]) -> PeImage:
    if hasattr(source, "read"):
        return read_pe_image(source.read())
    with open(source, "rb") as fl:
        return read_pe_image(fl.read())
