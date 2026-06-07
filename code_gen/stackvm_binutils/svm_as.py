"""Standalone StackVM object-file assembler (the ``svm-as`` core).

The historical :func:`assemble` helper assembles StackVM assembly *inline* into a
compiler :class:`BaseCmplObj` buffer.  This module reuses the very same
instruction encoder (:func:`encode_asm_line`) but wraps it with section
management, a symbol table and a relocation table so that hand-written ``.S`` /
``.s`` files (startup code, context switching, TLB flush routines) can be turned
into a relocatable ``.sbo`` object that the StackVM linker consumes.

The assembly *dialect* is unchanged from :mod:`assemble` (``:label`` definitions,
``4d1`` constants, ``LOAD-ABS_S8|SZ_8`` instructions, ``lRr[1]*:label`` and
``gRa*name`` references).  What this module adds on top is the GNU-``as``-style
directive layer (``.text`` / ``.data`` / ``.section`` / ``.globl`` / ``.align`` /
``.byte`` / ``.quad`` / ...) and object-file emission.

References are *not* resolved here (other than same-section PC-relative branches,
which GNU ``as`` also resolves locally): every symbolic reference becomes an
:class:`ObjectRelocation`, and any name that is referenced but not defined in the
file becomes an ``UNDEFINED`` :class:`ObjectSymbol` for the linker to resolve.
"""

import sys
from typing import Dict, List, Optional, Tuple

from .assemble import StackDict, AsmEmitEnv, encode_asm_line
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
from .linker import CODE_SECTIONS, DATA_SECTIONS, _matches_section
from ..LinkRef import LinkRef
from ...parser.type.align_util import align_up


class AssemblerError(Exception):
    """A user-facing assembler error (bad directive, undefined local, ...)."""


# Size in bytes for each fixed-width data directive.
_DATA_DIRECTIVE_SIZES = {
    ".byte": 1,
    ".short": 2,
    ".hword": 2,
    ".word": 4,
    ".long": 4,
    ".int": 4,
    ".quad": 8,
}


def _section_kind(name: str) -> Tuple[ObjectSegment, SectionFlags]:
    """Map a section *name* onto its (segment, default-flags) per linker rules.

    Mirrors the linker's recognised output-section families so that an
    unsupported section name fails at assemble time (with a clear message)
    rather than deep inside the linker.
    """
    for base in CODE_SECTIONS:
        if _matches_section(name, base):
            return ObjectSegment.CODE, SectionFlags.EXECUTABLE
    for base in DATA_SECTIONS:
        if _matches_section(name, base):
            if base == ".rodata":
                return ObjectSegment.DATA, SectionFlags.READ_ONLY
            if base == ".bss":
                return ObjectSegment.DATA, SectionFlags.NOBITS
            return ObjectSegment.DATA, SectionFlags.NONE
    raise AssemblerError(
        "unsupported section '%s': name must belong to a known linker family "
        "(%s)" % (name, ", ".join(sorted(CODE_SECTIONS | DATA_SECTIONS)))
    )


class _Section(object):
    __slots__ = ("name", "segment", "flags", "alignment", "memory", "nobits_size")

    def __init__(self, name, segment, flags, alignment):
        self.name = name
        self.segment = segment
        self.flags = flags
        self.alignment = alignment
        self.memory = bytearray()
        self.nobits_size = 0

    @property
    def is_nobits(self) -> bool:
        return bool(self.flags & SectionFlags.NOBITS)

    @property
    def size(self) -> int:
        return self.nobits_size if self.is_nobits else len(self.memory)


class _Symbol(object):
    __slots__ = (
        "name",
        "section",
        "value",
        "size",
        "binding",
        "typ",
        "defined",
        "referenced",
    )

    def __init__(self, name):
        self.name = name
        self.section: Optional[str] = None
        self.value: Optional[int] = None
        self.size: int = 0
        self.binding: Optional[SymbolBinding] = None
        self.typ: Optional[SymbolType] = None
        self.defined: bool = False
        self.referenced: bool = False


class _Relocation(object):
    __slots__ = ("section", "offset", "symbol", "typ", "addend")

    def __init__(self, section, offset, symbol, typ, addend):
        self.section = section
        self.offset = offset
        self.symbol = symbol
        self.typ = typ
        self.addend = addend


class _ObjectEnv(AsmEmitEnv):
    """Emit environment that records symbols/relocations for an object file."""

    def __init__(self, assembler: "ObjectAssembler"):
        self.asm = assembler

    @property
    def memory(self) -> bytearray:
        return self.asm._current_code_memory()

    def reference_code_or_global(self, name, is_code, is_l_rel, lnk_ref):
        self.asm._add_reference(name, lnk_ref)

    def define_code_label(self, name, pos):
        # Label definitions are intercepted by ObjectAssembler before reaching
        # the encoder, so this is only a defensive fallback.
        self.asm._define_label(name, pos)


class ObjectAssembler(object):
    """Assemble StackVM assembly text into a relocatable :class:`StackVMObject`."""

    def __init__(self):
        self.sections: Dict[str, _Section] = {}
        self.section_order: List[str] = []
        self.symbols: Dict[str, _Symbol] = {}
        self.relocations: List[_Relocation] = []
        self.constants: Dict[str, int] = {}
        self.local_vars = StackDict({})
        self.env = _ObjectEnv(self)
        self.current: Optional[str] = None
        self._switch_section(".text")

    # -- section management -------------------------------------------------
    def _get_or_create_section(
        self,
        name: str,
        segment: Optional[ObjectSegment] = None,
        flags: Optional[SectionFlags] = None,
    ) -> _Section:
        section = self.sections.get(name)
        if section is None:
            if segment is None or flags is None:
                segment, flags = _section_kind(name)
            section = _Section(name, segment, flags, 1)
            self.sections[name] = section
            self.section_order.append(name)
        return section

    def _switch_section(self, name, segment=None, flags=None):
        self._get_or_create_section(name, segment, flags)
        self.current = name

    def _current_section(self) -> _Section:
        return self.sections[self.current]

    def _current_code_memory(self) -> bytearray:
        section = self._current_section()
        if section.is_nobits:
            raise AssemblerError(
                "cannot emit code or data into NOBITS section '%s'" % section.name
            )
        return section.memory

    # -- symbols ------------------------------------------------------------
    def _sym(self, name: str) -> _Symbol:
        sym = self.symbols.get(name)
        if sym is None:
            sym = self.symbols[name] = _Symbol(name)
        return sym

    def _define_label(self, name: str, _pos_ignored: int = 0) -> None:
        section = self._current_section()
        sym = self._sym(name)
        if sym.defined:
            raise AssemblerError("symbol '%s' is already defined" % name)
        sym.defined = True
        sym.section = section.name
        sym.value = section.size
        if sym.typ is None:
            sym.typ = (
                SymbolType.FUNCTION
                if section.segment == ObjectSegment.CODE
                else SymbolType.OBJECT
            )

    def _add_reference(self, name: str, lnk_ref: LinkRef) -> None:
        section = self._current_section()
        sym = self._sym(name)
        sym.referenced = True
        # Resolve a backward, same-section PC-relative reference in place, just
        # like the inline assembler does -- no relocation needed (and GNU ``as``
        # behaves the same).  Forward refs, cross-section refs and all absolute
        # refs become relocations for the linker.
        if (
            lnk_ref.relocation_type == RelocationType.PCREL8
            and sym.defined
            and sym.section == section.name
        ):
            lnk_ref.try_fill_ref_rel(section.memory, sym.value)
            return
        self.relocations.append(
            _Relocation(
                section.name,
                lnk_ref.pos,
                name,
                RelocationType(lnk_ref.relocation_type),
                lnk_ref.addend,
            )
        )

    # -- top level ----------------------------------------------------------
    def assemble_text(self, text: str) -> None:
        lines = text.split("\n")
        for number, raw in enumerate(lines, start=1):
            line = _strip_comment(raw).strip()
            if not line:
                continue
            try:
                self._assemble_line(line)
            except (AssemblerError, ValueError, SyntaxError, TypeError,
                    LookupError, NotImplementedError) as exc:
                if not exc.args:
                    exc.args = ("",)
                exc.args = exc.args + ("At Line %u" % number,)
                raise

    def _assemble_line(self, line: str) -> None:
        if line.startswith("."):
            self._handle_directive(line)
        elif line.startswith(":") and "*" not in line:
            self._define_label(line[1:].strip())
        else:
            encode_asm_line(self.env, line, self.local_vars, {})

    # -- directives ---------------------------------------------------------
    def _handle_directive(self, line: str) -> None:
        name, _, rest = line.partition(" ")
        if "\t" in name:  # tolerate tab between directive and operands
            name, _, rest = line.partition("\t")
        name = name.strip()
        rest = rest.strip()

        if name in (".text", ".data", ".rodata", ".bss"):
            self._switch_section(name)
        elif name == ".section":
            self._directive_section(rest)
        elif name in (".globl", ".global"):
            for sym_name in _split_args(rest):
                self._sym(sym_name).binding = SymbolBinding.GLOBAL
        elif name == ".weak":
            for sym_name in _split_args(rest):
                self._sym(sym_name).binding = SymbolBinding.WEAK
        elif name == ".local":
            for sym_name in _split_args(rest):
                self._sym(sym_name).binding = SymbolBinding.LOCAL
        elif name in (".align", ".balign"):
            self._directive_align(rest, is_p2=False)
        elif name == ".p2align":
            self._directive_align(rest, is_p2=True)
        elif name in _DATA_DIRECTIVE_SIZES:
            self._directive_data(name, rest)
        elif name == ".ascii":
            self._directive_ascii(rest, nul=False)
        elif name in (".asciz", ".string"):
            self._directive_ascii(rest, nul=True)
        elif name in (".zero", ".skip", ".space"):
            self._directive_zero(rest)
        elif name in (".set", ".equ"):
            self._directive_set(rest)
        elif name in (".comm", ".lcomm"):
            self._directive_comm(rest, is_local=name == ".lcomm")
        elif name == ".type":
            self._directive_type(rest)
        elif name == ".size":
            self._directive_size(rest)
        elif name in _IGNORED_DIRECTIVES or name.startswith(".cfi"):
            return
        else:
            # Unknown directive: warn but keep going, like GNU ``as``.
            print("warning: ignoring unknown directive '%s'" % name, file=sys.stderr)

    def _directive_section(self, rest: str) -> None:
        args = _split_args(rest)
        if not args:
            raise AssemblerError(".section requires a name")
        section_name = args[0]
        segment, flags = _section_kind(section_name)
        # Honour an explicit flags string ("ax", "aw", ...) when present.
        if len(args) > 1:
            flag_str = _parse_string(args[1]) if args[1].startswith('"') else args[1]
            if "x" in flag_str:
                segment = ObjectSegment.CODE
                flags = flags | SectionFlags.EXECUTABLE
        self._switch_section(section_name, segment, flags)

    def _directive_align(self, rest: str, is_p2: bool) -> None:
        args = _split_args(rest)
        if not args:
            raise AssemblerError("alignment directive requires an argument")
        value = self._eval_int(args[0])
        boundary = (1 << value) if is_p2 else value
        if boundary <= 0 or (boundary & (boundary - 1)) != 0:
            raise AssemblerError("alignment must be a positive power of two: %r" % boundary)
        section = self._current_section()
        section.alignment = max(section.alignment, boundary)
        if section.is_nobits:
            section.nobits_size = align_up(section.nobits_size, boundary)
        else:
            padded = align_up(len(section.memory), boundary)
            section.memory.extend(b"\0" * (padded - len(section.memory)))

    def _directive_data(self, name: str, rest: str) -> None:
        size = _DATA_DIRECTIVE_SIZES[name]
        section = self._current_section()
        if section.is_nobits:
            raise AssemblerError(
                "cannot emit data into NOBITS section '%s'" % section.name
            )
        for token in _split_args(rest):
            value = self._try_eval_int(token)
            if value is None:
                # A symbolic operand: only an 8-byte absolute pointer is
                # representable as a relocation.
                if size != 8:
                    raise AssemblerError(
                        "symbol '%s' may only appear in an 8-byte (.quad) value"
                        % token
                    )
                pos = len(section.memory)
                section.memory.extend(b"\0" * 8)
                ref = LinkRef(pos, relocation_type=RelocationType.ABS8, addend=0)
                self._add_reference(token, ref)
            else:
                section.memory.extend(
                    (value & ((1 << (size * 8)) - 1)).to_bytes(size, "little")
                )

    def _directive_ascii(self, rest: str, nul: bool) -> None:
        section = self._current_section()
        if section.is_nobits:
            raise AssemblerError(
                "cannot emit data into NOBITS section '%s'" % section.name
            )
        for token in _split_args(rest):
            data = _parse_string(token)
            section.memory.extend(data)
            if nul:
                section.memory.append(0)

    def _directive_zero(self, rest: str) -> None:
        args = _split_args(rest)
        if not args:
            raise AssemblerError(".zero/.skip requires a byte count")
        count = self._eval_int(args[0])
        if count < 0:
            raise AssemblerError(".zero/.skip count must be non-negative")
        section = self._current_section()
        if section.is_nobits:
            section.nobits_size += count
        else:
            section.memory.extend(b"\0" * count)

    def _directive_set(self, rest: str) -> None:
        args = _split_args(rest)
        if len(args) != 2:
            raise AssemblerError(".set/.equ requires NAME, VALUE")
        self.constants[args[0]] = self._eval_int(args[1])

    def _directive_comm(self, rest: str, is_local: bool) -> None:
        args = _split_args(rest)
        if len(args) < 2:
            raise AssemblerError(".comm/.lcomm requires NAME, SIZE[, ALIGN]")
        sym_name = args[0]
        size = self._eval_int(args[1])
        alignment = self._eval_int(args[2]) if len(args) > 2 else 1
        if alignment <= 0 or (alignment & (alignment - 1)) != 0:
            raise AssemblerError(".comm alignment must be a power of two")
        bss = self._get_or_create_section(".bss")
        bss.alignment = max(bss.alignment, alignment)
        bss.nobits_size = align_up(bss.nobits_size, alignment)
        sym = self._sym(sym_name)
        if sym.defined:
            raise AssemblerError("symbol '%s' is already defined" % sym_name)
        sym.defined = True
        sym.section = ".bss"
        sym.value = bss.nobits_size
        sym.size = size
        sym.typ = SymbolType.OBJECT
        if sym.binding is None:
            sym.binding = SymbolBinding.LOCAL if is_local else SymbolBinding.GLOBAL
        bss.nobits_size += size

    def _directive_type(self, rest: str) -> None:
        args = _split_args(rest)
        if len(args) < 2:
            return
        kind = args[1].lstrip("@%").lower()
        sym = self._sym(args[0])
        if kind == "function":
            sym.typ = SymbolType.FUNCTION
        elif kind == "object":
            sym.typ = SymbolType.OBJECT

    def _directive_size(self, rest: str) -> None:
        args = _split_args(rest)
        if len(args) < 2:
            return
        value = self._try_eval_int(args[1])
        if value is not None:
            self._sym(args[0]).size = value

    # -- integer expression evaluation -------------------------------------
    def _try_eval_int(self, token: str) -> Optional[int]:
        token = token.strip()
        if not token:
            return None
        if token in self.constants:
            return self.constants[token]
        negate = False
        body = token
        if body.startswith(("+", "-")):
            negate = body[0] == "-"
            body = body[1:].strip()
            if body in self.constants:
                value = self.constants[body]
                return -value if negate else value
        if body.startswith("'") and body.endswith("'") and len(body) >= 3:
            data = _parse_string('"' + body[1:-1] + '"')
            if len(data) == 1:
                return -data[0] if negate else data[0]
            return None
        try:
            value = int(body, 0)
        except ValueError:
            return None
        return -value if negate else value

    def _eval_int(self, token: str) -> int:
        value = self._try_eval_int(token)
        if value is None:
            raise AssemblerError("expected an integer expression, got %r" % token)
        return value

    # -- object emission ----------------------------------------------------
    def to_object(self, default_alignment: int = 0) -> StackVMObject:
        ordered = self._ordered_sections()
        # Drop empty placeholder sections (e.g. the implicit ``.text`` created
        # for a file that only emits ``.data``) that carry no content, symbols
        # or relocations.
        used = {sym.section for sym in self.symbols.values() if sym.defined}
        used.update(reloc.section for reloc in self.relocations)
        ordered = [
            name for name in ordered
            if self.sections[name].size > 0 or name in used
        ]
        section_index = {name: i for i, name in enumerate(ordered)}

        # Assign each section a segment-relative offset and build the two
        # segment byte blobs (CODE / DATA), mirroring Compilation.to_stackvm_object.
        section_offset: Dict[str, int] = {}
        code = bytearray()
        data = bytearray()
        data_alignment = 1
        for segment, blob in (
            (ObjectSegment.CODE, code),
            (ObjectSegment.DATA, data),
        ):
            for name in ordered:
                section = self.sections[name]
                if section.segment != segment or section.is_nobits:
                    continue
                if segment == ObjectSegment.DATA:
                    data_alignment = max(data_alignment, section.alignment)
                offset = align_up(len(blob), section.alignment)
                blob.extend(b"\0" * (offset - len(blob)))
                section_offset[name] = offset
                blob.extend(section.memory)
            logical_end = len(blob)
            for name in ordered:
                section = self.sections[name]
                if section.segment != segment or not section.is_nobits:
                    continue
                if segment == ObjectSegment.DATA:
                    data_alignment = max(data_alignment, section.alignment)
                logical_end = align_up(logical_end, section.alignment)
                section_offset[name] = logical_end
                logical_end += section.nobits_size

        sections = [
            ObjectSection(
                name,
                section_offset[name],
                self.sections[name].size,
                self.sections[name].alignment,
                self.sections[name].segment,
                self.sections[name].flags,
            )
            for name in ordered
        ]

        symbols, symbol_index = self._build_symbols(section_index, section_offset)
        relocations = self._build_relocations(
            symbol_index, section_index, section_offset, code, data
        )

        obj = StackVMObject(
            bytes(code),
            bytes(data),
            symbols,
            relocations,
            default_alignment,
            data_alignment,
            sections,
        )
        validate_object(obj)
        return obj

    def _ordered_sections(self) -> List[str]:
        priority = {name: i for i, name in enumerate(_SECTION_PRIORITY)}

        def key(name: str):
            section = self.sections[name]
            family = len(_SECTION_PRIORITY)
            for base, prio in priority.items():
                if _matches_section(name, base):
                    family = prio
                    break
            return (int(section.segment), family, name)

        return sorted(self.section_order, key=key)

    def _build_symbols(self, section_index, section_offset):
        symbols: List[ObjectSymbol] = []
        symbol_index: Dict[str, int] = {}
        names = [
            name
            for name, sym in self.symbols.items()
            if sym.defined or sym.referenced
        ]
        # Defined symbols first (sorted), then undefined -- deterministic.
        names.sort(key=lambda n: (not self.symbols[n].defined, n))
        for name in names:
            sym = self.symbols[name]
            symbol_index[name] = len(symbols)
            if sym.defined:
                idx = section_index[sym.section]
                segment = self.sections[sym.section].segment
                symbols.append(
                    ObjectSymbol(
                        name,
                        section_offset[sym.section] + sym.value,
                        sym.size,
                        segment,
                        sym.binding if sym.binding is not None else SymbolBinding.LOCAL,
                        sym.typ if sym.typ is not None else SymbolType.NOTYPE,
                        section_index=idx,
                    )
                )
            else:
                symbols.append(
                    ObjectSymbol(
                        name,
                        0,
                        0,
                        ObjectSegment.CODE,
                        sym.binding if sym.binding is not None else SymbolBinding.GLOBAL,
                        sym.typ if sym.typ is not None else SymbolType.NOTYPE,
                        SymbolFlags.UNDEFINED,
                    )
                )
        return symbols, symbol_index

    def _build_relocations(
        self, symbol_index, section_index, section_offset, code, data
    ):
        relocations: List[ObjectRelocation] = []
        for reloc in self.relocations:
            section = self.sections[reloc.section]
            blob = code if section.segment == ObjectSegment.CODE else data
            patch = section_offset[reloc.section] + reloc.offset
            blob[patch : patch + 8] = (reloc.addend & ((1 << 64) - 1)).to_bytes(
                8, "little"
            )
            relocations.append(
                ObjectRelocation(
                    patch,
                    symbol_index[reloc.symbol],
                    section.segment,
                    reloc.typ,
                    section_index[reloc.section],
                )
            )
        relocations.sort(
            key=lambda rel: (int(rel.segment), rel.offset, rel.symbol_index)
        )
        return relocations


# Output-section ordering (matches the linker's default section order so the
# emitted object is laid out predictably).
_SECTION_PRIORITY = (
    ".text",
    ".init.text",
    ".init_array",
    ".fini_array",
    ".data",
    ".data..percpu",
    ".tdata",
    ".rodata",
    ".bss",
)

# Directives that carry no semantics for object emission (debug/metadata).
_IGNORED_DIRECTIVES = {
    ".file",
    ".ident",
    ".loc",
    ".line",
    ".weakref",
    ".previous",
    ".p2alignw",
    ".p2alignl",
}


def _strip_comment(line: str) -> str:
    """Remove a ``;`` or ``#`` comment, respecting double-quoted strings.

    ``;`` is the historical StackVM comment character; ``#`` is also treated as
    a line comment so that GNU-style ``#`` comments and leftover ``cpp`` line
    markers (``# 123 "file"``) in preprocessed ``.S`` output are ignored.
    """
    in_string = False
    escape = False
    for i, ch in enumerate(line):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in ";#":
            return line[:i]
    return line


def _split_args(rest: str) -> List[str]:
    """Split a directive operand list on commas, respecting quoted strings."""
    args: List[str] = []
    current = ""
    in_string = False
    escape = False
    for ch in rest:
        if in_string:
            current += ch
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            current += ch
        elif ch == ",":
            args.append(current.strip())
            current = ""
        else:
            current += ch
    args.append(current.strip())
    return [a for a in args if a != ""]


_STRING_ESCAPES = {
    "n": ord("\n"),
    "t": ord("\t"),
    "r": ord("\r"),
    "0": 0,
    "\\": ord("\\"),
    '"': ord('"'),
    "'": ord("'"),
    "a": 7,
    "b": 8,
    "f": 12,
    "v": 11,
}


def _parse_string(token: str) -> bytes:
    """Decode a double-quoted assembly string (with C-style escapes)."""
    token = token.strip()
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        raise AssemblerError("expected a quoted string, got %r" % token)
    body = token[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _STRING_ESCAPES:
                out.append(_STRING_ESCAPES[nxt])
                i += 2
                continue
            if nxt == "x":
                j = i + 2
                hexs = ""
                while j < len(body) and body[j] in "0123456789abcdefABCDEF":
                    hexs += body[j]
                    j += 1
                if hexs:
                    out.append(int(hexs, 16) & 0xFF)
                    i = j
                    continue
            out.append(ord(nxt))
            i += 2
            continue
        out.append(ord(ch))
        i += 1
    return bytes(out)


def assemble_object(text: str, default_alignment: int = 0) -> StackVMObject:
    """Assemble *text* (a whole ``.s`` translation unit) into a StackVMObject."""
    assembler = ObjectAssembler()
    assembler.assemble_text(text)
    return assembler.to_object(default_alignment)
