from typing import Dict, List, Optional, Tuple
from .CompileContext import CompileContext
from .BaseType import BaseType, TypeClass


class UnionType(CompileContext, BaseType):
    def to_user_str(self):
        return "union " + self.name

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_init(
        self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None
    ):
        if self.incomplete:
            raise TypeError("union %s is incomplete" % self.name)
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
        if len(init_args) > 1:
            raise TypeError(
                "Cannot instantiate union types with more than one argument"
            )
        if link is None:
            assert is_local
            assert cmpl_data is not None, "Expected cmpl_data to not be None for LOCAL"
            if len(init_args) == 0:
                sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
            else:
                expr = init_args[0]
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(expr.t_anot)
                assert compare_no_cvr(self, src_vt), "self = %s, src_vt = %s" % (
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
            if len(init_args):
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(init_args[0].t_anot)
                err0 = "Expected Expression sz == %s, but %u != %u (name = %r, linkName = '%s', expr = %r)"
                var_name = "<NONE>" if ctx_var is None else ctx_var.name
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

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.UNION
    mangle_captures = {"U": None}

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["UnionType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return UnionType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl: bool = False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "U%u%s" % (len(name), name)

    def __init__(
        self,
        parent: Optional["CompileContext"],
        name: Optional[str] = None,
        incomplete: bool = True,
        definition: Optional[Dict[str, "ContextVariable"]] = None,
        member_order: Optional[List["ContextVariable"]] = None,
        defined: bool = False,
        the_base_type: Optional["BaseType"] = None,
    ):
        super(UnionType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.member_order = [] if member_order is None else member_order
        self.defined = defined
        self.the_base_type = the_base_type
        self.is_packed: bool = False
        self.align_override: Optional[int] = None
        self.attributes: List[Attribute] = []

    def offset_of(self, attr: str) -> int:
        resolved = self.resolve_member(attr)
        if resolved is None:
            raise KeyError(attr)
        return resolved.byte_offset

    def resolve_member(self, attr: str) -> Optional["AggregateMemberResolution"]:
        member = self.definition.get(attr, None)
        if member is not None:
            return AggregateMemberResolution(member, 0, None)
        for member in self.member_order:
            if member.name is not None:
                continue
            anon_type = get_base_prim_type(member.typ)
            if isinstance(anon_type, (StructType, UnionType)):
                resolved = anon_type.resolve_member(attr)
                if resolved is not None:
                    return resolved
        return None

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.member_order,
                self.defined,
                self.the_base_type,
            ),
            pretty_repr_ctx,
        )

    def merge_to(self, other: "UnionType"):
        assert isinstance(other, UnionType)
        super(UnionType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.member_order = self.member_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type
        other.is_packed = other.is_packed or self.is_packed
        if self.align_override is not None:
            cur = 0 if other.align_override is None else other.align_override
            other.align_override = max(cur, self.align_override)
        other.attributes.extend(self.attributes)

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        # Handle __attribute__((...)) before the union name
        c, attrs = consume_gnu_attrs(tokens, c, end, context)
        apply_gnu_attributes_to_type(self, attrs)
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        # Handle __attribute__((...)) after the union name
        c, attrs = consume_gnu_attrs(tokens, c, end, context)
        apply_gnu_attributes_to_type(self, attrs)
        if tokens[c].str == ":":
            raise ParsingError(tokens, c, "Inheritance is not allowed for unions")
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
                raise ParsingError(tokens, start, "Expected closing '}' for union")
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
                stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
            c = end_t
            self.defined = True
            self.incomplete = False
            # Handle __attribute__((...)) after the union body
            c, attrs = consume_gnu_attrs(tokens, c, end, context)
            apply_gnu_attributes_to_type(self, attrs)
        return c

    def new_var(self, v: str, inst: "ContextVariable"):
        assert isinstance(inst, ContextVariable)
        if inst.mods == VarDeclMods.STATIC:
            return super(UnionType, self).new_var(v, inst)
        self.definition[v] = inst
        self.member_order.append(inst)
        return inst

    def add_anonymous_member(self, inst: "ContextVariable") -> "ContextVariable":
        self.member_order.append(inst)
        return inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


from ...PrettyRepr import get_pretty_repr
from .AggregateMemberResolution import AggregateMemberResolution
from .ContextVariable import ContextVariable
from ..ParsingError import ParsingError
from .gnu_attrs import consume_gnu_attrs, apply_gnu_attributes_to_type
from .VarDeclMods import VarDeclMods
from .StructLayoutEntry import StructLayoutEntry
from .AggregateLayout import AggregateLayout
from .BitFieldInfo import BitFieldInfo
from .align_size_of import align_of
from .align_util import align_up
from .qual_atomic_type_util import (
    get_base_prim_type,
    is_volatile_storage_type,
    is_atomic_storage_type,
)
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
from .get_strict_stmnt import get_strict_stmnt
from .align_size_of import size_of
from ...code_gen.compile_expr import compile_expr
from ...code_gen.byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from ...code_gen.memory_access import emit_tracked_abs_s8_load
from .qual_atomic_type_util import (
    get_tgt_ref_type,
    compare_no_cvr,
)
from ...StackVM.PyStackVM import BC_ADD_SP1
from .compile_static_storage_decl import compile_static_storage_decl
from .get_user_str_from_type import get_user_str_from_type
from ...code_gen.Compilation import CompileObjectType, Compilation
from .StructType import StructType
