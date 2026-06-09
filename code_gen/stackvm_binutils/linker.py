from collections import defaultdict
from dataclasses import dataclass, field
import fnmatch
import hashlib
import os
import re
from typing import (
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    TextIO,
    Tuple,
    Union,
)

from ...parser.type.align_util import align_up
from .archive_file import (
    SBA_MAGIC,
    StackVMArchive,
    load_sba,
)
from .executable_file import StackVMExecutable, dumps_sbc, write_sbc
from .elf_file import ELF_MAGIC, load_elf_object, write_elf_executable
from .debug_info import (
    DEBUG_SECTION_NAME,
    DebugFunctionRecord,
    DebugLineRecord,
    StackVMDebugInfo,
    dumps_debug,
    loads_debug,
)
from .lib_util_asm_impl.names import ISAAC_RUNTIME_LINK_NAMES
from .object_file import (
    SBO_MAGIC,
    ObjectRelocation,
    ObjectSegment,
    ObjectSymbol,
    RelocationType,
    SectionFlags,
    StackVMObject,
    SymbolBinding,
    SymbolType,
    load_sbo,
    validate_object,
)
from ..percpu import (
    PERCPU_END_SYMBOLS,
    PERCPU_LINKER_DEFINED_SYMBOLS,
    PERCPU_SECTION_NAME,
    PERCPU_SIZE_SYMBOLS,
    PERCPU_START_SYMBOLS,
)
from ..tls import (
    TLS_ALIGN_SYMBOL,
    TLS_LINKER_DEFINED_SYMBOLS,
    TLS_SECTION_NAME,
    TLS_SIZE_SYMBOL,
    TLS_TEMPLATE_END_SYMBOL,
    TLS_TEMPLATE_START_SYMBOL,
)

DEFAULT_CODE_BASE = 0
DEFAULT_DATA_BASE = 0x1000
DEFAULT_DATA_ALIGNMENT = 0x1000
DEFAULT_SECTION_ORDER = (
    ".text",
    ".init.text",
    ".init_array",
    ".fini_array",
    ".data",
    PERCPU_SECTION_NAME,
    TLS_SECTION_NAME,
    ".rodata",
    ".bss",
)
CODE_SECTIONS = {".text", ".init.text"}
DATA_SECTIONS = {
    ".init_array",
    ".fini_array",
    ".data",
    PERCPU_SECTION_NAME,
    TLS_SECTION_NAME,
    ".rodata",
    ".bss",
}
DEBUG_SECTIONS = {DEBUG_SECTION_NAME}
LINKER_DEFINED_SYMBOLS = {
    "__init_begin",
    "__init_end",
    "__init_array_start",
    "__init_array_end",
    "__fini_array_start",
    "__fini_array_end",
    "__bss_start",
    "__bss_end",
    "_start",
    "_end",
}
ALL_LINKER_DEFINED_SYMBOLS = (
    LINKER_DEFINED_SYMBOLS | PERCPU_LINKER_DEFINED_SYMBOLS | TLS_LINKER_DEFINED_SYMBOLS
)


class LinkerError(Exception):
    pass


class DuplicateSymbolError(LinkerError):
    pass


class UndefinedSymbolError(LinkerError):
    def __init__(self, symbols: Iterable[str]):
        self.symbols = tuple(sorted(set(symbols)))
        super().__init__("unresolved symbols: " + ", ".join(self.symbols))


def _matches_section(name: str, base: str) -> bool:
    return name == base or name.startswith(base + ".")


def _is_debug_section(name: str) -> bool:
    return any(_matches_section(name, base) for base in DEBUG_SECTIONS)


def _init_priority_section_key(name: str, base: str) -> int:
    if name == base:
        return 65535
    suffix = name[len(base) + 1 :]
    try:
        return int(suffix, 10)
    except ValueError:
        return 65535


@dataclass(frozen=True)
class LinkerScript:
    sections: Tuple[str, ...] = DEFAULT_SECTION_ORDER
    entry: Optional[str] = None
    keep: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "keep", tuple(self.keep))
        sections = tuple(self.sections)
        if PERCPU_SECTION_NAME not in sections:
            old_orders = (
                {name for name in DEFAULT_SECTION_ORDER if name != PERCPU_SECTION_NAME},
                {
                    name
                    for name in DEFAULT_SECTION_ORDER
                    if name not in {PERCPU_SECTION_NAME, TLS_SECTION_NAME}
                },
            )
            if set(sections) in old_orders:
                insert_at = sections.index(".data") + 1
                sections = (
                    sections[:insert_at]
                    + (PERCPU_SECTION_NAME,)
                    + sections[insert_at:]
                )
        if TLS_SECTION_NAME not in sections:
            order_without_tls = tuple(
                name for name in DEFAULT_SECTION_ORDER if name != TLS_SECTION_NAME
            )
            if set(sections) == set(order_without_tls):
                insert_at = sections.index(PERCPU_SECTION_NAME) + 1
                sections = (
                    sections[:insert_at] + (TLS_SECTION_NAME,) + sections[insert_at:]
                )
        object.__setattr__(self, "sections", sections)
        if len(sections) != len(DEFAULT_SECTION_ORDER) or set(sections) != set(
            DEFAULT_SECTION_ORDER
        ):
            raise ValueError(
                "linker script must contain each supported output section exactly once"
            )
        if sections.index(".init.text") < sections.index(".text"):
            raise ValueError(".init.text must be placed after .text")
        first_data = min(sections.index(name) for name in DATA_SECTIONS)
        last_code = max(sections.index(name) for name in CODE_SECTIONS)
        if last_code > first_data:
            raise ValueError("all code sections must precede data sections")
        if sections[-1] != ".bss":
            raise ValueError(".bss must be the final output section")

    def output_section_for(self, input_section_name: str) -> str:
        matches = [
            name for name in self.sections if _matches_section(input_section_name, name)
        ]
        if not matches:
            raise LinkerError("unsupported input section: %s" % input_section_name)
        return max(matches, key=len)


def parse_linker_script(text: str) -> LinkerScript:
    """Parse output-section declarations from a constrained GNU-style script.

    Beyond the supported output-section ordering this also recognises the
    ``ENTRY(symbol)`` command (used for ``vmlinux.lds`` and friends) and any
    ``KEEP(*(pattern))`` directives, whose matched input-section patterns are
    treated as garbage-collection roots when ``--gc-sections`` is in effect.
    """

    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*?$|#.*?$", "", text, flags=re.MULTILINE)
    entry_match = re.search(r"\bENTRY\s*\(\s*([A-Za-z_.$][\w.$]*)\s*\)", text)
    entry = entry_match.group(1) if entry_match else None
    keep: List[str] = []
    for keep_body in re.findall(r"\bKEEP\s*\(([^)]*\))", text):
        for pattern in re.findall(r"\*\s*\(\s*([^)]*?)\s*\)", keep_body):
            keep.extend(part for part in pattern.replace(",", " ").split() if part)
        # KEEP(symbol) / KEEP(*name) forms without an inner *(...) group.
        for token in re.findall(r"[\w.$*]+", re.sub(r"\*\s*\([^)]*\)", "", keep_body)):
            if token not in {"KEEP"}:
                keep.append(token)
    supported = "|".join(re.escape(name) for name in DEFAULT_SECTION_ORDER)
    sections = re.findall(r"(?<![\w.])(%s)\s*:" % supported, text)
    if not sections:
        sections = [
            line.strip()
            for line in text.splitlines()
            if line.strip() in DEFAULT_SECTION_ORDER
        ]
    if not sections:
        raise ValueError("linker script does not define any supported sections")
    return LinkerScript(tuple(sections), entry, tuple(dict.fromkeys(keep)))


def load_linker_script(path: str) -> LinkerScript:
    with open(path, "r") as fl:
        return parse_linker_script(fl.read())


@dataclass(frozen=True)
class VersionNode:
    """A single node of a GNU symbol-version script."""

    name: str
    globals: Tuple[str, ...] = ()
    locals: Tuple[str, ...] = ()
    parent: Optional[str] = None


@dataclass(frozen=True)
class VersionScript:
    nodes: Tuple[VersionNode, ...] = ()

    def _matches(self, patterns: Sequence[str], name: str) -> bool:
        for pattern in patterns:
            if pattern == name:
                return True
            if any(ch in pattern for ch in "*?[") and fnmatch.fnmatchcase(name, pattern):
                return True
        return False

    def is_local(self, name: str) -> bool:
        """Return True when *name* is hidden (matched by ``local:`` only)."""

        for node in self.nodes:
            if self._matches(node.globals, name):
                return False
        for node in self.nodes:
            if self._matches(node.locals, name):
                return True
        return False

    def version_for(self, name: str) -> Optional[str]:
        for node in self.nodes:
            if self._matches(node.globals, name):
                return node.name
        return None


def parse_version_script(text: str) -> VersionScript:
    """Parse a constrained GNU version script into :class:`VersionScript`.

    Supports named and anonymous nodes, ``global:``/``local:`` blocks with
    plain names or glob patterns, and ``} PARENT;`` version dependencies.
    """

    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*?$|#.*?$", "", text, flags=re.MULTILINE)
    nodes: List[VersionNode] = []
    pos = 0
    pattern = re.compile(r"([A-Za-z_.$][\w.$]*)?\s*\{", re.DOTALL)
    while True:
        match = pattern.search(text, pos)
        if match is None:
            break
        name = match.group(1) or "*ANON*"
        body_start = match.end()
        depth = 1
        index = body_start
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        if depth:
            raise ValueError("unterminated version node '%s'" % name)
        body = text[body_start : index - 1]
        trailer = text[index:]
        parent_match = re.match(r"\s*([A-Za-z_.$][\w.$]*)\s*;", trailer)
        parent = None
        if parent_match:
            parent = parent_match.group(1)
            pos = index + parent_match.end()
        else:
            semi = trailer.find(";")
            pos = index + (semi + 1 if semi >= 0 else 0)
        globals_: List[str] = []
        locals_: List[str] = []
        current = "global"
        # ``global:`` / ``local:`` are visibility labels that may share a
        # statement with the names they introduce, so tokenize them separately
        # from the (semicolon/space separated) symbol names and patterns.
        for token in re.findall(r"global\s*:|local\s*:|[^\s;]+", body):
            compact = token.replace(" ", "").lower()
            if compact == "global:":
                current = "global"
                continue
            if compact == "local:":
                current = "local"
                continue
            entry_name = token.strip().rstrip(";").strip()
            if not entry_name:
                continue
            (globals_ if current == "global" else locals_).append(entry_name)
        nodes.append(
            VersionNode(name, tuple(globals_), tuple(locals_), parent)
        )
    if not nodes:
        raise ValueError("version script does not define any version nodes")
    return VersionScript(tuple(nodes))


def load_version_script(path: str) -> VersionScript:
    with open(path, "r") as fl:
        return parse_version_script(fl.read())


@dataclass
class LinkOptions:
    allow_undefined: bool = False
    code_base: int = DEFAULT_CODE_BASE
    data_base: int = DEFAULT_DATA_BASE
    data_alignment: int = DEFAULT_DATA_ALIGNMENT
    runtime_aliases: bool = True
    symbol_aliases: Mapping[str, str] = field(default_factory=dict)
    script: LinkerScript = field(default_factory=LinkerScript)
    percpu_copies: int = 1
    gc_sections: bool = False
    entry_symbol: str = "_start"
    keep_symbols: Tuple[str, ...] = ()
    build_id: Optional[str] = None
    emit_relocs: bool = False
    version_script: Optional[VersionScript] = None
    shared: bool = False
    pie: bool = False
    soname: Optional[str] = None
    needed: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.code_base < 0 or self.data_base < 0:
            raise ValueError("segment base addresses must be non-negative")
        if self.percpu_copies < 1:
            raise ValueError("percpu copies must be a positive integer")
        if self.data_alignment <= 0 or (
            self.data_alignment & (self.data_alignment - 1)
        ):
            raise ValueError("data alignment must be a power of two")
        if isinstance(self.script, str):
            self.script = parse_linker_script(self.script)
        if not isinstance(self.script, LinkerScript):
            raise TypeError("script must be a LinkerScript or linker script text")
        if isinstance(self.version_script, str):
            self.version_script = parse_version_script(self.version_script)
        if self.version_script is not None and not isinstance(
            self.version_script, VersionScript
        ):
            raise TypeError(
                "version_script must be a VersionScript or version script text"
            )
        self.keep_symbols = tuple(self.keep_symbols)
        self.needed = tuple(self.needed)
        if self.script.entry is not None and self.entry_symbol == "_start":
            self.entry_symbol = self.script.entry


@dataclass
class ObjectInput:
    name: str
    obj: StackVMObject
    archive_name: Optional[str] = None

    @property
    def display_name(self) -> str:
        if self.archive_name is None:
            return self.name
        return "%s(%s)" % (self.archive_name, self.name)


@dataclass
class ArchiveInput:
    name: str
    archive: StackVMArchive
    whole_archive: bool = False


@dataclass
class ObjectLayout:
    name: str
    code_address: int
    code_size: int
    data_address: int
    data_size: int


@dataclass
class SectionLayout:
    name: str
    address: int
    size: int
    file_size: int
    segment: ObjectSegment
    input_sections: List[str] = field(default_factory=list)

    @property
    def end(self) -> int:
        return self.address + self.size


@dataclass
class LinkedSymbol:
    name: str
    address: int
    size: int
    segment: ObjectSegment
    binding: SymbolBinding
    typ: SymbolType
    object_name: str
    selected: bool = True
    section_name: str = ""


@dataclass
class EmittedRelocation:
    """A symbolic relocation retained in the linked image (``--emit-relocs``)."""

    offset: int
    symbol_name: str
    typ: RelocationType
    addend: int
    segment: ObjectSegment


@dataclass
class LinkResult:
    memory: bytes
    code_segment_end: int
    data_segment_start: int
    global_symbols: Dict[str, int]
    symbols: List[LinkedSymbol]
    unresolved_symbols: List[str]
    included_objects: List[str]
    object_layouts: List[ObjectLayout]
    section_layouts: List[SectionLayout]
    base_relocations: List[int] = field(default_factory=list)
    debug_info: bytes = b""
    removed_sections: List[str] = field(default_factory=list)
    build_id: bytes = b""
    emitted_relocations: List[EmittedRelocation] = field(default_factory=list)
    localized_symbols: List[str] = field(default_factory=list)
    dynamic_symbols: List[str] = field(default_factory=list)
    is_shared: bool = False
    is_pie: bool = False
    soname: Optional[str] = None
    needed: List[str] = field(default_factory=list)
    dynamic_imports: List[str] = field(default_factory=list)

    @property
    def symbol_addresses(self) -> Dict[str, int]:
        return self.global_symbols

    def to_executable(self) -> StackVMExecutable:
        bss = next(
            (layout for layout in self.section_layouts if layout.name == ".bss"),
            None,
        )
        file_size = (
            bss.address if bss is not None and bss.size > 0 else len(self.memory)
        )
        return StackVMExecutable(
            self.memory,
            self.code_segment_end,
            self.data_segment_start,
            file_size,
            tuple(self.base_relocations),
            self.debug_info,
        )

    def to_sbc(self) -> bytes:
        return dumps_sbc(self.to_executable())

    def to_elf(self) -> bytes:
        from .elf_file import dumps_elf_executable

        return dumps_elf_executable(
            self.to_executable(),
            self.section_layouts,
            self.symbols,
            build_id=self.build_id,
            emitted_relocations=self.emitted_relocations,
            shared=self.is_shared,
            pie=self.is_pie,
            soname=self.soname,
            needed=self.needed,
            dynamic_symbols=self.dynamic_symbols,
            dynamic_imports=self.dynamic_imports,
        )


@dataclass
class _Definition:
    object_index: int
    symbol_index: int


@dataclass
class _InputSection:
    object_index: int
    section_key: int
    name: str
    segment: ObjectSegment
    object_offset: int
    size: int
    alignment: int
    flags: SectionFlags
    data: bytes

    @property
    def key(self) -> Tuple[int, int]:
        return self.object_index, self.section_key

    @property
    def is_nobits(self) -> bool:
        return bool(self.flags & SectionFlags.NOBITS)


class _AliasResolver:
    def __init__(
        self,
        runtime_aliases: bool,
        symbol_aliases: Mapping[str, str],
    ):
        self._aliases: Dict[str, str] = {}
        if runtime_aliases:
            for raw_name, mangled_name in ISAAC_RUNTIME_LINK_NAMES.items():
                self._aliases[raw_name] = raw_name
                self._aliases[mangled_name] = raw_name
        self._aliases.update(symbol_aliases)
        for name in self._aliases:
            self.canonical(name)

    def canonical(self, name: str) -> str:
        current = name
        seen = set()
        while current in self._aliases and self._aliases[current] != current:
            if current in seen:
                raise ValueError("symbol alias cycle involving '%s'" % name)
            seen.add(current)
            current = self._aliases[current]
        return current

    def names_for(self, canonical_name: str) -> Set[str]:
        names = {canonical_name}
        for name in self._aliases:
            if self.canonical(name) == canonical_name:
                names.add(name)
        return names


def _read_addend(memory: bytearray, offset: int) -> int:
    return int.from_bytes(memory[offset : offset + 8], "little", signed=True)


def _write_value(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 8] = (value & ((1 << 64) - 1)).to_bytes(8, "little")


def _is_undefined_weak(symbol: ObjectSymbol) -> bool:
    return symbol.is_undefined and symbol.binding == SymbolBinding.WEAK


class _ObjectLinker:
    def __init__(self, options: LinkOptions):
        self.options = options
        self.aliases = _AliasResolver(
            options.runtime_aliases,
            options.symbol_aliases,
        )
        self.linker_defined_keys = {
            self.aliases.canonical(name) for name in ALL_LINKER_DEFINED_SYMBOLS
        }
        self.included: List[ObjectInput] = []
        self.selected: Dict[str, _Definition] = {}

    def _symbol_for_definition(self, definition: _Definition) -> ObjectSymbol:
        return self.included[definition.object_index].obj.symbols[
            definition.symbol_index
        ]

    def _register_definition(
        self,
        object_index: int,
        symbol_index: int,
        symbol: ObjectSymbol,
    ) -> None:
        key = self.aliases.canonical(symbol.name)
        if key in self.linker_defined_keys:
            raise DuplicateSymbolError(
                "'%s' is reserved as a linker-defined symbol" % symbol.name
            )
        previous = self.selected.get(key)
        if previous is None:
            self.selected[key] = _Definition(object_index, symbol_index)
            return
        previous_symbol = self._symbol_for_definition(previous)
        previous_is_weak = previous_symbol.binding == SymbolBinding.WEAK
        current_is_weak = symbol.binding == SymbolBinding.WEAK
        if previous_is_weak and not current_is_weak:
            self.selected[key] = _Definition(object_index, symbol_index)
        elif not previous_is_weak and not current_is_weak:
            previous_object = self.included[previous.object_index].display_name
            current_object = self.included[object_index].display_name
            raise DuplicateSymbolError(
                "multiple strong definitions of '%s': %s and %s"
                % (key, previous_object, current_object)
            )

    def include_object(self, obj_input: ObjectInput) -> None:
        try:
            validate_object(obj_input.obj)
        except ValueError as exc:
            raise LinkerError("invalid object %s: %s" % (obj_input.display_name, exc))
        object_index = len(self.included)
        self.included.append(obj_input)
        for symbol_index, symbol in enumerate(obj_input.obj.symbols):
            if symbol.is_undefined or symbol.binding == SymbolBinding.LOCAL:
                continue
            self._register_definition(object_index, symbol_index, symbol)

    def _unresolved_global_keys(self) -> Set[str]:
        unresolved = set()
        for obj_input in self.included:
            for relocation in obj_input.obj.relocations:
                symbol = obj_input.obj.symbols[relocation.symbol_index]
                if symbol.binding == SymbolBinding.LOCAL:
                    continue
                if _is_undefined_weak(symbol):
                    continue
                key = self.aliases.canonical(symbol.name)
                if key not in self.selected and key not in self.linker_defined_keys:
                    unresolved.add(key)
        return unresolved

    @staticmethod
    def _section_key(
        object_index: int,
        has_sections: bool,
        section_index: Optional[int],
        segment: ObjectSegment,
    ) -> Tuple[int, int]:
        if has_sections:
            return object_index, int(section_index)
        return object_index, (-1 if segment == ObjectSegment.CODE else -2)

    def _unresolved_names(
        self, live_keys: Optional[Set[Tuple[int, int]]] = None
    ) -> Set[str]:
        unresolved = set()
        for object_index, obj_input in enumerate(self.included):
            obj = obj_input.obj
            for relocation in obj.relocations:
                if live_keys is not None:
                    reloc_key = self._section_key(
                        object_index,
                        bool(obj.sections),
                        relocation.section_index,
                        relocation.segment,
                    )
                    if reloc_key not in live_keys:
                        continue
                symbol = obj.symbols[relocation.symbol_index]
                if symbol.binding == SymbolBinding.LOCAL:
                    if symbol.is_undefined:
                        unresolved.add(symbol.name)
                    continue
                if _is_undefined_weak(symbol):
                    continue
                key = self.aliases.canonical(symbol.name)
                if key not in self.selected and key not in self.linker_defined_keys:
                    unresolved.add(symbol.name)
        return unresolved

    def _build_input_sections(self) -> List[_InputSection]:
        input_sections: List[_InputSection] = []
        for object_index, obj_input in enumerate(self.included):
            obj = obj_input.obj
            if obj.sections:
                for section_index, section in enumerate(obj.sections):
                    segment_data = (
                        obj.code if section.segment == ObjectSegment.CODE else obj.data
                    )
                    data = (
                        b""
                        if section.is_nobits
                        else segment_data[
                            section.offset : section.offset + section.size
                        ]
                    )
                    input_sections.append(
                        _InputSection(
                            object_index,
                            section_index,
                            section.name,
                            section.segment,
                            section.offset,
                            section.size,
                            section.alignment,
                            section.flags,
                            data,
                        )
                    )
            else:
                for section_key, name, segment, data, alignment in (
                    (-1, ".text", ObjectSegment.CODE, obj.code, 1),
                    (
                        -2,
                        ".data",
                        ObjectSegment.DATA,
                        obj.data,
                        obj.data_alignment,
                    ),
                ):
                    needed = (
                        bool(data)
                        or any(
                            not symbol.is_undefined and symbol.segment == segment
                            for symbol in obj.symbols
                        )
                        or any(
                            relocation.segment == segment
                            for relocation in obj.relocations
                        )
                    )
                    if needed:
                        input_sections.append(
                            _InputSection(
                                object_index,
                                section_key,
                                name,
                                segment,
                                0,
                                len(data),
                                alignment,
                                (
                                    SectionFlags.EXECUTABLE
                                    if segment == ObjectSegment.CODE
                                    else SectionFlags.NONE
                                ),
                                data,
                            )
                        )
        return input_sections

    def _is_keep_section(self, name: str) -> bool:
        for base in (".init_array", ".fini_array"):
            if _matches_section(name, base):
                return True
        for pattern in self.options.script.keep:
            if name == pattern:
                return True
            if any(ch in pattern for ch in "*?[") and fnmatch.fnmatchcase(
                name, pattern
            ):
                return True
            if _matches_section(name, pattern):
                return True
        return False

    def _reloc_target_section_key(
        self, object_index: int, relocation: ObjectRelocation
    ) -> Optional[Tuple[int, int]]:
        obj = self.included[object_index].obj
        symbol = obj.symbols[relocation.symbol_index]
        if symbol.binding == SymbolBinding.LOCAL:
            if symbol.is_undefined:
                return None
            return self._section_key(
                object_index, bool(obj.sections), symbol.section_index, symbol.segment
            )
        definition = self.selected.get(self.aliases.canonical(symbol.name))
        if definition is None:
            return None
        def_obj = self.included[definition.object_index].obj
        def_symbol = def_obj.symbols[definition.symbol_index]
        return self._section_key(
            definition.object_index,
            bool(def_obj.sections),
            def_symbol.section_index,
            def_symbol.segment,
        )

    def _compute_live_sections(
        self, input_sections: Sequence[_InputSection]
    ) -> Tuple[Set[Tuple[int, int]], List[str]]:
        all_keys = {section.key for section in input_sections}
        if not self.options.gc_sections:
            return all_keys, []
        by_key = {section.key: section for section in input_sections}
        edges: Dict[Tuple[int, int], Set[Tuple[int, int]]] = defaultdict(set)
        for object_index, obj_input in enumerate(self.included):
            obj = obj_input.obj
            for relocation in obj.relocations:
                source = self._section_key(
                    object_index,
                    bool(obj.sections),
                    relocation.section_index,
                    relocation.segment,
                )
                target = self._reloc_target_section_key(object_index, relocation)
                if target is not None and source in by_key and target in by_key:
                    edges[source].add(target)
        roots: Set[Tuple[int, int]] = set()
        for key, section in by_key.items():
            object_index, _section_key = key
            if not self.included[object_index].obj.sections:
                roots.add(key)  # legacy single-segment objects are not collectable
            elif _is_debug_section(section.name) or self._is_keep_section(section.name):
                roots.add(key)
        root_symbols = set(self.options.keep_symbols)
        root_symbols.add(self.aliases.canonical(self.options.entry_symbol))
        export_all = self.options.shared or self.options.pie
        for object_index, obj_input in enumerate(self.included):
            obj = obj_input.obj
            for symbol in obj.symbols:
                if symbol.is_undefined:
                    continue
                exported = export_all and symbol.binding != SymbolBinding.LOCAL
                if not exported and self.aliases.canonical(symbol.name) not in root_symbols:
                    continue
                key = self._section_key(
                    object_index, bool(obj.sections), symbol.section_index, symbol.segment
                )
                if key in by_key:
                    roots.add(key)
        live: Set[Tuple[int, int]] = set()
        stack = list(roots)
        while stack:
            key = stack.pop()
            if key in live:
                continue
            live.add(key)
            stack.extend(target for target in edges.get(key, ()) if target not in live)
        removed = sorted(
            "%s:%s"
            % (self.included[key[0]].display_name, by_key[key].name)
            for key in (all_keys - live)
        )
        return live, removed

    def include_archive(self, archive_input: ArchiveInput) -> None:
        if archive_input.whole_archive:
            # ``--whole-archive`` pulls in every member unconditionally, as if
            # the archive's objects had been listed individually.
            for member in archive_input.archive.members:
                self.include_object(
                    ObjectInput(member.name, member.obj, archive_input.name)
                )
            return
        remaining = list(archive_input.archive.members)
        # Scan to a fixpoint at this input position, matching traditional
        # left-to-right archive semantics.
        while True:
            unresolved = self._unresolved_global_keys()
            selected_index = None
            for index, member in enumerate(remaining):
                defined = {
                    self.aliases.canonical(symbol.name)
                    for symbol in member.obj.symbols
                    if not symbol.is_undefined and symbol.binding != SymbolBinding.LOCAL
                }
                if unresolved & defined:
                    selected_index = index
                    break
            if selected_index is None:
                return
            member = remaining.pop(selected_index)
            self.include_object(
                ObjectInput(member.name, member.obj, archive_input.name)
            )

    def process(self, inputs: Sequence[Union[ObjectInput, ArchiveInput]]) -> LinkResult:
        for link_input in inputs:
            if isinstance(link_input, ObjectInput):
                self.include_object(link_input)
            elif isinstance(link_input, ArchiveInput):
                self.include_archive(link_input)
            else:
                raise TypeError("unrecognized linker input: %r" % (link_input,))

        all_input_sections = self._build_input_sections()
        live_keys, removed_sections = self._compute_live_sections(all_input_sections)
        unresolved_names = self._unresolved_names(live_keys)
        # A shared object / PIE leaves its undefined references for the dynamic
        # loader to bind at run time (they are emitted as ``SHN_UNDEF`` imports in
        # ``.dynsym``), so they are not link-time errors -- matching ``ld``'s
        # default ``-shared`` behaviour.
        tolerate_undefined = (
            self.options.allow_undefined
            or self.options.shared
            or self.options.pie
        )
        if unresolved_names and not tolerate_undefined:
            raise UndefinedSymbolError(unresolved_names)
        return self._layout_and_relocate(
            sorted(unresolved_names),
            all_input_sections,
            live_keys,
            removed_sections,
        )

    def _layout_and_relocate(
        self,
        unresolved_names: List[str],
        all_input_sections: List[_InputSection],
        live_keys: Set[Tuple[int, int]],
        removed_sections: List[str],
    ) -> LinkResult:
        input_sections = [
            section for section in all_input_sections if section.key in live_keys
        ]

        section_lookup = {section.key: section for section in input_sections}
        debug_sections = [
            section for section in input_sections if _is_debug_section(section.name)
        ]
        debug_section_keys = {section.key for section in debug_sections}
        for section in debug_sections:
            if section.segment != ObjectSegment.DATA:
                raise LinkerError(".debug sections must use the DATA segment")
            if section.is_nobits:
                raise LinkerError(".debug sections cannot be NOBITS")
        for object_index, obj_input in enumerate(self.included):
            obj = obj_input.obj
            for symbol in obj.symbols:
                if symbol.is_undefined:
                    continue
                section_key = (
                    symbol.section_index
                    if obj.sections
                    else (-1 if symbol.segment == ObjectSegment.CODE else -2)
                )
                if (object_index, section_key) in debug_section_keys:
                    raise LinkerError(".debug sections cannot define ordinary symbols")
            for relocation in obj.relocations:
                section_key = (
                    relocation.section_index
                    if obj.sections
                    else (-1 if relocation.segment == ObjectSegment.CODE else -2)
                )
                if (object_index, section_key) in debug_section_keys:
                    raise LinkerError(".debug sections cannot contain relocations")
        members_by_output = {name: [] for name in self.options.script.sections}
        output_name_by_input_key = {}
        for section in input_sections:
            if section.key in debug_section_keys:
                continue
            output_name = self.options.script.output_section_for(section.name)
            output_name_by_input_key[section.key] = output_name
            expected_segment = (
                ObjectSegment.CODE
                if output_name in CODE_SECTIONS
                else ObjectSegment.DATA
            )
            if section.segment != expected_segment:
                raise LinkerError(
                    "section %s has the wrong segment for output section %s"
                    % (section.name, output_name)
                )
            if output_name == ".bss" and not section.is_nobits:
                raise LinkerError("input .bss sections must be NOBITS")
            if output_name != ".bss" and section.is_nobits:
                raise LinkerError(
                    "NOBITS section %s must be placed in .bss" % section.name
                )
            members_by_output[output_name].append(section)
        for name in (".init_array", ".fini_array"):
            members_by_output[name].sort(
                key=lambda section, base=name: _init_priority_section_key(
                    section.name, base
                )
            )

        memory = bytearray(self.options.code_base)
        input_section_addresses = {}
        section_layouts = []
        output_section_unit_sizes = {}
        output_section_alignments = {}

        def place_output_section(name: str) -> SectionLayout:
            members = members_by_output[name]
            if members:
                alignment = max(section.alignment for section in members)
                start = align_up(len(memory), alignment)
                memory.extend([0] * (start - len(memory)))
            else:
                alignment = 1
                start = len(memory)
            file_size = 0
            input_names = []
            for section in members:
                address = align_up(len(memory), section.alignment)
                memory.extend([0] * (address - len(memory)))
                input_section_addresses[section.key] = address
                input_names.append(
                    "%s:%s"
                    % (self.included[section.object_index].display_name, section.name)
                )
                if section.is_nobits:
                    memory.extend([0] * section.size)
                else:
                    memory.extend(section.data)
                    file_size += len(section.data)
            unit_size = len(memory) - start
            unit_file_size = file_size
            if (
                name == PERCPU_SECTION_NAME
                and unit_size > 0
                and self.options.percpu_copies > 1
            ):
                unit = bytes(memory[start : start + unit_size])
                for _copy_index in range(1, self.options.percpu_copies):
                    memory.extend(unit)
                file_size = unit_file_size * self.options.percpu_copies
            output_section_unit_sizes[name] = unit_size
            output_section_alignments[name] = alignment
            return SectionLayout(
                name,
                start,
                len(memory) - start,
                file_size,
                (ObjectSegment.CODE if name in CODE_SECTIONS else ObjectSegment.DATA),
                input_names,
            )

        for name in self.options.script.sections:
            if name not in CODE_SECTIONS:
                continue
            section_layouts.append(place_output_section(name))
        code_segment_end = len(memory)

        data_segment_start = align_up(
            max(code_segment_end, self.options.data_base),
            self.options.data_alignment,
        )
        memory.extend([0] * (data_segment_start - len(memory)))
        for name in self.options.script.sections:
            if name not in DATA_SECTIONS:
                continue
            section_layouts.append(place_output_section(name))

        layout_by_name = {layout.name: layout for layout in section_layouts}

        def section_for_symbol(
            object_index: int, symbol: ObjectSymbol
        ) -> _InputSection:
            obj = self.included[object_index].obj
            section_key = (
                symbol.section_index
                if obj.sections
                else (-1 if symbol.segment == ObjectSegment.CODE else -2)
            )
            return section_lookup[(object_index, section_key)]

        def symbol_address(object_index: int, symbol: ObjectSymbol) -> int:
            section = section_for_symbol(object_index, symbol)
            return (
                input_section_addresses[section.key]
                + symbol.value
                - section.object_offset
            )

        def symbol_is_live(object_index: int, symbol: ObjectSymbol) -> bool:
            obj = self.included[object_index].obj
            section_key = (
                symbol.section_index
                if obj.sections
                else (-1 if symbol.segment == ObjectSegment.CODE else -2)
            )
            return (object_index, section_key) in section_lookup

        layouts = []
        for object_index, obj_input in enumerate(self.included):
            object_sections = [
                section
                for section in input_sections
                if section.object_index == object_index
                and section.key not in debug_section_keys
            ]

            def segment_layout(
                segment: ObjectSegment, fallback: int
            ) -> Tuple[int, int]:
                regions = [
                    (
                        input_section_addresses[section.key],
                        input_section_addresses[section.key] + section.size,
                    )
                    for section in object_sections
                    if section.segment == segment
                ]
                if not regions:
                    return fallback, 0
                return min(start for start, _end in regions), sum(
                    end - start for start, end in regions
                )

            code_address, code_size = segment_layout(
                ObjectSegment.CODE, self.options.code_base
            )
            data_address, data_size = segment_layout(
                ObjectSegment.DATA, data_segment_start
            )
            layouts.append(
                ObjectLayout(
                    obj_input.display_name,
                    code_address,
                    code_size,
                    data_address,
                    data_size,
                )
            )

        object_selected_addresses = {
            key: symbol_address(
                definition.object_index,
                self._symbol_for_definition(definition),
            )
            for key, definition in self.selected.items()
            if symbol_is_live(
                definition.object_index, self._symbol_for_definition(definition)
            )
        }
        linker_symbol_sections = {
            "_start": ".text",
            "__init_begin": ".init.text",
            "__init_end": ".init.text",
            "__init_array_start": ".init_array",
            "__init_array_end": ".init_array",
            "__fini_array_start": ".fini_array",
            "__fini_array_end": ".fini_array",
            "__bss_start": ".bss",
            "__bss_end": ".bss",
            "_end": ".bss",
        }
        for name in PERCPU_START_SYMBOLS + PERCPU_END_SYMBOLS + PERCPU_SIZE_SYMBOLS:
            linker_symbol_sections[name] = PERCPU_SECTION_NAME
        for name in (
            TLS_TEMPLATE_START_SYMBOL,
            TLS_TEMPLATE_END_SYMBOL,
            TLS_SIZE_SYMBOL,
            TLS_ALIGN_SYMBOL,
        ):
            linker_symbol_sections[name] = TLS_SECTION_NAME
        percpu_layout = layout_by_name[PERCPU_SECTION_NAME]
        percpu_unit_size = output_section_unit_sizes.get(PERCPU_SECTION_NAME, 0)
        tls_layout = layout_by_name[TLS_SECTION_NAME]
        tls_size = output_section_unit_sizes.get(TLS_SECTION_NAME, 0)
        tls_align = output_section_alignments.get(TLS_SECTION_NAME, 1)
        linker_addresses = {
            "_start": layout_by_name[".text"].address,
            "__init_begin": layout_by_name[".init.text"].address,
            "__init_end": layout_by_name[".init.text"].end,
            "__init_array_start": layout_by_name[".init_array"].address,
            "__init_array_end": layout_by_name[".init_array"].end,
            "__fini_array_start": layout_by_name[".fini_array"].address,
            "__fini_array_end": layout_by_name[".fini_array"].end,
            "__bss_start": layout_by_name[".bss"].address,
            "__bss_end": layout_by_name[".bss"].end,
            "_end": len(memory),
        }
        for name in PERCPU_START_SYMBOLS:
            linker_addresses[name] = percpu_layout.address
        for name in PERCPU_END_SYMBOLS:
            linker_addresses[name] = percpu_layout.address + percpu_unit_size
        for name in PERCPU_SIZE_SYMBOLS:
            linker_addresses[name] = percpu_unit_size
        linker_addresses[TLS_TEMPLATE_START_SYMBOL] = tls_layout.address
        linker_addresses[TLS_TEMPLATE_END_SYMBOL] = tls_layout.address + tls_size
        linker_addresses[TLS_SIZE_SYMBOL] = tls_size
        linker_addresses[TLS_ALIGN_SYMBOL] = tls_align
        selected_addresses = dict(object_selected_addresses)
        selected_addresses.update(
            {
                self.aliases.canonical(name): address
                for name, address in linker_addresses.items()
            }
        )

        base_relocations = []
        emitted_relocations: List[EmittedRelocation] = []
        for object_index, obj_input in enumerate(self.included):
            for relocation in obj_input.obj.relocations:
                symbol = obj_input.obj.symbols[relocation.symbol_index]
                section_key = (
                    relocation.section_index
                    if obj_input.obj.sections
                    else (-1 if relocation.segment == ObjectSegment.CODE else -2)
                )
                if (object_index, section_key) not in section_lookup:
                    # Patch site lives in a garbage-collected section.
                    continue
                section = section_lookup[(object_index, section_key)]
                patch_address = (
                    input_section_addresses[section.key]
                    + relocation.offset
                    - section.object_offset
                )
                patch_addresses = [patch_address]
                if output_name_by_input_key.get(section.key) == PERCPU_SECTION_NAME:
                    percpu_unit_size = output_section_unit_sizes.get(
                        PERCPU_SECTION_NAME, 0
                    )
                    if percpu_unit_size > 0:
                        patch_addresses = [
                            patch_address + copy_index * percpu_unit_size
                            for copy_index in range(self.options.percpu_copies)
                        ]
                resolved_undefined_weak = False
                if symbol.binding == SymbolBinding.LOCAL:
                    target_address = (
                        None
                        if symbol.is_undefined
                        else symbol_address(object_index, symbol)
                    )
                else:
                    target_address = selected_addresses.get(
                        self.aliases.canonical(symbol.name)
                    )
                    if target_address is None and _is_undefined_weak(symbol):
                        target_address = 0
                        resolved_undefined_weak = True
                if target_address is None:
                    continue
                for current_patch_address in patch_addresses:
                    addend = _read_addend(memory, current_patch_address)
                    if self.options.emit_relocs:
                        emitted_relocations.append(
                            EmittedRelocation(
                                current_patch_address,
                                symbol.name,
                                relocation.typ,
                                addend,
                                relocation.segment,
                            )
                        )
                    if relocation.typ == RelocationType.ABS8:
                        value = target_address + addend
                        if (
                            relocation.segment == ObjectSegment.DATA
                            and not resolved_undefined_weak
                        ):
                            base_relocations.append(current_patch_address)
                    elif relocation.typ == RelocationType.PCREL8:
                        value = target_address + addend - (current_patch_address + 8)
                    else:
                        raise LinkerError(
                            "unsupported relocation type %r in %s"
                            % (relocation.typ, obj_input.display_name)
                        )
                    _write_value(memory, current_patch_address, value)

        linked_symbols = []
        for object_index, obj_input in enumerate(self.included):
            for symbol_index, symbol in enumerate(obj_input.obj.symbols):
                if symbol.is_undefined:
                    continue
                if not symbol_is_live(object_index, symbol):
                    continue
                selected = True
                if symbol.binding != SymbolBinding.LOCAL:
                    definition = self.selected[self.aliases.canonical(symbol.name)]
                    selected = (
                        definition.object_index == object_index
                        and definition.symbol_index == symbol_index
                    )
                linked_symbols.append(
                    LinkedSymbol(
                        symbol.name,
                        symbol_address(object_index, symbol),
                        symbol.size,
                        symbol.segment,
                        symbol.binding,
                        symbol.typ,
                        obj_input.display_name,
                        selected,
                        section_for_symbol(object_index, symbol).name,
                    )
                )

        global_symbols = {}
        for key, address in object_selected_addresses.items():
            for name in self.aliases.names_for(key):
                global_symbols[name] = address
            definition = self.selected[key]
            global_symbols[self._symbol_for_definition(definition).name] = address
        for name, address in linker_addresses.items():
            global_symbols[name] = address
            for alias in self.aliases.names_for(self.aliases.canonical(name)):
                global_symbols[alias] = address
            section_name = linker_symbol_sections[name]
            segment = layout_by_name[section_name].segment
            linked_symbols.append(
                LinkedSymbol(
                    name,
                    address,
                    0,
                    segment,
                    SymbolBinding.GLOBAL,
                    SymbolType.NOTYPE,
                    "<linker>",
                    True,
                    section_name,
                )
            )

        merged_debug_lines = []
        merged_debug_functions = []
        if debug_sections:
            sections_by_object_and_name: Dict[Tuple[int, str], List[_InputSection]] = {}
            for section in input_sections:
                if section.key in debug_section_keys:
                    continue
                sections_by_object_and_name.setdefault(
                    (section.object_index, section.name),
                    [],
                ).append(section)

            def relocate_debug_address(
                object_index: int,
                source_section_name: str,
                section_relative_address: int,
            ) -> int:
                if not source_section_name:
                    return section_relative_address
                candidates = sections_by_object_and_name.get(
                    (object_index, source_section_name),
                    [],
                )
                if len(candidates) != 1:
                    raise LinkerError(
                        "debug record references unknown or ambiguous section %s in %s"
                        % (
                            source_section_name,
                            self.included[object_index].display_name,
                        )
                    )
                section = candidates[0]
                return input_section_addresses[section.key] + section_relative_address

            for section in debug_sections:
                if not section.data:
                    continue
                try:
                    debug_info = loads_debug(section.data)
                except ValueError as exc:
                    raise LinkerError(
                        "invalid debug section in %s: %s"
                        % (self.included[section.object_index].display_name, exc)
                    ) from exc
                for record in debug_info.lines:
                    merged_debug_lines.append(
                        DebugLineRecord(
                            relocate_debug_address(
                                section.object_index,
                                record.section,
                                record.address,
                            ),
                            record.file,
                            record.line,
                            record.column,
                            "",
                        )
                    )
                for record in debug_info.functions:
                    merged_debug_functions.append(
                        DebugFunctionRecord(
                            record.name,
                            relocate_debug_address(
                                section.object_index,
                                record.section,
                                record.address,
                            ),
                            record.size,
                            record.frame_size,
                            record.return_address_offset,
                            record.previous_bp_offset,
                            "",
                        )
                    )
        merged_debug_lines.sort(key=lambda record: record.address)
        merged_debug_functions.sort(key=lambda record: record.address)
        debug_info = (
            dumps_debug(StackVMDebugInfo(merged_debug_lines, merged_debug_functions))
            if merged_debug_lines or merged_debug_functions
            else b""
        )

        # Symbol-version script: localize (hide) any matched global symbol and
        # remove it from the exported global table.
        localized_symbols: List[str] = []
        version_script = self.options.version_script
        if version_script is not None:
            for symbol in linked_symbols:
                if (
                    symbol.binding != SymbolBinding.LOCAL
                    and symbol.object_name != "<linker>"
                    and version_script.is_local(symbol.name)
                ):
                    symbol.binding = SymbolBinding.LOCAL
                    if symbol.name not in localized_symbols:
                        localized_symbols.append(symbol.name)
            for name in localized_symbols:
                global_symbols.pop(name, None)

        # Dynamic symbol table for shared objects / PIE: the defined globals this
        # object exports plus the undefined references it imports (which the
        # dynamic loader binds at run time).
        dynamic_symbols: List[str] = []
        dynamic_imports: List[str] = []
        if self.options.shared or self.options.pie:
            seen: Set[str] = set()
            for symbol in linked_symbols:
                if (
                    symbol.binding != SymbolBinding.LOCAL
                    and not symbol.name.startswith("__")
                    and symbol.name not in seen
                    and symbol.name in global_symbols
                ):
                    seen.add(symbol.name)
                    dynamic_symbols.append(symbol.name)
            for name in unresolved_names:
                if name not in seen:
                    seen.add(name)
                    dynamic_imports.append(name)

        build_id = self._compute_build_id(memory, sorted(base_relocations))

        return LinkResult(
            bytes(memory),
            code_segment_end,
            data_segment_start,
            global_symbols,
            linked_symbols,
            unresolved_names,
            [obj_input.display_name for obj_input in self.included],
            layouts,
            section_layouts,
            sorted(base_relocations),
            debug_info,
            removed_sections,
            build_id,
            emitted_relocations,
            sorted(localized_symbols),
            dynamic_symbols,
            self.options.shared,
            self.options.pie,
            self.options.soname,
            list(self.options.needed),
            dynamic_imports,
        )

    def _compute_build_id(
        self, memory: bytearray, base_relocations: Sequence[int]
    ) -> bytes:
        style = self.options.build_id
        if not style or style == "none":
            return b""
        # A reproducible build id is derived from the linked image so identical
        # inputs yield identical ids; ``uuid`` opts into a random id instead.
        digest_source = bytes(memory) + b"".join(
            offset.to_bytes(8, "little") for offset in base_relocations
        )
        if style in ("sha1", "default", "tree", ""):
            return hashlib.sha1(digest_source).digest()
        if style == "md5":
            return hashlib.md5(digest_source).digest()
        if style == "uuid":
            return os.urandom(16)
        if style.startswith("0x") or style.startswith("0X"):
            hex_digits = style[2:]
            if not hex_digits or len(hex_digits) % 2 or any(
                ch not in "0123456789abcdefABCDEF" for ch in hex_digits
            ):
                raise LinkerError("invalid --build-id hex string: %s" % style)
            return bytes.fromhex(hex_digits)
        raise LinkerError("unsupported --build-id style: %s" % style)


LinkInput = Union[
    ObjectInput,
    ArchiveInput,
    StackVMObject,
    StackVMArchive,
    Tuple[str, StackVMObject],
    Tuple[str, StackVMArchive],
]


def _coerce_inputs(
    inputs: Sequence[LinkInput],
) -> List[Union[ObjectInput, ArchiveInput]]:
    result = []
    for index, link_input in enumerate(inputs):
        if isinstance(link_input, (ObjectInput, ArchiveInput)):
            result.append(link_input)
        elif isinstance(link_input, StackVMObject):
            result.append(ObjectInput("<object %u>" % index, link_input))
        elif isinstance(link_input, StackVMArchive):
            result.append(ArchiveInput("<archive %u>" % index, link_input))
        elif (
            isinstance(link_input, tuple)
            and len(link_input) == 2
            and isinstance(link_input[0], str)
        ):
            name, value = link_input
            if isinstance(value, StackVMObject):
                result.append(ObjectInput(name, value))
            elif isinstance(value, StackVMArchive):
                result.append(ArchiveInput(name, value))
            else:
                raise TypeError("unrecognized linker input value: %r" % (value,))
        else:
            raise TypeError("unrecognized linker input: %r" % (link_input,))
    return result


def link(
    inputs: Sequence[LinkInput],
    options: Optional[LinkOptions] = None,
) -> LinkResult:
    return _ObjectLinker(LinkOptions() if options is None else options).process(
        _coerce_inputs(inputs)
    )


def link_objects(
    objects: Sequence[LinkInput],
    archives: Sequence[LinkInput] = (),
    *,
    allow_undefined: bool = False,
    code_base: int = DEFAULT_CODE_BASE,
    data_base: int = DEFAULT_DATA_BASE,
    data_alignment: int = DEFAULT_DATA_ALIGNMENT,
    runtime_aliases: bool = True,
    symbol_aliases: Optional[Mapping[str, str]] = None,
    linker_script: Optional[Union[LinkerScript, str]] = None,
    percpu_copies: int = 1,
    gc_sections: bool = False,
    entry_symbol: str = "_start",
    keep_symbols: Sequence[str] = (),
    build_id: Optional[str] = None,
    emit_relocs: bool = False,
    version_script: Optional[Union[VersionScript, str]] = None,
    shared: bool = False,
    pie: bool = False,
    soname: Optional[str] = None,
    needed: Sequence[str] = (),
) -> LinkResult:
    return link(
        list(objects) + list(archives),
        LinkOptions(
            allow_undefined,
            code_base,
            data_base,
            data_alignment,
            runtime_aliases,
            {} if symbol_aliases is None else symbol_aliases,
            LinkerScript() if linker_script is None else linker_script,
            percpu_copies,
            gc_sections=gc_sections,
            entry_symbol=entry_symbol,
            keep_symbols=tuple(keep_symbols),
            build_id=build_id,
            emit_relocs=emit_relocs,
            version_script=version_script,
            shared=shared,
            pie=pie,
            soname=soname,
            needed=tuple(needed),
        ),
    )


def load_link_input(path: str) -> Union[ObjectInput, ArchiveInput]:
    path = os.fspath(path)
    with open(path, "rb") as fl:
        magic = fl.read(8)
    if magic[:4] == ELF_MAGIC:
        return ObjectInput(path, load_elf_object(path))
    if magic == SBO_MAGIC:
        return ObjectInput(path, load_sbo(path))
    if magic == SBA_MAGIC:
        return ArchiveInput(path, load_sba(path))
    raise LinkerError("unrecognized linker input format: %s" % path)


def _should_write_elf_executable(path: str) -> bool:
    base = os.path.basename(os.fspath(path))
    return base == "vmlinux" or os.path.splitext(base)[1].lower() == ".elf"


def _should_write_pe_executable(path: str) -> bool:
    return os.path.splitext(os.path.basename(os.fspath(path)))[1].lower() in {
        ".efi",
        ".pe",
    }


def link_files(
    input_paths: Sequence[str],
    output_path: Optional[str] = None,
    map_path: Optional[str] = None,
    *,
    allow_undefined: bool = False,
    code_base: int = DEFAULT_CODE_BASE,
    data_base: int = DEFAULT_DATA_BASE,
    data_alignment: int = DEFAULT_DATA_ALIGNMENT,
    runtime_aliases: bool = True,
    symbol_aliases: Optional[Mapping[str, str]] = None,
    linker_script: Optional[Union[LinkerScript, str]] = None,
    percpu_copies: int = 1,
    whole_archive_flags: Optional[Sequence[bool]] = None,
    gc_sections: bool = False,
    entry_symbol: str = "_start",
    keep_symbols: Sequence[str] = (),
    build_id: Optional[str] = None,
    emit_relocs: bool = False,
    version_script: Optional[Union[VersionScript, str]] = None,
    shared: bool = False,
    pie: bool = False,
    soname: Optional[str] = None,
    needed: Sequence[str] = (),
    subsystem: Union[str, int, None] = None,
) -> LinkResult:
    if whole_archive_flags is not None and len(whole_archive_flags) != len(input_paths):
        raise ValueError("whole_archive_flags must align with input_paths")
    inputs: List[Union[ObjectInput, ArchiveInput]] = []
    for index, path in enumerate(input_paths):
        link_input = load_link_input(path)
        if (
            whole_archive_flags is not None
            and whole_archive_flags[index]
            and isinstance(link_input, ArchiveInput)
        ):
            link_input.whole_archive = True
        inputs.append(link_input)
    result = link_objects(
        inputs,
        allow_undefined=allow_undefined,
        code_base=code_base,
        data_base=data_base,
        data_alignment=data_alignment,
        runtime_aliases=runtime_aliases,
        symbol_aliases=symbol_aliases,
        linker_script=linker_script,
        percpu_copies=percpu_copies,
        gc_sections=gc_sections,
        entry_symbol=entry_symbol,
        keep_symbols=keep_symbols,
        build_id=build_id,
        emit_relocs=emit_relocs,
        version_script=version_script,
        shared=shared,
        pie=pie,
        soname=soname,
        needed=needed,
    )
    if output_path is not None:
        if not shared and not pie and _should_write_pe_executable(output_path):
            from .pe_file import write_pe_executable

            write_pe_executable(
                result.to_executable(),
                output_path,
                result.section_layouts,
                result.symbols,
                subsystem=subsystem,
            )
        elif shared or pie or _should_write_elf_executable(output_path):
            write_elf_executable(
                result.to_executable(),
                output_path,
                result.section_layouts,
                result.symbols,
                build_id=result.build_id,
                emitted_relocations=result.emitted_relocations,
                shared=result.is_shared,
                pie=result.is_pie,
                soname=result.soname,
                needed=result.needed,
                dynamic_symbols=result.dynamic_symbols,
                dynamic_imports=result.dynamic_imports,
            )
        else:
            write_sbc(result.to_executable(), output_path)
    if map_path is not None:
        write_map_file(result, map_path)
    return result


def format_map(result: LinkResult) -> str:
    lines = [
        "StackVM linker map",
        "CODE 0x%016X 0x%016X" % (0, result.code_segment_end),
        "DATA 0x%016X 0x%016X" % (result.data_segment_start, len(result.memory)),
        "",
        "Sections:",
    ]
    for layout in result.section_layouts:
        lines.append(
            "  0x%016X +0x%X file=0x%X %-10s"
            % (
                layout.address,
                layout.size,
                layout.file_size,
                layout.name,
            )
        )
    lines.extend(
        [
            "",
            "Object layout:",
        ]
    )
    for layout in result.object_layouts:
        lines.append(
            "  CODE 0x%016X +0x%X  DATA 0x%016X +0x%X  %s"
            % (
                layout.code_address,
                layout.code_size,
                layout.data_address,
                layout.data_size,
                layout.name,
            )
        )
    lines.extend(["", "Symbols:"])
    for symbol in sorted(
        result.symbols,
        key=lambda item: (item.address, item.name, item.object_name),
    ):
        suffix = "" if symbol.selected else " (overridden)"
        lines.append(
            "  0x%016X %-4s %-6s %-8s %-10s %s [%s]%s"
            % (
                symbol.address,
                symbol.segment.name,
                symbol.binding.name,
                symbol.typ.name,
                symbol.section_name,
                symbol.name,
                symbol.object_name,
                suffix,
            )
        )
    if result.unresolved_symbols:
        lines.extend(["", "Unresolved symbols:"])
        lines.extend("  %s" % name for name in result.unresolved_symbols)
    return "\n".join(lines) + "\n"


def write_map_file(result: LinkResult, target: Union[str, TextIO]) -> None:
    data = format_map(result)
    if hasattr(target, "write"):
        target.write(data)
        return
    with open(target, "w") as fl:
        fl.write(data)
