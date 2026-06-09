"""Host binutils CLIs that kbuild invokes (workstream C2).

This module implements the StackVM equivalents of the GNU binutils a kernel
build expects to find on ``$PATH``: ``nm``, ``objdump``, ``readelf``, ``size``,
``strip`` and ``objcopy`` (plus the archive helper ``ranlib`` and the kbuild
generator ``kallsyms``).  They are reached as subcommands of the package
front end, e.g. ``python -m IsaacCompiler nm vmlinux``.

The tools operate on the standard ELF interchange format produced by the
assembler/compiler/linker (workstream C1).  Native ``.sbo``/``.sbc`` inputs are
transparently re-expressed as ELF so a single read path drives every tool.

Each tool is split into a pure ``format_*``/``generate_*`` core (returning text,
so it is unit-testable without spawning a process) and a thin ``run_*`` wrapper
that parses ``argv``, loads inputs and prints.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence, Tuple

from .archive_file import (
    ArchiveMember,
    StackVMArchive,
    SBA_MAGIC,
    dumps_sba,
    load_sba,
    loads_sba,
)
from .debug_info import DEBUG_SECTION_NAME
from .disassemble import disassemble
from .elf_file import (
    DT_NEEDED,
    DT_NULL,
    DT_SONAME,
    ELF_MAGIC,
    ET_DYN,
    ET_EXEC,
    ET_REL,
    NT_GNU_BUILD_ID,
    PF_R,
    PF_W,
    PF_X,
    PT_DYNAMIC,
    PT_LOAD,
    PT_NOTE,
    R_STACKVM_64,
    R_STACKVM_COPY,
    R_STACKVM_GLOB_DAT,
    R_STACKVM_JUMP_SLOT,
    R_STACKVM_NONE,
    R_STACKVM_PC64,
    R_STACKVM_RELATIVE,
    SHN_ABS,
    SHN_UNDEF,
    SHT_DYNAMIC,
    SHT_DYNSYM,
    SHT_HASH,
    SHT_NOBITS,
    SHT_NOTE,
    SHT_NULL,
    SHT_PROGBITS,
    SHT_RELA,
    SHT_STRTAB,
    SHT_SYMTAB,
    STB_GLOBAL,
    STB_LOCAL,
    STB_WEAK,
    STT_FILE,
    STT_FUNC,
    STT_NOTYPE,
    STT_OBJECT,
    STT_SECTION,
    ElfImage,
    ElfSymbolInfo,
    dumps_elf_executable,
    dumps_elf_object,
    read_elf_image,
)
from .pe_file import (
    DOS_MAGIC,
    IMAGE_FILE_DLL,
    IMAGE_REL_BASED_DIR64,
    IMAGE_SCN_CNT_CODE,
    IMAGE_SCN_CNT_INITIALIZED_DATA,
    IMAGE_SCN_CNT_UNINITIALIZED_DATA,
    IMAGE_SCN_MEM_DISCARDABLE,
    IMAGE_SCN_MEM_EXECUTE,
    IMAGE_SCN_MEM_READ,
    IMAGE_SCN_MEM_WRITE,
    SUBSYSTEM_NAMES,
    PeImage,
    is_pe_bytes,
    read_pe_image,
)
from .object_file import (
    ObjectRelocation,
    ObjectSection,
    ObjectSegment,
    ObjectSymbol,
    SBO_MAGIC,
    StackVMObject,
    SymbolBinding,
    SymbolType,
    loads_sbo,
)
from .executable_file import (
    SBC_DEBUG_MAGIC,
    SBC_MAGIC,
    SBC_RELOC_MAGIC,
    SBC_SPARSE_MAGIC,
    StackVMExecutable,
    loads_sbc,
)


class HostToolError(Exception):
    """A user-facing error raised by one of the host binutils tools."""


# ---------------------------------------------------------------------------
# Shared loading: present any StackVM artifact as a structural ELF image.
# ---------------------------------------------------------------------------

_SBC_MAGICS = {SBC_MAGIC, SBC_SPARSE_MAGIC, SBC_RELOC_MAGIC, SBC_DEBUG_MAGIC}


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as fl:
            return fl.read()
    except OSError as exc:
        raise HostToolError(str(exc)) from exc


def image_from_bytes(data: bytes) -> ElfImage:
    """Return an :class:`ElfImage` for ELF, ``.sbo`` or ``.sbc`` *data*."""
    if data[:4] == ELF_MAGIC:
        return read_elf_image(data)
    magic8 = data[:8]
    if magic8 == SBO_MAGIC:
        return read_elf_image(dumps_elf_object(loads_sbo(data)))
    if magic8 in _SBC_MAGICS:
        return read_elf_image(dumps_elf_executable(loads_sbc(data)))
    if magic8 == SBA_MAGIC:
        raise HostToolError(
            "archives must be processed per member, not as a flat image"
        )
    raise HostToolError("unrecognized input format")


def load_image(path: str) -> ElfImage:
    return image_from_bytes(_read_bytes(path))


def _is_archive(data: bytes) -> bool:
    return data[:8] == SBA_MAGIC


def load_archive_members(path: str) -> List[Tuple[str, ElfImage]]:
    archive = loads_sba(_read_bytes(path))
    return [
        (member.name, read_elf_image(dumps_elf_object(member.obj)))
        for member in archive.members
    ]


def _is_debug_section_name(name: str) -> bool:
    return name == DEBUG_SECTION_NAME or name.startswith(DEBUG_SECTION_NAME + ".")


# ---------------------------------------------------------------------------
# nm
# ---------------------------------------------------------------------------

_VALUE_WIDTH = 16


def nm_symbol_letter(symbol: ElfSymbolInfo, image: ElfImage) -> str:
    """Return the GNU-``nm`` type character for *symbol*."""
    if symbol.is_undefined:
        return "w" if symbol.is_weak else "U"
    if symbol.is_weak:
        # Weak data symbols are 'V'/'v'; everything else weak is 'W'/'w'.
        section = image.section_by_name(symbol.section_name)
        if section is not None and not section.is_exec and section.is_writable:
            return "V" if symbol.is_global else "v"
        return "W" if symbol.is_global else "w"
    if symbol.is_absolute:
        letter = "a"
    else:
        section = image.section_by_name(symbol.section_name)
        if section is None or not section.is_alloc:
            letter = "n"  # non-allocated (e.g. debug) or unknown section
        elif section.is_nobits:
            letter = "b"
        elif section.is_exec:
            letter = "t"
        elif section.is_writable:
            letter = "d"
        else:
            letter = "r"  # read-only allocated data (.rodata)
    return letter.upper() if symbol.is_global else letter


def _nm_should_emit(
    symbol: ElfSymbolInfo,
    extern_only: bool,
    defined_only: bool,
    undefined_only: bool,
) -> bool:
    if symbol.typ in (STT_SECTION, STT_FILE):
        return False
    if extern_only and not symbol.is_global:
        return False
    if defined_only and symbol.is_undefined:
        return False
    if undefined_only and not symbol.is_undefined:
        return False
    return True


def format_nm(
    image: ElfImage,
    *,
    numeric_sort: bool = False,
    no_sort: bool = False,
    reverse_sort: bool = False,
    size_sort: bool = False,
    extern_only: bool = False,
    defined_only: bool = False,
    undefined_only: bool = False,
) -> List[str]:
    symbols = [
        symbol
        for symbol in image.symbols
        if _nm_should_emit(symbol, extern_only, defined_only, undefined_only)
    ]
    if not no_sort:
        if size_sort:
            symbols.sort(key=lambda s: (s.size, s.name))
        elif numeric_sort:
            symbols.sort(key=lambda s: (s.is_undefined, s.value, s.name))
        else:
            symbols.sort(key=lambda s: s.name)
        if reverse_sort:
            symbols.reverse()

    lines = []
    for symbol in symbols:
        letter = nm_symbol_letter(symbol, image)
        if size_sort and not symbol.is_undefined:
            value_field = format(symbol.size, "0%dx" % _VALUE_WIDTH)
        elif symbol.is_undefined:
            value_field = " " * _VALUE_WIDTH
        else:
            value_field = format(symbol.value, "0%dx" % _VALUE_WIDTH)
        lines.append("%s %s %s" % (value_field, letter, symbol.name))
    return lines


def run_nm(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="stackvm-nm", add_help=True)
    parser.add_argument("files", nargs="+")
    parser.add_argument("-n", "--numeric-sort", action="store_true")
    parser.add_argument("-p", "--no-sort", action="store_true")
    parser.add_argument("-r", "--reverse-sort", action="store_true")
    parser.add_argument("--size-sort", action="store_true")
    parser.add_argument("-g", "--extern-only", action="store_true")
    parser.add_argument("--defined-only", action="store_true")
    parser.add_argument("-u", "--undefined-only", action="store_true")
    args = parser.parse_args(argv)

    multiple = len(args.files) > 1
    try:
        for path in args.files:
            data = _read_bytes(path)
            if _is_archive(data):
                for member_name, image in load_archive_members(path):
                    print("\n%s[%s]:" % (path if multiple else "", member_name))
                    _print_nm_image(image, args)
            else:
                if multiple:
                    print("\n%s:" % path)
                _print_nm_image(image_from_bytes(data), args)
    except HostToolError as exc:
        print("stackvm-nm: %s" % exc, file=sys.stderr)
        return 1
    return 0


def _print_nm_image(image: ElfImage, args: argparse.Namespace) -> None:
    for line in format_nm(
        image,
        numeric_sort=args.numeric_sort,
        no_sort=args.no_sort,
        reverse_sort=args.reverse_sort,
        size_sort=args.size_sort,
        extern_only=args.extern_only,
        defined_only=args.defined_only,
        undefined_only=args.undefined_only,
    ):
        print(line)


# ---------------------------------------------------------------------------
# size
# ---------------------------------------------------------------------------


def size_totals(image: ElfImage) -> Tuple[int, int, int]:
    """Return Berkeley-style (text, data, bss) byte totals for *image*."""
    text = data = bss = 0
    for section in image.sections:
        if not section.is_alloc:
            continue
        if section.is_nobits:
            bss += section.size
        elif section.is_writable and not section.is_exec:
            data += section.size
        else:
            text += section.size
    return text, data, bss


def format_size_berkeley(images: Sequence[Tuple[str, ElfImage]]) -> List[str]:
    lines = ["%7s %7s %7s %7s %7s %s" % ("text", "data", "bss", "dec", "hex", "filename")]
    for name, image in images:
        text, data, bss = size_totals(image)
        total = text + data + bss
        lines.append(
            "%7d %7d %7d %7d %7x %s" % (text, data, bss, total, total, name)
        )
    return lines


def format_size_sysv(name: str, image: ElfImage) -> List[str]:
    lines = ["%s  :" % name, "%-20s %10s %10s" % ("section", "size", "addr")]
    total = 0
    for section in image.sections:
        if not section.is_alloc:
            continue
        lines.append("%-20s %10d %10d" % (section.name, section.size, section.addr))
        total += section.size
    lines.append("%-20s %10d" % ("Total", total))
    return lines


def run_size(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="stackvm-size", add_help=True)
    parser.add_argument("files", nargs="+")
    parser.add_argument(
        "-A", "--format-sysv", action="store_true", dest="sysv",
        help="use System V (per-section) output format",
    )
    args = parser.parse_args(argv)
    try:
        if args.sysv:
            for path in args.files:
                for line in format_size_sysv(path, load_image(path)):
                    print(line)
        else:
            images = [(path, load_image(path)) for path in args.files]
            for line in format_size_berkeley(images):
                print(line)
    except HostToolError as exc:
        print("stackvm-size: %s" % exc, file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# readelf / objdump shared name tables
# ---------------------------------------------------------------------------

_ET_NAMES = {
    ET_REL: "REL (Relocatable file)",
    ET_EXEC: "EXEC (Executable file)",
    ET_DYN: "DYN (Shared object file)",
}
_SHT_NAMES = {
    SHT_NULL: "NULL",
    SHT_PROGBITS: "PROGBITS",
    SHT_SYMTAB: "SYMTAB",
    SHT_STRTAB: "STRTAB",
    SHT_RELA: "RELA",
    SHT_HASH: "HASH",
    SHT_DYNAMIC: "DYNAMIC",
    SHT_NOTE: "NOTE",
    SHT_NOBITS: "NOBITS",
    SHT_DYNSYM: "DYNSYM",
}
_STT_NAMES = {
    STT_NOTYPE: "NOTYPE",
    STT_OBJECT: "OBJECT",
    STT_FUNC: "FUNC",
    STT_SECTION: "SECTION",
    STT_FILE: "FILE",
}
_STB_NAMES = {STB_LOCAL: "LOCAL", STB_GLOBAL: "GLOBAL", STB_WEAK: "WEAK"}
_RELOC_NAMES = {
    R_STACKVM_NONE: "R_STACKVM_NONE",
    R_STACKVM_64: "R_STACKVM_64",
    R_STACKVM_PC64: "R_STACKVM_PC64",
    R_STACKVM_RELATIVE: "R_STACKVM_RELATIVE",
    R_STACKVM_GLOB_DAT: "R_STACKVM_GLOB_DAT",
    R_STACKVM_JUMP_SLOT: "R_STACKVM_JUMP_SLOT",
    R_STACKVM_COPY: "R_STACKVM_COPY",
}
_PT_NAMES = {PT_LOAD: "LOAD", PT_DYNAMIC: "DYNAMIC", PT_NOTE: "NOTE"}
_DT_NAMES = {
    0: "NULL", 1: "NEEDED", 2: "PLTRELSZ", 3: "PLTGOT", 4: "HASH", 5: "STRTAB",
    6: "SYMTAB", 7: "RELA", 8: "RELASZ", 9: "RELAENT", 10: "STRSZ", 11: "SYMENT",
    12: "INIT", 13: "FINI", 14: "SONAME", 23: "JMPREL", 25: "INIT_ARRAY",
    26: "FINI_ARRAY", 27: "INIT_ARRAYSZ", 28: "FINI_ARRAYSZ", 30: "FLAGS",
    0x6FFFFFFB: "FLAGS_1",
}


def _section_flag_chars(section) -> str:
    chars = ""
    if section.is_writable:
        chars += "W"
    if section.is_alloc:
        chars += "A"
    if section.is_exec:
        chars += "X"
    return chars


def _phdr_flag_chars(flags: int) -> str:
    return (
        ("R" if flags & PF_R else " ")
        + ("W" if flags & PF_W else " ")
        + ("E" if flags & PF_X else " ")
    )


def _format_symbol_table(name: str, syms: Sequence[ElfSymbolInfo]) -> List[str]:
    lines = [
        "Symbol table '%s' contains %d entries:" % (name, len(syms) + 1),
        "   Num:    Value          Size Type    Bind   Ndx Name",
        "     0: %016x %5d %-7s %-6s UND " % (0, 0, "NOTYPE", "LOCAL"),
    ]
    for index, symbol in enumerate(syms, start=1):
        if symbol.is_undefined:
            ndx = "UND"
        elif symbol.is_absolute:
            ndx = "ABS"
        else:
            ndx = str(symbol.shndx)
        lines.append(
            "  %4d: %016x %5d %-7s %-6s %3s %s"
            % (
                index,
                symbol.value,
                symbol.size,
                _STT_NAMES.get(symbol.typ, "%#x" % symbol.typ),
                _STB_NAMES.get(symbol.binding, "%#x" % symbol.binding),
                ndx,
                symbol.name,
            )
        )
    return lines


def format_readelf(
    path: str,
    image: ElfImage,
    *,
    file_header: bool,
    section_headers: bool,
    symbols: bool,
    program_headers: bool,
    relocs: bool,
    notes: bool = False,
    dynamic: bool = False,
    dyn_syms: bool = False,
) -> List[str]:
    lines: List[str] = []
    if file_header:
        lines.append("ELF Header:")
        lines.append("  Class:                             ELF64")
        lines.append("  Data:                              2's complement, little endian")
        lines.append("  Machine:                           StackVM")
        lines.append("  Type:                              %s" % _ET_NAMES.get(image.e_type, "%#x" % image.e_type))
        lines.append("  Entry point address:               0x%x" % image.entry)
        lines.append("  Number of section headers:         %d" % len(image.sections))
        lines.append("  Number of program headers:         %d" % len(image.program_headers))
    if section_headers:
        lines.append("Section Headers:")
        lines.append("  [Nr] Name              Type            Address          Off    Size   ES Flg Lk Inf Al")
        for index, section in enumerate(image.sections):
            lines.append(
                "  [%2d] %-17s %-15s %016x %06x %06x %2d %3s %2d %3d %2d"
                % (
                    index,
                    section.name[:17],
                    _SHT_NAMES.get(section.typ, "%#x" % section.typ),
                    section.addr,
                    section.offset,
                    section.size,
                    section.entsize,
                    _section_flag_chars(section),
                    section.link,
                    section.info,
                    section.align,
                )
            )
    if program_headers:
        lines.append("Program Headers:")
        lines.append("  Type           Offset             VirtAddr           FileSiz            MemSiz             Flg Align")
        for phdr in image.program_headers:
            lines.append(
                "  %-14s 0x%016x 0x%016x 0x%016x 0x%016x %s 0x%x"
                % (
                    _PT_NAMES.get(phdr.typ, "%#x" % phdr.typ),
                    phdr.offset,
                    phdr.vaddr,
                    phdr.filesz,
                    phdr.memsz,
                    _phdr_flag_chars(phdr.flags),
                    phdr.align,
                )
            )
    if symbols:
        lines.extend(_format_symbol_table(".symtab", image.symbols))
        # GNU readelf -s also prints the dynamic symbol table when present.
        if image.dynamic_symbols:
            lines.extend(_format_symbol_table(".dynsym", image.dynamic_symbols))
    elif dyn_syms:
        lines.extend(_format_symbol_table(".dynsym", image.dynamic_symbols))
    if relocs:
        if not image.relocations:
            lines.append("There are no relocations in this file.")
        else:
            lines.append("Relocation section contains %d entries:" % len(image.relocations))
            lines.append("  Offset          Type               Sym. Name + Addend")
            for reloc in image.relocations:
                lines.append(
                    "  %016x  %-18s %s + %d"
                    % (
                        reloc.offset,
                        _RELOC_NAMES.get(reloc.typ, "%#x" % reloc.typ),
                        reloc.symbol_name,
                        reloc.addend,
                    )
                )
    if notes:
        if not image.notes:
            lines.append("There are no notes in this file.")
        for note in image.notes:
            lines.append("Displaying notes found in: %s" % note.section_name)
            lines.append("  Owner                Data size    Description")
            if note.typ == NT_GNU_BUILD_ID and note.name == "GNU":
                lines.append(
                    "  %-20s 0x%08x   NT_GNU_BUILD_ID (unique build ID bitstring)"
                    % (note.name, len(note.desc))
                )
                lines.append("    Build ID: %s" % note.desc.hex())
            else:
                lines.append(
                    "  %-20s 0x%08x   %#x" % (note.name, len(note.desc), note.typ)
                )
    if dynamic:
        if not image.dynamic:
            lines.append("There is no dynamic section in this file.")
        else:
            lines.append(
                "Dynamic section contains %d entries:" % len(image.dynamic)
            )
            lines.append("  Tag                Type           Name/Value")
            for entry in image.dynamic:
                name = _DT_NAMES.get(entry.tag, "%#x" % entry.tag)
                lines.append(
                    "  0x%016x (%-12s) 0x%x" % (entry.tag, name, entry.value)
                )
    return lines


def run_readelf(argv: Sequence[str]) -> int:
    # add_help=False: readelf (like GNU readelf) uses -h for the file header and
    # -H/--help for usage, so the default -h help action must be disabled.
    parser = argparse.ArgumentParser(prog="stackvm-readelf", add_help=False)
    parser.add_argument("-H", "--help", action="help", help="show this help message and exit")
    parser.add_argument("files", nargs="+")
    parser.add_argument("-a", "--all", action="store_true")
    parser.add_argument("-h", "--file-header", action="store_true")
    parser.add_argument("-S", "--section-headers", "--sections", action="store_true", dest="section_headers")
    parser.add_argument("-s", "--syms", "--symbols", action="store_true", dest="symbols")
    parser.add_argument("-l", "--program-headers", "--segments", action="store_true", dest="program_headers")
    parser.add_argument("-r", "--relocs", action="store_true")
    parser.add_argument("-n", "--notes", action="store_true")
    parser.add_argument("-d", "--dynamic", action="store_true")
    parser.add_argument("--dyn-syms", action="store_true", dest="dyn_syms")
    args = parser.parse_args(argv)

    any_selected = any(
        [
            args.all,
            args.file_header,
            args.section_headers,
            args.symbols,
            args.program_headers,
            args.relocs,
            args.notes,
            args.dynamic,
            args.dyn_syms,
        ]
    )
    if not any_selected:
        parser.error("no output requested; use -h/-S/-s/-l/-r/-n/-d/--dyn-syms or -a")
    try:
        for path in args.files:
            data = _read_bytes(path)
            if is_pe_bytes(data):
                for line in format_pe_readelf(
                    path,
                    read_pe_image(data),
                    file_header=args.all or args.file_header,
                    section_headers=args.all or args.section_headers,
                    relocs=args.all or args.relocs,
                ):
                    print(line)
                continue
            image = image_from_bytes(data)
            for line in format_readelf(
                path,
                image,
                file_header=args.all or args.file_header,
                section_headers=args.all or args.section_headers,
                symbols=args.all or args.symbols,
                program_headers=args.all or args.program_headers,
                relocs=args.all or args.relocs,
                notes=args.all or args.notes,
                dynamic=args.all or args.dynamic,
                dyn_syms=args.dyn_syms,
            ):
                print(line)
    except (HostToolError, ValueError) as exc:
        print("stackvm-readelf: %s" % exc, file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# objdump
# ---------------------------------------------------------------------------


def _disassemble_section(section) -> List[str]:
    base = section.addr
    fmt = lambda line, addr: "%8x:\t%s" % (addr + base, line)
    text = disassemble(section.data, 0, len(section.data), {}, fmt)
    return text.splitlines() if text else []


def format_objdump(
    path: str,
    image: ElfImage,
    *,
    disassemble_code: bool,
    section_headers: bool,
    syms: bool,
    relocs: bool,
) -> List[str]:
    lines = ["", "%s:     file format elf64-stackvm" % path]
    if section_headers:
        lines.append("")
        lines.append("Sections:")
        lines.append("Idx Name          Size      VMA               Type")
        idx = 0
        for section in image.sections:
            if section.typ == SHT_NULL:
                continue
            kind = "BSS" if section.is_nobits else ("TEXT" if section.is_exec else "DATA")
            lines.append(
                "%3d %-13s %08x  %016x  %s"
                % (idx, section.name, section.size, section.addr, kind)
            )
            idx += 1
    if syms:
        lines.append("")
        lines.append("SYMBOL TABLE:")
        for symbol in image.symbols:
            letter = nm_symbol_letter(symbol, image)
            section = symbol.section_name or ("*UND*" if symbol.is_undefined else "*ABS*")
            lines.append(
                "%016x %s %-14s %08x %s"
                % (symbol.value, letter, section, symbol.size, symbol.name)
            )
    if relocs and image.relocations:
        lines.append("")
        lines.append("RELOCATION RECORDS:")
        lines.append("OFFSET           TYPE              VALUE")
        for reloc in image.relocations:
            lines.append(
                "%016x %-17s %s+0x%x"
                % (reloc.offset, _RELOC_NAMES.get(reloc.typ, "%#x" % reloc.typ), reloc.symbol_name, reloc.addend)
            )
    if disassemble_code:
        # Map section-relative addresses to leading "<symbol>:" labels.
        for section in image.sections:
            if section.typ != SHT_PROGBITS or not section.is_exec or not section.data:
                continue
            lines.append("")
            lines.append("Disassembly of section %s:" % section.name)
            labels = {
                symbol.value: "\n%016x <%s>:" % (symbol.value, symbol.name)
                for symbol in image.symbols
                if symbol.section_name == section.name and symbol.typ == STT_FUNC
            }
            base = section.addr
            fmt = lambda line, addr: "%8x:\t%s" % (addr + base, line)
            text = disassemble(
                section.data,
                0,
                len(section.data),
                {},
                fmt,
                {addr - base: label for addr, label in labels.items()},
            )
            if text:
                lines.extend(text.splitlines())
    return lines


def run_objdump(argv: Sequence[str]) -> int:
    # add_help=False: objdump (like GNU objdump) uses -h for section headers and
    # -H/--help for usage, so the default -h help action must be disabled.
    parser = argparse.ArgumentParser(prog="stackvm-objdump", add_help=False)
    parser.add_argument("-H", "--help", action="help", help="show this help message and exit")
    parser.add_argument("files", nargs="+")
    parser.add_argument("-d", "--disassemble", action="store_true")
    parser.add_argument("-h", "--section-headers", "--headers", action="store_true", dest="section_headers")
    parser.add_argument("-t", "--syms", action="store_true")
    parser.add_argument("-r", "--reloc", action="store_true", dest="relocs")
    parser.add_argument("-x", "--all-headers", action="store_true", dest="all_headers")
    args = parser.parse_args(argv)

    selected = any([args.disassemble, args.section_headers, args.syms, args.relocs, args.all_headers])
    if not selected:
        parser.error("no output requested; use -d/-h/-t/-r/-x")
    try:
        for path in args.files:
            data = _read_bytes(path)
            if is_pe_bytes(data):
                for line in format_pe_objdump(
                    path,
                    read_pe_image(data),
                    disassemble_code=args.disassemble,
                    section_headers=args.section_headers or args.all_headers,
                    relocs=args.relocs or args.all_headers,
                ):
                    print(line)
                continue
            image = image_from_bytes(data)
            for line in format_objdump(
                path,
                image,
                disassemble_code=args.disassemble,
                section_headers=args.section_headers or args.all_headers,
                syms=args.syms or args.all_headers,
                relocs=args.relocs or args.all_headers,
            ):
                print(line)
    except (HostToolError, ValueError) as exc:
        print("stackvm-objdump: %s" % exc, file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# PE/COFF inspection (UEFI ``.efi`` images, workstream D1b.1)
#
# PE images have their own structure (DOS+PE headers, RVA-based sections, a
# base-relocation directory) rather than the ELF section/symbol model, so the
# readelf/objdump runners detect ``MZ`` and route here instead of through the
# ELF image path.
# ---------------------------------------------------------------------------


def load_pe(path: str) -> PeImage:
    return read_pe_image(_read_bytes(path))


def _pe_section_flag_chars(section) -> str:
    chars = []
    if section.characteristics & IMAGE_SCN_CNT_CODE:
        chars.append("CODE")
    if section.characteristics & IMAGE_SCN_CNT_INITIALIZED_DATA:
        chars.append("IDATA")
    if section.characteristics & IMAGE_SCN_CNT_UNINITIALIZED_DATA:
        chars.append("UDATA")
    perm = ""
    perm += "r" if section.characteristics & IMAGE_SCN_MEM_READ else "-"
    perm += "w" if section.characteristics & IMAGE_SCN_MEM_WRITE else "-"
    perm += "x" if section.characteristics & IMAGE_SCN_MEM_EXECUTE else "-"
    chars.append(perm)
    if section.characteristics & IMAGE_SCN_MEM_DISCARDABLE:
        chars.append("DISCARD")
    return ",".join(chars)


_PE_DIRECTORY_NAMES = {
    5: "BASE RELOCATION",
    6: "DEBUG",
}


def format_pe_readelf(
    path: str,
    pe: PeImage,
    *,
    file_header: bool,
    section_headers: bool,
    relocs: bool,
) -> List[str]:
    lines: List[str] = []
    if file_header:
        lines.append("PE Header:")
        lines.append("  Magic:                             PE32+")
        lines.append("  Machine:                           StackVM (0x%04x)" % pe.machine)
        lines.append(
            "  Subsystem:                         %s (%d)"
            % (SUBSYSTEM_NAMES.get(pe.subsystem, "Unknown"), pe.subsystem)
        )
        lines.append(
            "  Type:                              %s"
            % ("DLL" if pe.characteristics & IMAGE_FILE_DLL else "EXE")
        )
        lines.append("  ImageBase:                         0x%x" % pe.image_base)
        lines.append("  AddressOfEntryPoint:               0x%x" % pe.entry_point)
        lines.append("  SectionAlignment:                  0x%x" % pe.section_alignment)
        lines.append("  FileAlignment:                     0x%x" % pe.file_alignment)
        lines.append("  SizeOfImage:                       0x%x" % pe.size_of_image)
        lines.append("  SizeOfHeaders:                     0x%x" % pe.size_of_headers)
        lines.append("  Number of sections:                %d" % len(pe.sections))
        lines.append("Data Directories:")
        for index, (rva, size) in enumerate(pe.data_directories):
            if not rva and not size:
                continue
            lines.append(
                "  [%2d] %-16s VirtualAddress 0x%08x Size 0x%x"
                % (index, _PE_DIRECTORY_NAMES.get(index, ""), rva, size)
            )
    if section_headers:
        lines.append("Section Headers:")
        lines.append("  [Nr] Name             VirtAddr         VirtSize Off    RawSize Flags")
        for index, section in enumerate(pe.sections):
            lines.append(
                "  [%2d] %-16s %016x %08x %06x %07x %s"
                % (
                    index,
                    section.name[:16],
                    section.virtual_address,
                    section.virtual_size,
                    section.raw_pointer,
                    section.raw_size,
                    _pe_section_flag_chars(section),
                )
            )
    if relocs:
        dir64 = [
            (rva, typ) for rva, typ in pe.base_relocations if typ == IMAGE_REL_BASED_DIR64
        ]
        if not pe.base_relocations:
            lines.append("There are no base relocations in this file.")
        else:
            lines.append(
                "Base relocation section contains %d entries (%d DIR64):"
                % (len(pe.base_relocations), len(dir64))
            )
            lines.append("  RVA               Type")
            for rva, typ in pe.base_relocations:
                name = "DIR64" if typ == IMAGE_REL_BASED_DIR64 else ("ABSOLUTE" if typ == 0 else "%#x" % typ)
                lines.append("  %016x  %s" % (rva, name))
    return lines


def format_pe_objdump(
    path: str,
    pe: PeImage,
    *,
    disassemble_code: bool,
    section_headers: bool,
    relocs: bool,
) -> List[str]:
    lines = ["", "%s:     file format pe32+-stackvm" % path]
    if section_headers:
        lines.append("")
        lines.append("Sections:")
        lines.append("Idx Name          Size      VMA               Type")
        for idx, section in enumerate(pe.sections):
            kind = (
                "BSS"
                if section.is_uninitialized
                else ("TEXT" if section.is_code else "DATA")
            )
            lines.append(
                "%3d %-13s %08x  %016x  %s"
                % (idx, section.name, section.virtual_size, section.virtual_address, kind)
            )
    if relocs:
        dir64 = [r for r in pe.base_relocations if r[1] == IMAGE_REL_BASED_DIR64]
        if dir64:
            lines.append("")
            lines.append("BASE RELOCATION RECORDS:")
            lines.append("RVA              TYPE")
            for rva, _typ in dir64:
                lines.append("%016x DIR64" % rva)
    if disassemble_code:
        for section in pe.sections:
            if not section.is_code or not section.data:
                continue
            lines.append("")
            lines.append("Disassembly of section %s:" % section.name)
            base = section.virtual_address
            # Disassemble the file-backed bytes up to the section's virtual size.
            # The raw payload is zero-padded to the file alignment; an extra pad
            # keeps an instruction whose operands straddle the boundary in range.
            end = min(section.virtual_size, len(section.data))
            buffer = section.data + b"\x00" * 16
            fmt = lambda line, addr: "%8x:\t%s" % (addr + base, line)
            text = disassemble(buffer, 0, end, {}, fmt)
            if text:
                lines.extend(text.splitlines())
    return lines


# ---------------------------------------------------------------------------
# objcopy / strip (ELF rewriting + flat binary extraction)
# ---------------------------------------------------------------------------


def elf_to_binary(image: ElfImage, only_sections: Optional[Sequence[str]] = None) -> bytes:
    """Extract a flat boot image: allocated section bytes placed at their VMA.

    Trailing ``NOBITS`` (``.bss``) is not emitted.  When *only_sections* is
    given, only those sections contribute (the common ``objcopy -O binary -j
    .text`` boot-image extraction).
    """
    keep = [
        section
        for section in image.sections
        if section.is_alloc
        and not section.is_nobits
        and section.size > 0
        and (only_sections is None or section.name in only_sections)
    ]
    if not keep:
        return b""
    base = min(section.addr for section in keep)
    end = max(section.addr + section.size for section in keep)
    buf = bytearray(end - base)
    for section in keep:
        start = section.addr - base
        buf[start : start + len(section.data)] = section.data
    return bytes(buf)


def _rebuild_object(obj: StackVMObject, keep) -> StackVMObject:
    """Return a copy of *obj* keeping only sections for which ``keep(section)``.

    Section bytes are re-laid-out into fresh code/data segments and every
    symbol/relocation offset is remapped; symbols and relocations that belong to
    dropped sections are removed.
    """
    new_code = bytearray()
    new_data = bytearray()
    new_sections: List[ObjectSection] = []
    old_to_new_index = {}
    # delta[(segment, old_section_index)] = new_offset - old_offset
    delta = {}
    for old_index, section in enumerate(obj.sections):
        if not keep(section):
            continue
        buf = new_code if section.segment == ObjectSegment.CODE else new_data
        segment_bytes = obj.code if section.segment == ObjectSegment.CODE else obj.data
        if section.alignment > 1:
            buf.extend(b"\0" * ((-len(buf)) % section.alignment))
        new_offset = len(buf)
        if not section.is_nobits:
            buf.extend(segment_bytes[section.offset : section.offset + section.size])
        delta[(section.segment, old_index)] = new_offset - section.offset
        old_to_new_index[old_index] = len(new_sections)
        new_sections.append(
            ObjectSection(
                section.name,
                new_offset,
                section.size,
                section.alignment,
                section.segment,
                section.flags,
            )
        )

    new_symbols: List[ObjectSymbol] = []
    symbol_old_to_new = {}
    for old_symbol_index, symbol in enumerate(obj.symbols):
        if symbol.is_undefined:
            new_value = 0
            new_section_index = None
        elif symbol.section_index is not None:
            if symbol.section_index not in old_to_new_index:
                continue  # symbol lived in a dropped section
            new_value = symbol.value + delta[(symbol.segment, symbol.section_index)]
            new_section_index = old_to_new_index[symbol.section_index]
        else:
            new_value = symbol.value
            new_section_index = None
        symbol_old_to_new[old_symbol_index] = len(new_symbols)
        new_symbols.append(
            ObjectSymbol(
                symbol.name,
                new_value,
                symbol.size,
                symbol.segment,
                symbol.binding,
                symbol.typ,
                symbol.flags,
                new_section_index,
            )
        )

    new_relocations: List[ObjectRelocation] = []
    for reloc in obj.relocations:
        if reloc.section_index is None or reloc.section_index not in old_to_new_index:
            continue
        if reloc.symbol_index not in symbol_old_to_new:
            continue
        new_relocations.append(
            ObjectRelocation(
                reloc.offset + delta[(reloc.segment, reloc.section_index)],
                symbol_old_to_new[reloc.symbol_index],
                reloc.segment,
                reloc.typ,
                old_to_new_index[reloc.section_index],
            )
        )

    return StackVMObject(
        bytes(new_code),
        bytes(new_data),
        new_symbols,
        new_relocations,
        obj.default_alignment,
        obj.data_alignment,
        new_sections,
    )


def _drop_local_symbols(obj: StackVMObject) -> StackVMObject:
    """Strip-all for objects: drop local symbols not needed by a relocation.

    Globals/weaks and undefined symbols are retained (an object linked later
    still needs them), as are any local symbols a relocation points at; the
    relocation symbol indices are remapped to the surviving table.
    """
    referenced = {reloc.symbol_index for reloc in obj.relocations}
    keep_indices = [
        index
        for index, symbol in enumerate(obj.symbols)
        if symbol.binding != SymbolBinding.LOCAL or index in referenced
    ]
    old_to_new = {old: new for new, old in enumerate(keep_indices)}
    new_symbols = [obj.symbols[index] for index in keep_indices]
    new_relocations = [
        ObjectRelocation(
            reloc.offset,
            old_to_new[reloc.symbol_index],
            reloc.segment,
            reloc.typ,
            reloc.section_index,
        )
        for reloc in obj.relocations
    ]
    return StackVMObject(
        obj.code,
        obj.data,
        new_symbols,
        new_relocations,
        obj.default_alignment,
        obj.data_alignment,
        obj.sections,
    )


class _ExecSymbol:
    """Minimal duck-typed symbol consumed by ``dumps_elf_executable``."""

    def __init__(self, symbol: ElfSymbolInfo):
        self.name = symbol.name
        self.address = symbol.value
        self.size = symbol.size
        self.section_name = symbol.section_name
        self.binding = (
            SymbolBinding.LOCAL
            if symbol.binding == STB_LOCAL
            else SymbolBinding.WEAK
            if symbol.binding == STB_WEAK
            else SymbolBinding.GLOBAL
        )
        self.typ = (
            SymbolType.FUNCTION
            if symbol.typ == STT_FUNC
            else SymbolType.OBJECT
            if symbol.typ == STT_OBJECT
            else SymbolType.NOTYPE
        )


class _ExecLayout:
    def __init__(self, section):
        self.name = section.name
        self.address = section.addr
        self.size = section.size
        self.segment = ObjectSegment.CODE if section.is_exec else ObjectSegment.DATA


def _rewrite_elf(
    data: bytes,
    *,
    strip_debug: bool = False,
    strip_all: bool = False,
    remove_sections: Sequence[str] = (),
    keep_only: Optional[Sequence[str]] = None,
) -> bytes:
    """Return a new ELF with sections filtered per the requested operations."""
    image = read_elf_image(data)
    remove = set(remove_sections)

    def drop(name: str) -> bool:
        if keep_only is not None and name not in keep_only:
            return True
        if name in remove:
            return True
        if (strip_debug or strip_all) and _is_debug_section_name(name):
            return True
        return False

    if image.e_type == ET_REL:
        obj = loads_sbo_or_elf(data)
        rebuilt = _rebuild_object(obj, lambda section: not drop(section.name))
        if strip_all:
            rebuilt = _drop_local_symbols(rebuilt)
        return dumps_elf_object(rebuilt)

    # Executable: re-emit loadable image with filtered symbol/debug content.
    executable = loads_sbc_or_elf(data)
    debug_info = b"" if (strip_debug or strip_all or ".debug" in remove) else executable.debug_info
    executable = StackVMExecutable(
        executable.memory,
        executable.code_segment_end,
        executable.data_segment_start,
        executable.file_size,
        executable.base_relocations,
        debug_info,
    )
    layouts = [
        _ExecLayout(section)
        for section in image.sections
        if section.is_alloc and section.typ in (SHT_PROGBITS, SHT_NOBITS)
    ]
    if strip_all or ".symtab" in remove:
        symbols = None
    else:
        symbols = [_ExecSymbol(symbol) for symbol in image.symbols]
    return dumps_elf_executable(executable, layouts or None, symbols)


def loads_sbo_or_elf(data: bytes) -> StackVMObject:
    from .elf_file import loads_elf_object

    if data[:4] == ELF_MAGIC:
        return loads_elf_object(data)
    return loads_sbo(data)


def loads_sbc_or_elf(data: bytes) -> StackVMExecutable:
    from .elf_file import loads_elf_executable

    if data[:4] == ELF_MAGIC:
        return loads_elf_executable(data)
    return loads_sbc(data)


def _normalize_to_elf(data: bytes) -> bytes:
    if data[:4] == ELF_MAGIC:
        return data
    if data[:8] == SBO_MAGIC:
        return dumps_elf_object(loads_sbo(data))
    if data[:8] in _SBC_MAGICS:
        return dumps_elf_executable(loads_sbc(data))
    raise HostToolError("unrecognized input format")


def run_objcopy(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="stackvm-objcopy", add_help=True)
    parser.add_argument("-O", "--output-target", dest="output_target", default=None)
    parser.add_argument("-I", "--input-target", dest="input_target", default=None)
    parser.add_argument("-j", "--only-section", action="append", default=[], dest="only_sections")
    parser.add_argument("-R", "--remove-section", action="append", default=[], dest="remove_sections")
    parser.add_argument("-S", "--strip-all", action="store_true", dest="strip_all")
    parser.add_argument("-g", "--strip-debug", action="store_true", dest="strip_debug")
    parser.add_argument("infile")
    parser.add_argument("outfile", nargs="?", default=None)
    args = parser.parse_args(argv)

    outfile = args.outfile or args.infile
    try:
        data = _read_bytes(args.infile)
        if _is_archive(data):
            raise HostToolError("objcopy does not operate on archives")
        if args.output_target == "binary":
            image = image_from_bytes(data)
            payload = elf_to_binary(image, args.only_sections or None)
            with open(outfile, "wb") as fl:
                fl.write(payload)
            return 0
        elf = _normalize_to_elf(data)
        result = _rewrite_elf(
            elf,
            strip_debug=args.strip_debug,
            strip_all=args.strip_all,
            remove_sections=args.remove_sections,
            keep_only=args.only_sections or None,
        )
        with open(outfile, "wb") as fl:
            fl.write(result)
    except HostToolError as exc:
        print("stackvm-objcopy: %s" % exc, file=sys.stderr)
        return 1
    return 0


def run_strip(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="stackvm-strip", add_help=True)
    parser.add_argument("-o", "--output", dest="output", default=None)
    parser.add_argument("-s", "--strip-all", action="store_true", dest="strip_all")
    parser.add_argument(
        "-g", "-d", "-S", "--strip-debug", action="store_true", dest="strip_debug"
    )
    parser.add_argument("-R", "--remove-section", action="append", default=[], dest="remove_sections")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)

    if len(args.files) > 1 and args.output is not None:
        parser.error("--output cannot be used with multiple input files")
    # Default action (no flag) is strip-all, matching GNU strip.
    strip_all = args.strip_all or not args.strip_debug
    try:
        for path in args.files:
            data = _read_bytes(path)
            if _is_archive(data):
                raise HostToolError("strip does not operate on archives")
            elf = _normalize_to_elf(data)
            result = _rewrite_elf(
                elf,
                strip_debug=args.strip_debug,
                strip_all=strip_all,
                remove_sections=args.remove_sections,
            )
            with open(args.output or path, "wb") as fl:
                fl.write(result)
    except HostToolError as exc:
        print("stackvm-strip: %s" % exc, file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# ranlib
# ---------------------------------------------------------------------------


def run_ranlib(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="stackvm-ranlib", add_help=True)
    parser.add_argument("archives", nargs="+")
    parser.add_argument(
        "-t", action="store_true", dest="touch", help="only update the archive timestamp (no-op)"
    )
    args = parser.parse_args(argv)
    try:
        for path in args.archives:
            data = _read_bytes(path)
            if not _is_archive(data):
                raise HostToolError("%s is not a StackVM archive" % path)
            archive = loads_sba(data)  # validates every member object
            if not args.touch:
                with open(path, "wb") as fl:
                    fl.write(dumps_sba(archive))  # canonical, index-refreshed rewrite
    except (HostToolError, ValueError) as exc:
        print("stackvm-ranlib: %s" % exc, file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# kallsyms
# ---------------------------------------------------------------------------


def _kallsyms_symbols(image: ElfImage) -> List[ElfSymbolInfo]:
    """Defined function/object symbols, sorted by address (i.e. ``nm -n``)."""
    symbols = [
        symbol
        for symbol in image.symbols
        if not symbol.is_undefined
        and not symbol.is_absolute
        and symbol.typ in (STT_FUNC, STT_OBJECT, STT_NOTYPE)
        and symbol.name
    ]
    symbols.sort(key=lambda s: (s.value, s.name))
    return symbols


def _kallsyms_from_nm(text: str) -> List[Tuple[int, str, str]]:
    """Parse ``nm`` output lines into ``(address, type_letter, name)`` triples."""
    result = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        value, letter, name = parts
        if letter in ("U", "w"):  # undefined symbols carry no address
            continue
        try:
            address = int(value, 16)
        except ValueError:
            continue
        result.append((address, letter, name))
    result.sort(key=lambda item: (item[0], item[2]))
    return result


def _escape_asm_string(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"')


def generate_kallsyms(entries: Sequence[Tuple[int, str, str]]) -> str:
    """Emit StackVM assembly describing the kernel symbol table.

    Layout (all in ``.data``):

    * ``kallsyms_num_syms``  : one ``.quad`` count
    * ``kallsyms_addresses`` : ``num_syms`` ``.quad`` absolute addresses
    * ``kallsyms_names``     : for each symbol, a length ``.byte`` followed by a
      type ``.byte`` (the ``nm`` letter) and the raw name bytes (``.ascii``)

    This is the uncompressed analogue of Linux's ``kallsyms.S`` and is directly
    consumable by :class:`ObjectAssembler`.
    """
    lines = [
        "; Generated by stackvm-kallsyms -- do not edit",
        ".data",
        ".globl kallsyms_num_syms",
        ":kallsyms_num_syms",
        ".quad %d" % len(entries),
        ".globl kallsyms_addresses",
        ":kallsyms_addresses",
    ]
    for address, _letter, _name in entries:
        lines.append(".quad 0x%x" % address)
    lines.append(".globl kallsyms_names")
    lines.append(":kallsyms_names")
    for _address, letter, name in entries:
        encoded = name.encode("utf-8")
        lines.append(".byte %d" % len(encoded))
        lines.append(".byte %d" % (ord(letter[0]) if letter else 0))
        lines.append('.ascii "%s"' % _escape_asm_string(name))
    return "\n".join(lines) + "\n"


def run_kallsyms(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="stackvm-kallsyms", add_help=True)
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="ELF/object input; omit (or '-') to read 'nm' output from stdin",
    )
    parser.add_argument("-o", "--output", default=None, help="output .S file (default: stdout)")
    parser.add_argument(
        "--from-nm",
        action="store_true",
        help="treat the input/stdin as 'nm' output instead of an ELF image",
    )
    args = parser.parse_args(argv)

    try:
        if args.input in (None, "-") or args.from_nm:
            if args.input in (None, "-"):
                text = sys.stdin.read()
            else:
                text = _read_bytes(args.input).decode("utf-8", "replace")
            entries = _kallsyms_from_nm(text)
        else:
            image = load_image(args.input)
            entries = [
                (symbol.value, nm_symbol_letter(symbol, image), symbol.name)
                for symbol in _kallsyms_symbols(image)
            ]
        output = generate_kallsyms(entries)
    except HostToolError as exc:
        print("stackvm-kallsyms: %s" % exc, file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w") as fl:
            fl.write(output)
    else:
        sys.stdout.write(output)
    return 0
