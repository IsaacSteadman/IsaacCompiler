from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set

from .BaseCmplObj import BaseCmplObj
from .NameMangling import NameManglingMode, normalize_name_mangling_mode
from .stackvm_binutils.object_file import (
    ObjectSection,
    ObjectRelocation,
    ObjectSegment,
    ObjectSymbol,
    RelocationType,
    SectionFlags,
    StackVMObject,
    SymbolBinding,
    SymbolFlags,
    SymbolType,
)
from .stackvm_binutils.debug_info import (
    DEBUG_SECTION_NAME,
    DEFAULT_PREVIOUS_BP_OFFSET,
    DEFAULT_RETURN_ADDRESS_OFFSET,
    DebugFunctionRecord,
    DebugLineRecord,
    StackVMDebugInfo,
    dumps_debug,
)

INIT_GLOBALS_LINK_NAME = "?Fz__init_globals"
INIT_ARRAY_SECTION = ".init_array"
FINI_ARRAY_SECTION = ".fini_array"
DEFAULT_LIFECYCLE_PRIORITY = 65535


class CompileObjectType(Enum):
    GLOBAL = 0  # initialization of a global
    FUNCTION = 1  # definition of a function


@dataclass
class TranslationUnitSymbol:
    link_name: str
    source_name: str
    typ: object
    binding: SymbolBinding
    segment: ObjectSegment
    symbol_type: SymbolType
    declared: bool = True
    defined: bool = False
    size: int = 0
    alignment: int = 1
    section_name: Optional[str] = None


@dataclass(frozen=True)
class LifecycleFunction:
    kind: str
    link_name: str
    priority: int
    sequence: int
    object_name: str


def _align_up(x: int, align: int) -> int:
    return (x + align - 1) & ~(align - 1)


class Compilation(BaseCmplObj):
    def __init__(
        self,
        keep_local_syms: bool,
        name_mangling_mode: NameManglingMode = NameManglingMode.NONE,
        default_alignment: Optional[int] = None,
    ):
        super(Compilation, self).__init__()
        self.keep_local_syms = keep_local_syms
        self.name_mangling_mode = normalize_name_mangling_mode(name_mangling_mode)
        self.default_alignment = default_alignment
        self.objects: Dict[str, CompileObject] = {}
        self.symbol_registry: Dict[str, TranslationUnitSymbol] = {}
        self._global_initializer_finalized = False
        self.lifecycle_functions: List[LifecycleFunction] = []
        self._registered_lifecycle_functions = set()
        self._standalone_startup_emitted = False
        self.code_segment_end = None
        self.data_segment_start = None
        self.source_path = None

    def register_symbol(
        self,
        link_name: str,
        source_name: str,
        typ: object,
        binding: SymbolBinding,
        segment: ObjectSegment,
        symbol_type: SymbolType,
        declared: bool = True,
        defined: bool = False,
        size: int = 0,
        alignment: int = 1,
        section_name: Optional[str] = None,
    ) -> TranslationUnitSymbol:
        binding = SymbolBinding(binding)
        segment = ObjectSegment(segment)
        symbol_type = SymbolType(symbol_type)
        cur = self.symbol_registry.get(link_name)
        if cur is None:
            cur = TranslationUnitSymbol(
                link_name,
                source_name,
                typ,
                binding,
                segment,
                symbol_type,
                declared,
                defined,
                size,
                alignment,
                section_name,
            )
            self.symbol_registry[link_name] = cur
            return cur
        if cur.binding != binding:
            if {cur.binding, binding} <= {
                SymbolBinding.GLOBAL,
                SymbolBinding.WEAK,
            }:
                cur.binding = SymbolBinding.WEAK
            else:
                raise TypeError("Conflicting binding for symbol '%s'" % link_name)
        if cur.segment != segment or cur.symbol_type != symbol_type:
            raise TypeError("Conflicting type for symbol '%s'" % link_name)
        cur.declared = cur.declared or declared
        cur.defined = cur.defined or defined
        cur.size = max(cur.size, size)
        cur.alignment = max(cur.alignment, alignment)
        if section_name is not None:
            if cur.section_name is not None and cur.section_name != section_name:
                raise TypeError("Conflicting section for symbol '%s'" % link_name)
            cur.section_name = section_name
        if cur.typ is None:
            cur.typ = typ
        return cur

    def spawn_compile_object(
        self, typ: CompileObjectType, name: str
    ) -> "CompileObject":
        rtn = CompileObject(typ, name)
        rtn.debug_source_file = self.source_path
        registry_symbol = self.symbol_registry.get(name)
        if registry_symbol is not None:
            rtn.section_name = registry_symbol.section_name
        self.objects[name] = rtn
        return rtn.set_parent(self)

    def ensure_compile_object(
        self, typ: CompileObjectType, name: str
    ) -> "CompileObject":
        cur = self.objects.get(name)
        if cur is None:
            return self.spawn_compile_object(typ, name)
        if cur.typ != typ:
            raise TypeError(
                "Compile object %r already exists with type %r (expected %r)"
                % (name, cur.typ, typ)
            )
        return cur

    def finalize_global_initializer(self) -> Optional["CompileObject"]:
        init_obj = self.objects.get(INIT_GLOBALS_LINK_NAME)
        if init_obj is None:
            return None
        if not self._global_initializer_finalized:
            from ..StackVM.PyStackVM import BC_RET

            init_obj.memory.append(BC_RET)
            self._global_initializer_finalized = True
        self.register_symbol(
            INIT_GLOBALS_LINK_NAME,
            "__init_globals",
            None,
            SymbolBinding.LOCAL,
            ObjectSegment.CODE,
            SymbolType.FUNCTION,
            True,
            True,
            len(init_obj.memory),
        )
        return init_obj

    @staticmethod
    def _lifecycle_priority(attribute) -> int:
        args = attribute.args
        if len(args) == 0:
            return DEFAULT_LIFECYCLE_PRIORITY
        if len(args) != 1:
            raise TypeError(
                "%s attribute accepts at most one priority" % attribute.name
            )
        try:
            priority = int(args[0], 0)
        except ValueError as exc:
            raise TypeError(
                "%s attribute priority must be an integer constant"
                % attribute.name
            ) from exc
        if priority < 0 or priority > DEFAULT_LIFECYCLE_PRIORITY:
            raise ValueError(
                "%s attribute priority must be between 0 and %u"
                % (attribute.name, DEFAULT_LIFECYCLE_PRIORITY)
            )
        return priority

    def register_lifecycle_function(
        self,
        link_name: str,
        typ: object,
        attributes,
    ) -> None:
        lifecycle_attrs = [
            attribute
            for attribute in attributes
            if attribute.name in {"constructor", "destructor"}
        ]
        if not lifecycle_attrs:
            return
        registry_symbol = self.symbol_registry.get(link_name)
        if registry_symbol is None or not registry_symbol.defined:
            return

        from ..parser.type.types import QualType, compare_no_cvr, void_t

        if not isinstance(typ, QualType) or typ.qual_id != QualType.QUAL_FN:
            raise TypeError("constructor and destructor attributes require a function")
        if typ.ext_inf:
            raise TypeError(
                "constructor and destructor functions cannot accept arguments"
            )
        if not compare_no_cvr(typ.tgt_type, void_t):
            raise TypeError("constructor and destructor functions must return void")

        by_kind = {}
        for attribute in lifecycle_attrs:
            priority = self._lifecycle_priority(attribute)
            previous = by_kind.get(attribute.name)
            if previous is not None and previous != priority:
                raise TypeError(
                    "conflicting %s priorities for '%s'"
                    % (attribute.name, link_name)
                )
            by_kind[attribute.name] = priority

        for kind, priority in by_kind.items():
            registration_key = kind, link_name
            if registration_key in self._registered_lifecycle_functions:
                continue
            self._registered_lifecycle_functions.add(registration_key)

            sequence = len(self.lifecycle_functions)
            object_name = "?__svm.%s_array.%08u" % (kind, sequence)
            section_base = (
                INIT_ARRAY_SECTION if kind == "constructor" else FINI_ARRAY_SECTION
            )
            section_name = (
                section_base
                if priority == DEFAULT_LIFECYCLE_PRIORITY
                else "%s.%05u" % (section_base, priority)
            )
            entry_obj = self.spawn_compile_object(CompileObjectType.GLOBAL, object_name)
            entry_obj.alignment = 8
            entry_obj.section_name = section_name
            entry_obj.memory.extend([0] * 8)
            entry_obj.get_link(link_name).lst_tgt.append(
                LinkRef(0, relocation_type=RelocationType.ABS8)
            )
            self.register_symbol(
                object_name,
                object_name,
                None,
                SymbolBinding.LOCAL,
                ObjectSegment.DATA,
                SymbolType.OBJECT,
                True,
                True,
                8,
                8,
                section_name,
            )
            self.lifecycle_functions.append(
                LifecycleFunction(kind, link_name, priority, sequence, object_name)
            )

    def _emit_lifecycle_calls(self, kind: str, reverse: bool = False) -> None:
        entries = sorted(
            (
                entry
                for entry in self.lifecycle_functions
                if entry.kind == kind
            ),
            key=lambda entry: (entry.priority, entry.sequence),
            reverse=reverse,
        )
        if not entries:
            return

        from .branch_emit import emit_rel_call

        for entry in entries:
            emit_rel_call(self.memory, self.get_link(entry.link_name))

    def emit_standalone_startup(self, main_link_name: str) -> None:
        if self._standalone_startup_emitted:
            raise ValueError("standalone startup code has already been emitted")

        from ..StackVM.PyStackVM import BC_HLT
        from .branch_emit import emit_rel_call
        from .stackvm_binutils.emit_load_i_const import emit_load_i_const

        init_obj = self.finalize_global_initializer()
        if init_obj is not None:
            emit_rel_call(self.memory, self.get_link(INIT_GLOBALS_LINK_NAME))
        self._emit_lifecycle_calls("constructor")
        emit_load_i_const(self.memory, 1, True, 2)
        emit_rel_call(self.memory, self.get_link(main_link_name))
        self._emit_lifecycle_calls("destructor", reverse=True)
        self.memory.append(BC_HLT)
        self._standalone_startup_emitted = True

    def merge_all(
        self,
        link_opts: "LinkerOptions",
        extern: Optional[Dict[str, "CompileObject"]] = None,
        excl: Optional[Set[str]] = None,
    ):
        # memory Layout
        #   FUNCTION
        #   GLOBALS
        #   STRINGS
        funcs = []
        globs = []
        for k in sorted(self.objects):
            cur = self.objects[k]
            if cur.typ == CompileObjectType.FUNCTION:
                funcs.append(cur)
            elif cur.typ == CompileObjectType.GLOBAL:
                globs.append(cur)
            else:
                raise TypeError(
                    "Unexpected Compile Object name = %r Type = %u"
                    % (cur.name, cur.typ)
                )
        if extern is not None:
            for k in sorted(extern):
                cur = extern[k]
                if cur.typ == CompileObjectType.FUNCTION:
                    funcs.append(cur)
                elif cur.typ == CompileObjectType.GLOBAL:
                    globs.append(cur)
                else:
                    raise TypeError(
                        "Unexpected Compile Object name = %r Type = %u"
                        % (cur.name, cur.typ)
                    )
        for lst_objects in [funcs, globs]:
            for cur in lst_objects:
                assert isinstance(cur, CompileObject)
                if excl is not None and cur.name in excl:
                    continue
                obj_lnk = self.get_link(cur.name)
                if obj_lnk.src is not None:
                    raise NameError(
                        "Redefinition of name = '%s' is not allowed" % cur.name
                    )
                if cur.typ == CompileObjectType.GLOBAL and cur.alignment > 1:
                    mem_off = _align_up(len(self.memory), cur.alignment)
                    if mem_off > len(self.memory):
                        self.memory.extend([0] * (mem_off - len(self.memory)))
                mem_off = len(self.memory)
                self.memory.extend(cur.memory)
                self.memory_accesses.extend(
                    access.shifted(mem_off) for access in cur.memory_accesses
                )
                obj_lnk.src = mem_off
                for k1 in cur.string_pool:
                    cur1 = cur.string_pool[k1]
                    lnk = self.get_string_link(k1)
                    lnk.merge_from(cur1, mem_off)
                for k1 in cur.linkages:
                    cur1 = cur.linkages[k1]
                    lnk = self.get_link(k1)
                    lnk.merge_from(cur1, mem_off)
            if lst_objects is funcs:
                self.code_segment_end = len(self.memory)
                dsa = link_opts.data_seg_align
                if dsa > 1:
                    length = len(self.memory)
                    self.memory.extend([0] * (dsa - length % dsa))
                self.data_segment_start = len(self.memory)
        for k in self.string_pool:
            assert isinstance(k, bytes)
            cur = self.string_pool[k]
            assert cur.src is None
            if cur.alignment > 1:
                mem_off = _align_up(len(self.memory), cur.alignment)
                if mem_off > len(self.memory):
                    self.memory.extend([0] * (mem_off - len(self.memory)))
            mem_off = len(self.memory)
            self.memory.extend(k)
            cur.src = mem_off

    @staticmethod
    def _object_symbol_defaults(
        obj: "CompileObject",
    ):
        if obj.typ == CompileObjectType.FUNCTION:
            return ObjectSegment.CODE, SymbolType.FUNCTION
        if obj.typ == CompileObjectType.GLOBAL:
            return ObjectSegment.DATA, SymbolType.OBJECT
        raise TypeError("Unexpected compile object type: %r" % obj.typ)

    def _undefined_symbol_defaults(
        self,
        name: str,
        extern: Optional[Dict[str, "CompileObject"]],
    ):
        registry_symbol = self.symbol_registry.get(name)
        if registry_symbol is not None:
            return (
                registry_symbol.binding,
                registry_symbol.segment,
                registry_symbol.symbol_type,
            )
        extern_obj = None if extern is None else extern.get(name)
        if extern_obj is not None:
            segment, symbol_type = self._object_symbol_defaults(extern_obj)
            return SymbolBinding.GLOBAL, segment, symbol_type
        return SymbolBinding.GLOBAL, ObjectSegment.CODE, SymbolType.FUNCTION

    @staticmethod
    def _write_relocation_addend(memory: bytearray, offset: int, addend: int) -> None:
        memory[offset : offset + 8] = (addend & ((1 << 64) - 1)).to_bytes(
            8, "little"
        )

    def to_stackvm_object(
        self,
        extern: Optional[Dict[str, "CompileObject"]] = None,
        default_alignment: Optional[int] = None,
    ) -> StackVMObject:
        if self.memory:
            raise ValueError(
                "Cannot emit an .sbo after standalone startup code or merged output "
                "has been generated"
            )
        self.finalize_global_initializer()
        if default_alignment is None:
            default_alignment = self.default_alignment

        funcs = []
        globs = []
        for name in sorted(self.objects):
            obj = self.objects[name]
            if obj.typ == CompileObjectType.FUNCTION:
                funcs.append(obj)
            elif obj.typ == CompileObjectType.GLOBAL:
                globs.append(obj)
            else:
                raise TypeError("Unexpected compile object type: %r" % obj.typ)

        def matches_section(name: str, base: str) -> bool:
            return name == base or name.startswith(base + ".")

        def is_read_only_type(typ: object) -> bool:
            from ..parser.type.types import QualType

            while isinstance(typ, QualType):
                if typ.qual_id == QualType.QUAL_CONST:
                    return True
                if typ.qual_id == QualType.QUAL_PTR:
                    return False
                if typ.qual_id == QualType.QUAL_ARR:
                    typ = typ.tgt_type
                    continue
                if typ.qual_id in {
                    QualType.QUAL_DEF,
                    QualType.QUAL_REG,
                    QualType.QUAL_VOLATILE,
                    QualType.QUAL_ATOMIC,
                }:
                    typ = typ.tgt_type
                    continue
                return False
            return False

        def has_source_relocations(obj: "CompileObject") -> bool:
            return any(linkage.lst_tgt for linkage in obj.linkages.values()) or any(
                linkage.lst_tgt for linkage in obj.string_pool.values()
            )

        def default_section_name(obj: "CompileObject") -> str:
            if obj.section_name is not None:
                return obj.section_name
            if obj.typ == CompileObjectType.FUNCTION:
                return ".text"
            registry_symbol = self.symbol_registry.get(obj.name)
            if registry_symbol is not None and is_read_only_type(registry_symbol.typ):
                return ".rodata"
            if not any(obj.memory) and not has_source_relocations(obj):
                return ".bss"
            return ".data"

        section_builders = {}

        def get_section_builder(
            section_name: str,
            segment: ObjectSegment,
            alignment: int,
            flags: SectionFlags,
        ):
            builder = section_builders.get(section_name)
            if builder is None:
                builder = {
                    "name": section_name,
                    "segment": segment,
                    "alignment": alignment,
                    "flags": flags,
                    "memory": bytearray(),
                    "size": 0,
                }
                section_builders[section_name] = builder
            elif builder["segment"] != segment or builder["flags"] != flags:
                raise ValueError("incompatible uses of section '%s'" % section_name)
            else:
                builder["alignment"] = max(builder["alignment"], alignment)
            return builder

        def add_compile_object(obj: "CompileObject") -> None:
            section_name = default_section_name(obj)
            segment, _symbol_type = self._object_symbol_defaults(obj)
            alignment = max(1, obj.alignment)
            flags = SectionFlags.NONE
            if segment == ObjectSegment.CODE:
                flags |= SectionFlags.EXECUTABLE
                if any(
                    matches_section(section_name, base)
                    for base in (".data", ".rodata", ".bss")
                ):
                    raise ValueError(
                        "function '%s' cannot be placed in data section '%s'"
                        % (obj.name, section_name)
                    )
            else:
                if matches_section(section_name, ".text") or matches_section(
                    section_name, ".init.text"
                ):
                    raise ValueError(
                        "object '%s' cannot be placed in code section '%s'"
                        % (obj.name, section_name)
                    )
                if matches_section(section_name, ".rodata"):
                    flags |= SectionFlags.READ_ONLY
                if matches_section(section_name, ".bss"):
                    flags |= SectionFlags.NOBITS
                    if any(obj.memory) or has_source_relocations(obj):
                        raise ValueError(
                            "initialized object '%s' cannot be placed in NOBITS section '%s'"
                            % (obj.name, section_name)
                        )
            builder = get_section_builder(section_name, segment, alignment, flags)
            offset = _align_up(builder["size"], alignment)
            if not flags & SectionFlags.NOBITS:
                memory = builder["memory"]
                if offset > len(memory):
                    memory.extend([0] * (offset - len(memory)))
                memory.extend(obj.memory)
            builder["size"] = offset + len(obj.memory)
            object_positions[obj.name] = (
                section_name,
                offset,
                len(obj.memory),
            )

        object_positions = {}
        for obj in funcs + globs:
            add_compile_object(obj)

        string_alignments = {}
        for obj in funcs + globs:
            for value, linkage in obj.string_pool.items():
                if linkage.lst_tgt:
                    string_alignments[value] = max(
                        string_alignments.get(value, 1),
                        linkage.alignment,
                    )
        string_values = sorted(string_alignments)
        string_positions = {}
        rodata_builder = None
        for index, value in enumerate(string_values):
            alignment = string_alignments[value]
            if rodata_builder is None:
                rodata_builder = get_section_builder(
                    ".rodata",
                    ObjectSegment.DATA,
                    alignment,
                    SectionFlags.READ_ONLY,
                )
            else:
                rodata_builder["alignment"] = max(
                    rodata_builder["alignment"], alignment
                )
            offset = _align_up(rodata_builder["size"], alignment)
            memory = rodata_builder["memory"]
            if offset > len(memory):
                memory.extend([0] * (offset - len(memory)))
            memory.extend(value)
            rodata_builder["size"] = offset + len(value)
            string_positions[value] = (".L.str.%u" % index, offset, len(value))

        if self.keep_local_syms:
            line_records = []
            function_records = []
            for obj in funcs:
                section_name, base_offset, size = object_positions[obj.name]
                for offset, source_file, line, column in obj.debug_line_records:
                    if offset < 0 or offset > len(obj.memory):
                        continue
                    line_records.append(
                        DebugLineRecord(
                            base_offset + offset,
                            source_file,
                            line,
                            column,
                            section_name,
                        )
                    )
                function_records.append(
                    DebugFunctionRecord(
                        obj.name,
                        base_offset,
                        size,
                        getattr(obj, "debug_frame_size", 0),
                        getattr(
                            obj,
                            "debug_return_address_offset",
                            DEFAULT_RETURN_ADDRESS_OFFSET,
                        ),
                        getattr(
                            obj,
                            "debug_previous_bp_offset",
                            DEFAULT_PREVIOUS_BP_OFFSET,
                        ),
                        section_name,
                    )
                )
            if line_records or function_records:
                debug_bytes = dumps_debug(
                    StackVMDebugInfo(line_records, function_records)
                )
                debug_builder = get_section_builder(
                    DEBUG_SECTION_NAME,
                    ObjectSegment.DATA,
                    1,
                    SectionFlags.READ_ONLY,
                )
                debug_builder["memory"].extend(debug_bytes)
                debug_builder["size"] = len(debug_bytes)

        section_priority = {
            ".text": 0,
            ".init.text": 1,
            INIT_ARRAY_SECTION: 2,
            FINI_ARRAY_SECTION: 3,
            ".data": 4,
            ".rodata": 5,
            ".bss": 6,
            DEBUG_SECTION_NAME: 7,
        }

        def section_sort_key(builder):
            name = builder["name"]
            family_priority = len(section_priority)
            for base, priority in section_priority.items():
                if matches_section(name, base):
                    family_priority = priority
                    break
            return (int(builder["segment"]), family_priority, name)

        ordered_builders = sorted(section_builders.values(), key=section_sort_key)
        section_indices = {
            builder["name"]: index for index, builder in enumerate(ordered_builders)
        }

        symbols = []
        symbol_indices = {}
        for name in sorted(object_positions):
            obj = self.objects[name]
            section_name, value, size = object_positions[name]
            section_index = section_indices[section_name]
            segment = ordered_builders[section_index]["segment"]
            registry_symbol = self.symbol_registry.get(name)
            if registry_symbol is None:
                binding = (
                    SymbolBinding.LOCAL
                    if name == INIT_GLOBALS_LINK_NAME
                    or name.endswith("$init_guard")
                    else SymbolBinding.GLOBAL
                )
                _, symbol_type = self._object_symbol_defaults(obj)
            else:
                binding = registry_symbol.binding
                symbol_type = registry_symbol.symbol_type
            symbol_indices[name] = len(symbols)
            symbols.append(
                ObjectSymbol(
                    name,
                    value,
                    size,
                    segment,
                    binding,
                    symbol_type,
                    section_index=section_index,
                )
            )

        string_symbol_indices = {}
        for value in string_values:
            name, offset, size = string_positions[value]
            string_symbol_indices[value] = len(symbols)
            symbols.append(
                ObjectSymbol(
                    name,
                    offset,
                    size,
                    ObjectSegment.DATA,
                    SymbolBinding.LOCAL,
                    SymbolType.OBJECT,
                    section_index=section_indices[".rodata"],
                )
            )

        referenced_names = {
            name
            for obj in funcs + globs
            for name, linkage in obj.linkages.items()
            if linkage.lst_tgt
        }
        for name in sorted(referenced_names - set(object_positions)):
            binding, segment, symbol_type = self._undefined_symbol_defaults(
                name, extern
            )
            symbol_indices[name] = len(symbols)
            symbols.append(
                ObjectSymbol(
                    name,
                    0,
                    0,
                    segment,
                    binding,
                    symbol_type,
                    SymbolFlags.UNDEFINED,
                )
            )

        relocations = []
        for obj in funcs + globs:
            section_name, base_offset, _size = object_positions[obj.name]
            section_index = section_indices[section_name]
            builder = ordered_builders[section_index]
            segment = builder["segment"]
            section_memory = builder["memory"]
            for name in sorted(obj.linkages):
                linkage = obj.linkages[name]
                if not linkage.lst_tgt:
                    continue
                symbol_index = symbol_indices[name]
                for ref in linkage.lst_tgt:
                    offset = base_offset + ref.pos
                    if ref.pos < 0 or ref.pos + 8 > len(obj.memory):
                        raise ValueError(
                            "Relocation patch for '%s' is outside object '%s'"
                            % (name, obj.name)
                        )
                    self._write_relocation_addend(section_memory, offset, ref.addend)
                    relocations.append(
                        ObjectRelocation(
                            offset,
                            symbol_index,
                            segment,
                            RelocationType(ref.relocation_type),
                            section_index,
                        )
                    )
            for value in sorted(obj.string_pool):
                linkage = obj.string_pool[value]
                if not linkage.lst_tgt:
                    continue
                symbol_index = string_symbol_indices[value]
                for ref in linkage.lst_tgt:
                    offset = base_offset + ref.pos
                    if ref.pos < 0 or ref.pos + 8 > len(obj.memory):
                        raise ValueError(
                            "String relocation patch is outside object '%s'"
                            % obj.name
                        )
                    self._write_relocation_addend(section_memory, offset, ref.addend)
                    relocations.append(
                        ObjectRelocation(
                            offset,
                            symbol_index,
                            segment,
                            RelocationType(ref.relocation_type),
                            section_index,
                        )
                    )

        code = bytearray()
        data = bytearray()
        data_alignment = 1
        section_offsets = {}
        for segment, segment_memory in (
            (ObjectSegment.CODE, code),
            (ObjectSegment.DATA, data),
        ):
            for index, builder in enumerate(ordered_builders):
                if (
                    builder["segment"] != segment
                    or builder["flags"] & SectionFlags.NOBITS
                ):
                    continue
                if segment == ObjectSegment.DATA:
                    data_alignment = max(data_alignment, builder["alignment"])
                offset = _align_up(len(segment_memory), builder["alignment"])
                if offset > len(segment_memory):
                    segment_memory.extend([0] * (offset - len(segment_memory)))
                section_offsets[index] = offset
                segment_memory.extend(builder["memory"])
            logical_end = len(segment_memory)
            for index, builder in enumerate(ordered_builders):
                if (
                    builder["segment"] != segment
                    or not builder["flags"] & SectionFlags.NOBITS
                ):
                    continue
                if segment == ObjectSegment.DATA:
                    data_alignment = max(data_alignment, builder["alignment"])
                logical_end = _align_up(logical_end, builder["alignment"])
                section_offsets[index] = logical_end
                logical_end += builder["size"]

        sections = []
        for index, builder in enumerate(ordered_builders):
            sections.append(
                ObjectSection(
                    builder["name"],
                    section_offsets[index],
                    builder["size"],
                    builder["alignment"],
                    builder["segment"],
                    builder["flags"],
                )
            )
        for symbol in symbols:
            if symbol.section_index is not None:
                symbol.value += section_offsets[symbol.section_index]
        for relocation in relocations:
            relocation.offset += section_offsets[relocation.section_index]
        relocations.sort(
            key=lambda rel: (
                int(rel.segment),
                rel.offset,
                rel.symbol_index,
            )
        )
        return StackVMObject(
            bytes(code),
            bytes(data),
            symbols,
            relocations,
            0 if default_alignment is None else default_alignment,
            data_alignment,
            sections,
        )

    def link_all(self):
        rtn = True
        for k in self.linkages:
            lnk = self.linkages[k]
            assert isinstance(lnk, Linkage)
            if lnk.src is None:
                fmt = (
                    "Unresolved "
                    + ("External " if lnk.is_extern else "")
                    + "Symbol: "
                    + k
                )
                if len(lnk.lst_tgt):
                    rtn = False
                    print("ERROR: " + fmt)
                else:
                    print("WARN_: " + fmt)
            else:
                lnk.fill_all(self.memory)
        for k in self.string_pool:
            lnk = self.string_pool[k]
            assert isinstance(lnk, Linkage)
            if lnk.src is None:
                fmt = (
                    "Unresolved "
                    + ("External " if lnk.is_extern else "")
                    + "Symbol: <bytes %r>" % k
                )
                if len(lnk.lst_tgt):
                    rtn = False
                    print("ERROR: " + fmt)
                else:
                    print("WARN_: " + fmt)
            else:
                lnk.fill_all(self.memory)
        return rtn


from .CompileObject import CompileObject
from .LinkRef import LinkRef
from .Linkage import Linkage
from .LinkerOptions import LinkerOptions
