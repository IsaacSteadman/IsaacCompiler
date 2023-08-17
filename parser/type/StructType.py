from typing import List, Optional, Tuple, Union, TYPE_CHECKING
from .BaseType import BaseType, TypeClass
from ..context.CompileContext import CompileContext


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
    def from_mangle(cls, s, c):
        """
        :param str s:
        :param int c:
        :rtype: (StructType, int)
        """
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return StructType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "B%u%s" % (len(name), name)

    def __init__(
        self,
        parent,
        name=None,
        incomplete=True,
        definition=None,
        var_order=None,
        defined=False,
        the_base_type=None,
    ):
        """
        :param CompileContext|None parent:
        :param unicode|str|None name:
        :param bool incomplete:
        :param dict[str,int] definition:
        :param list[ContextVariable] var_order:
        :param bool defined:
        :param BaseType|None the_base_type:
        """
        super(StructType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.var_order = [] if var_order is None else var_order
        self.defined = defined
        self.the_base_type = the_base_type

    def offset_of(self, attr):
        """
        :param str attr:
        :rtype: int
        """
        # TODO: improve speed of OffsetOf by tracking the offsets along-side the types
        index = self.definition[attr]
        off = 0
        for c in range(index):
            off += size_of(self.var_order[0].typ)
        return off

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.var_order,
                self.defined,
                self.the_base_type,
            )
        )

    def merge_to(self, other):
        assert isinstance(other, StructType)
        super(StructType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.var_order = self.var_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
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
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
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
        """ """
        if self.incomplete:
            raise TypeError("struct %s is incomplete" % self.name)
        link = None
        name = None
        ctx_var = None
        is_local = True
        sz_var = size_of(self)
        if ref.ref_type == VAR_REF_TOS_NAMED:
            assert isinstance(ref, VarRefTosNamed)
            ctx_var = ref.ctx_var
            if ctx_var is not None:
                assert isinstance(ctx_var, ContextVariable)
                name = ctx_var.get_link_name()
                is_local = ctx_var.parent.is_local_scope()
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
                    sz_cls = sz_var.bit_length() - 1
                    assert sz_var == (1 << sz_cls)
                    cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                else:
                    assert sz == sz_var
            if ctx_var is not None:
                cmpl_data.put_local(ctx_var, name, sz_var, None, True)
        else:
            assert cmpl_data is None, "Expected cmpl_data to be None for GLOBAL"
            assert isinstance(cmpl_obj, Compilation)
            assert ctx_var is None or isinstance(ctx_var, ContextVariable)
            var_name = "<NONE>" if ctx_var is None else ctx_var.name
            assert name is not None
            if len(init_args):
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(init_args[0].t_anot)
                err0 = "Expected Expression sz == %s, but %u != %u (name = %r, linkName = '%s', expr = %r)"
                if is_src_ref:
                    sz = compile_expr(
                        cmpl_obj, init_args[0], context, cmpl_data, src_pt, temp_links
                    )
                    assert sz == 8, err0 % (
                        "sizeof(void*)",
                        sz,
                        8,
                        var_name,
                        name,
                        init_args[0],
                    )
                    sz_cls = sz_var.bit_length() - 1
                    assert sz_var == 1 << sz_cls
                    cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                else:
                    sz = compile_expr(
                        cmpl_obj, init_args[0], context, cmpl_data, src_vt, temp_links
                    )
                    assert sz == sz_var, err0 % (
                        "sz_var",
                        sz,
                        sz_var,
                        var_name,
                        name,
                        init_args[0],
                    )
                link.emit_stor(
                    cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic
                )
        return sz_var

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        return -1

    def new_var(self, v: str, inst: "ContextVariable") -> "ContextVariable":
        if inst.mods == VarDeclMods.STATIC:
            return super(StructType, self).new_var(v, inst)
        self.definition[v] = len(self.var_order)
        self.var_order.append(inst)
        return inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


from .compare_no_cvr import compare_no_cvr
from .get_user_str_from_type import get_user_str_from_type
from .size_of import size_of
from ..ParsingError import ParsingError
from .helpers.VarRef import (
    VAR_REF_LNK_PREALLOC,
    VAR_REF_TOS_NAMED,
    VarRef,
    VarRefLnkPrealloc,
    VarRefTosNamed,
)
from ...ParseConstants import CLOSE_GROUPS, OPEN_GROUPS
from ...PrettyRepr import get_pretty_repr
from ...lexer.lexer import Token, tok_to_str
from ..try_get_as_name import try_get_as_name
from ..context.CompileContext import CompileContext
from ..context.ContextVariable import ContextVariable, VarDeclMods
from ..expr.BaseExpr import BaseExpr
from ..stmnt.get_strict_stmnt import get_strict_stmnt
from ...StackVM.PyStackVM import BCR_ABS_S8, BC_ADD_SP1, BC_LOAD
from ...code_gen.BaseCmplObj import BaseCmplObj
from ...code_gen.BaseLink import BaseLink
from ...code_gen.Compilation import Compilation, CompileObjectType
from ...code_gen.LocalCompileData import LocalCompileData
from ...code_gen.byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from ...code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from .get_tgt_ref_type import get_tgt_ref_type
from .get_base_type import get_base_type
from ...code_gen.compile_expr import compile_expr

if TYPE_CHECKING:
    from ..stmnt.CurlyStmnt import CurlyStmnt
