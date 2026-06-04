from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Set

from .BaseCmplObj import BaseCmplObj
from .NameMangling import NameManglingMode, normalize_name_mangling_mode
from .stackvm_binutils.object_file import (
    ObjectRelocation,
    ObjectSegment,
    ObjectSymbol,
    RelocationType,
    StackVMObject,
    SymbolBinding,
    SymbolFlags,
    SymbolType,
)

INIT_GLOBALS_LINK_NAME = "?Fz__init_globals"


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
        self.code_segment_end = None
        self.data_segment_start = None

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
            )
            self.symbol_registry[link_name] = cur
            return cur
        if cur.binding != binding:
            raise TypeError("Conflicting binding for symbol '%s'" % link_name)
        if cur.segment != segment or cur.symbol_type != symbol_type:
            raise TypeError("Conflicting type for symbol '%s'" % link_name)
        cur.declared = cur.declared or declared
        cur.defined = cur.defined or defined
        cur.size = max(cur.size, size)
        cur.alignment = max(cur.alignment, alignment)
        if cur.typ is None:
            cur.typ = typ
        return cur

    def spawn_compile_object(
        self, typ: CompileObjectType, name: str
    ) -> "CompileObject":
        rtn = CompileObject(typ, name)
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

        code = bytearray()
        data = bytearray()
        object_positions = {}
        for obj in funcs:
            offset = len(code)
            code.extend(obj.memory)
            object_positions[obj.name] = (
                ObjectSegment.CODE,
                offset,
                len(obj.memory),
            )
        data_alignment = 1
        for obj in globs:
            alignment = max(1, obj.alignment)
            data_alignment = max(data_alignment, alignment)
            offset = _align_up(len(data), alignment)
            if offset > len(data):
                data.extend([0] * (offset - len(data)))
            data.extend(obj.memory)
            object_positions[obj.name] = (
                ObjectSegment.DATA,
                offset,
                len(obj.memory),
            )

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
        for index, value in enumerate(string_values):
            alignment = string_alignments[value]
            data_alignment = max(data_alignment, alignment)
            offset = _align_up(len(data), alignment)
            if offset > len(data):
                data.extend([0] * (offset - len(data)))
            data.extend(value)
            string_positions[value] = (".L.str.%u" % index, offset, len(value))

        symbols = []
        symbol_indices = {}
        for name in sorted(object_positions):
            obj = self.objects[name]
            segment, value, size = object_positions[name]
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
            segment, base_offset, _size = object_positions[obj.name]
            segment_memory = code if segment == ObjectSegment.CODE else data
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
                    self._write_relocation_addend(segment_memory, offset, ref.addend)
                    relocations.append(
                        ObjectRelocation(
                            offset,
                            symbol_index,
                            segment,
                            RelocationType(ref.relocation_type),
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
                    self._write_relocation_addend(segment_memory, offset, ref.addend)
                    relocations.append(
                        ObjectRelocation(
                            offset,
                            symbol_index,
                            segment,
                            RelocationType(ref.relocation_type),
                        )
                    )

        relocations.sort(key=lambda rel: (int(rel.segment), rel.offset, rel.symbol_index))
        return StackVMObject(
            bytes(code),
            bytes(data),
            symbols,
            relocations,
            0 if default_alignment is None else default_alignment,
            data_alignment,
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
from .Linkage import Linkage
from .LinkerOptions import LinkerOptions
