from dataclasses import dataclass, field
import os
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, TextIO, Tuple, Union

from .archive_file import (
    SBA_MAGIC,
    StackVMArchive,
    load_sba,
)
from .executable_file import StackVMExecutable, dumps_sbc, write_sbc
from .lib_util_asm_impl.names import ISAAC_RUNTIME_LINK_NAMES
from .object_file import (
    SBO_MAGIC,
    ObjectSegment,
    ObjectSymbol,
    RelocationType,
    StackVMObject,
    SymbolBinding,
    SymbolType,
    load_sbo,
    validate_object,
)


DEFAULT_CODE_BASE = 0
DEFAULT_DATA_BASE = 0x1000
DEFAULT_DATA_ALIGNMENT = 0x1000


class LinkerError(Exception):
    pass


class DuplicateSymbolError(LinkerError):
    pass


class UndefinedSymbolError(LinkerError):
    def __init__(self, symbols: Iterable[str]):
        self.symbols = tuple(sorted(set(symbols)))
        super().__init__("unresolved symbols: " + ", ".join(self.symbols))


@dataclass
class LinkOptions:
    allow_undefined: bool = False
    code_base: int = DEFAULT_CODE_BASE
    data_base: int = DEFAULT_DATA_BASE
    data_alignment: int = DEFAULT_DATA_ALIGNMENT
    runtime_aliases: bool = True
    symbol_aliases: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code_base < 0 or self.data_base < 0:
            raise ValueError("segment base addresses must be non-negative")
        if self.data_alignment <= 0 or (
            self.data_alignment & (self.data_alignment - 1)
        ):
            raise ValueError("data alignment must be a power of two")


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


@dataclass
class ObjectLayout:
    name: str
    code_address: int
    code_size: int
    data_address: int
    data_size: int


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

    @property
    def symbol_addresses(self) -> Dict[str, int]:
        return self.global_symbols

    def to_executable(self) -> StackVMExecutable:
        return StackVMExecutable(
            self.memory,
            self.code_segment_end,
            self.data_segment_start,
        )

    def to_sbc(self) -> bytes:
        return dumps_sbc(self.to_executable())


@dataclass
class _Definition:
    object_index: int
    symbol_index: int


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


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _read_addend(memory: bytearray, offset: int) -> int:
    return int.from_bytes(memory[offset : offset + 8], "little", signed=True)


def _write_value(memory: bytearray, offset: int, value: int) -> None:
    memory[offset : offset + 8] = (value & ((1 << 64) - 1)).to_bytes(8, "little")


class _ObjectLinker:
    def __init__(self, options: LinkOptions):
        self.options = options
        self.aliases = _AliasResolver(
            options.runtime_aliases,
            options.symbol_aliases,
        )
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
                key = self.aliases.canonical(symbol.name)
                if key not in self.selected:
                    unresolved.add(key)
        return unresolved

    def _unresolved_names(self) -> Set[str]:
        unresolved = set()
        for obj_input in self.included:
            for relocation in obj_input.obj.relocations:
                symbol = obj_input.obj.symbols[relocation.symbol_index]
                if symbol.binding == SymbolBinding.LOCAL:
                    if symbol.is_undefined:
                        unresolved.add(symbol.name)
                    continue
                if self.aliases.canonical(symbol.name) not in self.selected:
                    unresolved.add(symbol.name)
        return unresolved

    def include_archive(self, archive_input: ArchiveInput) -> None:
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
                    if not symbol.is_undefined
                    and symbol.binding != SymbolBinding.LOCAL
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

        unresolved_names = self._unresolved_names()
        if unresolved_names and not self.options.allow_undefined:
            raise UndefinedSymbolError(unresolved_names)
        return self._layout_and_relocate(sorted(unresolved_names))

    def _layout_and_relocate(self, unresolved_names: List[str]) -> LinkResult:
        memory = bytearray(self.options.code_base)
        code_addresses = []
        for obj_input in self.included:
            code_addresses.append(len(memory))
            memory.extend(obj_input.obj.code)
        code_segment_end = len(memory)

        data_segment_start = _align_up(
            max(code_segment_end, self.options.data_base),
            self.options.data_alignment,
        )
        memory.extend([0] * (data_segment_start - len(memory)))
        data_addresses = []
        for obj_input in self.included:
            data_address = _align_up(len(memory), obj_input.obj.data_alignment)
            memory.extend([0] * (data_address - len(memory)))
            data_addresses.append(data_address)
            memory.extend(obj_input.obj.data)

        layouts = [
            ObjectLayout(
                obj_input.display_name,
                code_addresses[index],
                len(obj_input.obj.code),
                data_addresses[index],
                len(obj_input.obj.data),
            )
            for index, obj_input in enumerate(self.included)
        ]

        def symbol_address(object_index: int, symbol: ObjectSymbol) -> int:
            base = (
                code_addresses[object_index]
                if symbol.segment == ObjectSegment.CODE
                else data_addresses[object_index]
            )
            return base + symbol.value

        selected_addresses = {
            key: symbol_address(
                definition.object_index,
                self._symbol_for_definition(definition),
            )
            for key, definition in self.selected.items()
        }

        for object_index, obj_input in enumerate(self.included):
            for relocation in obj_input.obj.relocations:
                symbol = obj_input.obj.symbols[relocation.symbol_index]
                patch_base = (
                    code_addresses[object_index]
                    if relocation.segment == ObjectSegment.CODE
                    else data_addresses[object_index]
                )
                patch_address = patch_base + relocation.offset
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
                if target_address is None:
                    continue
                addend = _read_addend(memory, patch_address)
                if relocation.typ == RelocationType.ABS8:
                    value = target_address + addend
                elif relocation.typ == RelocationType.PCREL8:
                    value = target_address + addend - (patch_address + 8)
                else:
                    raise LinkerError(
                        "unsupported relocation type %r in %s"
                        % (relocation.typ, obj_input.display_name)
                    )
                _write_value(memory, patch_address, value)

        linked_symbols = []
        for object_index, obj_input in enumerate(self.included):
            for symbol_index, symbol in enumerate(obj_input.obj.symbols):
                if symbol.is_undefined:
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
                    )
                )

        global_symbols = {}
        for key, address in selected_addresses.items():
            for name in self.aliases.names_for(key):
                global_symbols[name] = address
            definition = self.selected[key]
            global_symbols[self._symbol_for_definition(definition).name] = address

        return LinkResult(
            bytes(memory),
            code_segment_end,
            data_segment_start,
            global_symbols,
            linked_symbols,
            unresolved_names,
            [obj_input.display_name for obj_input in self.included],
            layouts,
        )


LinkInput = Union[
    ObjectInput,
    ArchiveInput,
    StackVMObject,
    StackVMArchive,
    Tuple[str, StackVMObject],
    Tuple[str, StackVMArchive],
]


def _coerce_inputs(inputs: Sequence[LinkInput]) -> List[Union[ObjectInput, ArchiveInput]]:
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
        ),
    )


def load_link_input(path: str) -> Union[ObjectInput, ArchiveInput]:
    path = os.fspath(path)
    with open(path, "rb") as fl:
        magic = fl.read(8)
    if magic == SBO_MAGIC:
        return ObjectInput(path, load_sbo(path))
    if magic == SBA_MAGIC:
        return ArchiveInput(path, load_sba(path))
    raise LinkerError("unrecognized linker input format: %s" % path)


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
) -> LinkResult:
    result = link_objects(
        [load_link_input(path) for path in input_paths],
        allow_undefined=allow_undefined,
        code_base=code_base,
        data_base=data_base,
        data_alignment=data_alignment,
        runtime_aliases=runtime_aliases,
        symbol_aliases=symbol_aliases,
    )
    if output_path is not None:
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
        "Object layout:",
    ]
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
            "  0x%016X %-4s %-6s %-8s %s [%s]%s"
            % (
                symbol.address,
                symbol.segment.name,
                symbol.binding.name,
                symbol.typ.name,
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
