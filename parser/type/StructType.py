from typing import Dict, List, Optional, Tuple, Union
from .CompileContext import CompileContext
from .BaseType import BaseType, TypeClass


class StructType(CompileContext, BaseType):
    def to_user_str(self) -> str:
        return "struct " + self.name

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.STRUCT
    mangle_captures = {"B": None}

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["StructType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return StructType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl: bool = False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "B%u%s" % (len(name), name)

    def __init__(
        self,
        parent: Optional["CompileContext"],
        name: Optional[str] = None,
        incomplete: bool = True,
        definition: Dict[str, int] = None,
        var_order: List["ContextVariable"] = None,
        defined: bool = False,
        the_base_type: Optional["BaseType"] = None,
    ):
        super(StructType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.var_order = [] if var_order is None else var_order
        self.defined = defined
        self.the_base_type = the_base_type
        self.align_override: Optional[int] = None
        self.attributes: List[Attribute] = []
        self.layout_entries: List[StructLayoutEntry] = []
        # Bit-field layout state
        self.bit_field_info: Dict[str, BitFieldInfo] = {}
        self._precomp_byte_offsets: Dict[str, int] = {}
        self._direct_member_offsets: Dict["ContextVariable", int] = {}
        self._bf_struct_total_sz: Optional[int] = None
        self.is_packed: bool = False
        self._layout_cache: Optional[AggregateLayout] = None

    def offset_of(self, attr: str) -> int:
        resolved = self.resolve_member(attr)
        if resolved is None:
            raise KeyError(attr)
        return resolved.byte_offset

    def resolve_member(self, attr: str) -> Optional["AggregateMemberResolution"]:
        self._ensure_layout()
        var_index = self.definition.get(attr, -1)
        if var_index != -1:
            member = self.var_order[var_index]
            bit_field_info = self.bit_field_info.get(attr, None)
            if bit_field_info is not None:
                return AggregateMemberResolution(
                    member, bit_field_info.byte_offset, bit_field_info
                )
            return AggregateMemberResolution(
                member, self._precomp_byte_offsets[attr], None
            )
        for entry in self.layout_entries:
            member = entry.member
            if member is None or member.name is not None:
                continue
            anon_type = get_base_prim_type(member.typ)
            if isinstance(anon_type, (StructType, UnionType)):
                resolved = anon_type.resolve_member(attr)
                if resolved is not None:
                    return resolved.shifted(self._direct_member_offsets.get(member, 0))
        return None

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.var_order,
                self.defined,
                self.the_base_type,
            ),
            pretty_repr_ctx,
        )

    def merge_to(self, other):
        assert isinstance(other, StructType)
        super(StructType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.var_order = self.var_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type
        if self.align_override is not None:
            cur = 0 if other.align_override is None else other.align_override
            other.align_override = max(cur, self.align_override)
        other.layout_entries = self.layout_entries
        other.bit_field_info = self.bit_field_info
        other._precomp_byte_offsets = self._precomp_byte_offsets
        other._direct_member_offsets = self._direct_member_offsets
        other._bf_struct_total_sz = self._bf_struct_total_sz
        other.is_packed = other.is_packed or self.is_packed
        other.attributes.extend(self.attributes)
        other._layout_cache = self._layout_cache

    def _invalidate_layout(self) -> None:
        self._layout_cache = None
        self.bit_field_info = {}
        self._precomp_byte_offsets = {}
        self._direct_member_offsets = {}
        self._bf_struct_total_sz = None

    def _validate_flexible_array_members(self) -> None:
        seen_flexible_member = False
        for idx, entry in enumerate(self.layout_entries):
            if seen_flexible_member:
                raise ValueError(
                    "Flexible array member must be the last member of the struct"
                )
            member = entry.member
            if member is not None and is_flexible_array_type(member.typ):
                seen_flexible_member = True
                if idx != len(self.layout_entries) - 1:
                    raise ValueError(
                        "Flexible array member must be the last member of the struct"
                    )

    def _ensure_layout(self) -> "AggregateLayout":
        if self._layout_cache is not None:
            return self._layout_cache
        self._validate_flexible_array_members()
        if not self.layout_entries and self.var_order:
            self.layout_entries = [
                StructLayoutEntry(member=var) for var in self.var_order
            ]
        offsets: Dict[str, int] = {}
        bit_field_info: Dict[str, BitFieldInfo] = {}
        direct_member_offsets: Dict["ContextVariable", int] = {}
        off = 0
        max_align = 1
        if self.the_base_type is not None:
            base_align = (
                1 if self.is_packed else align_of(self.the_base_type, owner=self)
            )
            max_align = max(max_align, base_align)
            off = size_of(self.the_base_type, owner=self)
        cur_storage_sz = 0
        cur_storage_off = 0
        cur_bits_used = 0
        for entry in self.layout_entries:
            member = entry.member
            if member is None:
                assert entry.bit_field_type is not None
                assert entry.bit_field_width is not None
                storage_sz = size_of(entry.bit_field_type, owner=self)
                storage_align = (
                    1 if self.is_packed else align_of(entry.bit_field_type, owner=self)
                )
                max_align = max(max_align, storage_align)
                storage_bits = storage_sz * 8
                if entry.bit_field_width == 0:
                    if cur_storage_sz > 0:
                        off = cur_storage_off + cur_storage_sz
                        cur_storage_sz = 0
                        cur_bits_used = 0
                    if not self.is_packed:
                        off = align_up(off, storage_align)
                    continue
                if (
                    cur_storage_sz == storage_sz
                    and cur_bits_used + entry.bit_field_width <= storage_bits
                ):
                    cur_bits_used += entry.bit_field_width
                    continue
                if cur_storage_sz > 0:
                    off = cur_storage_off + cur_storage_sz
                if not self.is_packed:
                    off = align_up(off, storage_align)
                cur_storage_off = off
                cur_storage_sz = storage_sz
                cur_bits_used = entry.bit_field_width
                continue
            if member.bit_field_width is not None:
                storage_sz = size_of(member.typ, owner=self)
                storage_align = (
                    1 if self.is_packed else align_of(member.typ, owner=self)
                )
                max_align = max(max_align, storage_align)
                storage_bits = storage_sz * 8
                width = member.bit_field_width
                if width == 0:
                    if cur_storage_sz > 0:
                        off = cur_storage_off + cur_storage_sz
                        cur_storage_sz = 0
                        cur_bits_used = 0
                    if not self.is_packed:
                        off = align_up(off, storage_align)
                    continue
                if (
                    cur_storage_sz == storage_sz
                    and cur_bits_used + width <= storage_bits
                ):
                    bit_shift = cur_bits_used
                    byte_off = cur_storage_off
                    cur_bits_used += width
                else:
                    if cur_storage_sz > 0:
                        off = cur_storage_off + cur_storage_sz
                    if not self.is_packed:
                        off = align_up(off, storage_align)
                    cur_storage_off = off
                    cur_storage_sz = storage_sz
                    bit_shift = 0
                    byte_off = cur_storage_off
                    cur_bits_used = width
                direct_member_offsets[member] = byte_off
                if member.name is not None:
                    offsets[member.name] = byte_off
                    bit_field_info[member.name] = BitFieldInfo(
                        byte_offset=byte_off,
                        bit_shift=bit_shift,
                        bit_mask=(1 << width) - 1,
                        storage_sz=storage_sz,
                    )
                continue
            if cur_storage_sz > 0:
                off = cur_storage_off + cur_storage_sz
                cur_storage_sz = 0
                cur_bits_used = 0
            member_align = 1 if self.is_packed else align_of(member.typ, owner=self)
            max_align = max(max_align, member_align)
            if not self.is_packed:
                off = align_up(off, member_align)
            direct_member_offsets[member] = off
            if member.name is not None:
                offsets[member.name] = off
            off += size_of(member.typ, owner=self)
        if cur_storage_sz > 0:
            off = cur_storage_off + cur_storage_sz
        struct_align = 1 if self.is_packed else max_align
        if self.align_override is not None:
            struct_align = max(struct_align, self.align_override)
        if not self.is_packed or self.align_override is not None:
            off = align_up(off, struct_align)
        layout = AggregateLayout(off, struct_align, offsets, bit_field_info)
        self._layout_cache = layout
        self.bit_field_info = bit_field_info
        self._precomp_byte_offsets = offsets
        self._direct_member_offsets = direct_member_offsets
        self._bf_struct_total_sz = off
        return layout

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        # Handle __attribute__((...)) before the struct name
        c, attrs = consume_gnu_attrs(tokens, c, end, context)
        apply_gnu_attributes_to_type(self, attrs)
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        # Handle __attribute__((...)) between name and body
        c, attrs = consume_gnu_attrs(tokens, c, end, context)
        apply_gnu_attributes_to_type(self, attrs)
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(
                    tokens, c, "Expected a Type to follow ':' in class declaration"
                )
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in ("{", "[", "("):
                    lvl += 1
                elif s in ("}", "]", ")"):
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, start, "Expected closing '}' for struct")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].str in {"public", "private", "protected"}:
                    # TODO: IDEA: store a current access specifier variable
                    # TODO:   then combine that with inst in the definition of function: 'NewVar(self, V, inst)'
                    raise ParsingError(
                        tokens, c, "access specifier keywords not allowed"
                    )
                try:
                    stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
                except ParsingError:
                    print("self.name = " + repr(self.name))
                    raise
            c = end_t
            self.defined = True
            self.incomplete = False
            # Handle __attribute__((...)) after the struct body
            c, attrs = consume_gnu_attrs(tokens, c, end, context)
            apply_gnu_attributes_to_type(self, attrs)
            self._validate_flexible_array_members()
        return c

    def compile_var_init(
        self,
        cmpl_obj: "BaseCmplObj",
        init_args: List[Union["BaseExpr", "CurlyStmnt"]],
        context: "CompileContext",
        ref: "VarRef",
        cmpl_data: Optional["LocalCompileData"] = None,
        temp_links: Optional[Tuple["BaseType", "BaseLink"]] = None,
    ):
        if self.incomplete:
            raise TypeError("struct %s is incomplete" % self.name)
        link = None
        name = None
        ctx_var = None
        is_local = True
        static_res = compile_static_storage_decl(
            self, cmpl_obj, init_args, context, ref, cmpl_data, temp_links
        )
        if static_res is not None:
            return static_res
        sz_var = size_of(self)
        if ref.ref_type == VAR_REF_TOS_NAMED:
            assert isinstance(ref, VarRefTosNamed)
            ctx_var = ref.ctx_var
            if ctx_var is not None:
                assert isinstance(ctx_var, ContextVariable)
                name = ctx_var.get_link_name()
                is_local = ctx_var.uses_stack_storage()
                if not is_local:
                    assert isinstance(cmpl_obj, Compilation)
                    cmpl_obj1 = cmpl_obj.spawn_compile_object(
                        CompileObjectType.GLOBAL, name
                    )
                    cmpl_obj1.memory.extend([0] * sz_var)
                    link = cmpl_obj.get_link(name)
        elif ref.ref_type == VAR_REF_LNK_PREALLOC:
            assert isinstance(ref, VarRefLnkPrealloc)
            if len(init_args) == 0:
                return sz_var
            link = ref.lnk
        else:
            raise TypeError("Unrecognized VarRef: %s" % repr(ref))
        # ── Curly initialiser path:  struct foo f = { ... } ──────────────────────
        if (
            len(init_args) == 1
            and isinstance(init_args[0], CurlyExpr)
            and init_args[0].lst_expr is not None
        ):
            curly = init_args[0]
            if link is None:
                assert is_local
                assert cmpl_data is not None
                assert ctx_var is not None
                sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
                lnk = cmpl_data.put_local(ctx_var, name, sz_var, None, True)
            else:
                lnk = link
            zero_init_link(
                cmpl_obj,
                lnk,
                sz_var,
                volatile_access=is_volatile_storage_type(
                    self if ctx_var is None else ctx_var.typ
                ),
            )
            next_field_index = 0
            for elem in curly.lst_expr:
                target_index = next_field_index
                subexpr = elem
                if isinstance(elem, DesigInitExpr):
                    if elem.kind != DesigInitExpr.KIND_FIELD:
                        raise TypeError(
                            "Cannot use array designators in a struct initializer"
                        )
                    target_index = self.definition[elem.designator]
                    subexpr = elem.expr
                if target_index >= len(self.var_order) or subexpr is None:
                    raise TypeError("Too many elements in struct initializer")
                field_var = self.var_order[target_index]
                if is_flexible_array_type(field_var.typ):
                    raise TypeError(
                        "Flexible array member '%s' cannot be initialized"
                        % field_var.name
                    )
                field_lnk = lnk.get_offset_link(self.offset_of(field_var.name))
                field_var.typ.compile_var_init(
                    cmpl_obj,
                    [subexpr],
                    context,
                    VarRefLnkPrealloc(field_lnk),
                    cmpl_data,
                    temp_links,
                )
                next_field_index = target_index + 1
            return sz_var
        # ── End curly-initialiser path ───────────────────────────────────────────
        if len(init_args) > 1:
            raise TypeError(
                "Cannot instantiate struct types with more than one argument"
            )
        if link is None:
            assert is_local
            assert cmpl_data is not None, "Expected cmpl_data to not be None for LOCAL"
            if len(init_args) == 0:
                sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
            else:
                expr = init_args[0]
                typ = expr.t_anot
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(typ)
                assert compare_no_cvr(self, src_vt), "self = %s, SrvVT = %s" % (
                    get_user_str_from_type(self),
                    get_user_str_from_type(src_vt),
                )
                sz = compile_expr(
                    cmpl_obj, expr, context, cmpl_data, src_pt, temp_links
                )
                if is_src_ref:
                    assert sz == 8
                    emit_tracked_abs_s8_load(
                        cmpl_obj,
                        sz_var,
                        is_volatile_storage_type(expr.t_anot, through_ref=True),
                        atomic_access=is_atomic_storage_type(
                            expr.t_anot, through_ref=True
                        ),
                    )
                else:
                    assert sz == sz_var
            if ctx_var is not None:
                cmpl_data.put_local(ctx_var, name, sz_var, None, True)
        else:
            assert ctx_var is None or isinstance(ctx_var, ContextVariable)
            var_name = "<NONE>" if ctx_var is None else ctx_var.name
            if len(init_args):
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(init_args[0].t_anot)
                err0 = "Expected Expression sz == %s, but %u != %u (name = %r, linkName = '%s', expr = %r)"
                link_name = "<PREALLOC>" if name is None else name
                if is_src_ref:
                    sz = compile_expr(
                        cmpl_obj, init_args[0], context, cmpl_data, src_pt, temp_links
                    )
                    assert sz == 8, err0 % (
                        "sizeof(void*)",
                        sz,
                        8,
                        var_name,
                        link_name,
                        init_args[0],
                    )
                    emit_tracked_abs_s8_load(
                        cmpl_obj,
                        sz_var,
                        is_volatile_storage_type(init_args[0].t_anot, through_ref=True),
                        atomic_access=is_atomic_storage_type(
                            init_args[0].t_anot, through_ref=True
                        ),
                    )
                else:
                    sz = compile_expr(
                        cmpl_obj, init_args[0], context, cmpl_data, src_vt, temp_links
                    )
                    assert sz == sz_var, err0 % (
                        "sz_var",
                        sz,
                        sz_var,
                        var_name,
                        link_name,
                        init_args[0],
                    )
                link.emit_stor(
                    cmpl_obj.memory,
                    sz_var,
                    cmpl_obj,
                    byte_copy_cmpl_intrinsic,
                    volatile_access=is_volatile_storage_type(
                        self if ctx_var is None else ctx_var.typ
                    ),
                    atomic_access=is_atomic_storage_type(
                        self if ctx_var is None else ctx_var.typ
                    ),
                )
        return sz_var

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        return -1

    def new_var(self, v: str, inst: "ContextVariable") -> "ContextVariable":
        if inst.mods == VarDeclMods.STATIC:
            return super(StructType, self).new_var(v, inst)
        self.definition[v] = len(self.var_order)
        self.var_order.append(inst)
        self.layout_entries.append(StructLayoutEntry(member=inst))
        self._invalidate_layout()
        return inst

    def add_anonymous_member(self, inst: "ContextVariable") -> "ContextVariable":
        self.layout_entries.append(StructLayoutEntry(member=inst))
        self._invalidate_layout()
        return inst

    def _init_bf_layout(self):
        """Compatibility shim for older bit-field code paths."""
        self._invalidate_layout()

    def _consume_padding_bits(self, storage_type: "BaseType", width: int):
        """Handle an unnamed bit field (i.e. padding) in struct layout."""
        self.layout_entries.append(
            StructLayoutEntry(
                member=None,
                bit_field_type=storage_type,
                bit_field_width=width,
            )
        )
        self._invalidate_layout()

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


from ...PrettyRepr import get_pretty_repr
from .StructLayoutEntry import StructLayoutEntry
from .AggregateLayout import AggregateLayout
from .AggregateMemberResolution import AggregateMemberResolution
from .BitFieldInfo import BitFieldInfo
from .ContextVariable import ContextVariable
from .align_size_of import align_of
from ..ParsingError import ParsingError
from .align_util import align_up
from .VarDeclMods import VarDeclMods
from .qual_atomic_type_util import (
    get_base_prim_type,
    is_volatile_storage_type,
    is_atomic_storage_type,
)
from .gnu_attrs import consume_gnu_attrs, apply_gnu_attributes_to_type
from .helpers.VarRef import (
    VAR_REF_LNK_PREALLOC,
    VAR_REF_TOS_NAMED,
    VarRef,
    VarRefLnkPrealloc,
    VarRefTosNamed,
)
from ...code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..try_get_as_name import try_get_as_name
from ...lexer.lexer import Token, tok_to_str
from .Attribute import Attribute
from .get_base_type import get_base_type
from .get_strict_stmnt import get_strict_stmnt
from .align_size_of import size_of
from ...code_gen.compile_expr import compile_expr
from ...code_gen.byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from ...code_gen.BaseCmplObj import BaseCmplObj
from ...code_gen.BaseLink import BaseLink
from ...code_gen.LocalCompileData import LocalCompileData
from ...code_gen.memory_access import emit_tracked_abs_s8_load
from .qual_atomic_type_util import (
    get_tgt_ref_type,
    compare_no_cvr,
    is_flexible_array_type,
)
from ...StackVM.PyStackVM import BC_ADD_SP1
from .compile_static_storage_decl import compile_static_storage_decl
from ..expr.CurlyExpr import CurlyExpr
from ..expr.DesigInitExpr import DesigInitExpr
from .get_user_str_from_type import get_user_str_from_type
from ...code_gen.zero_init_link import zero_init_link
from ...code_gen.Compilation import CompileObjectType, Compilation
from ..expr.BaseExpr import BaseExpr
from ..stmnt.CurlyStmnt import CurlyStmnt
from .UnionType import UnionType
