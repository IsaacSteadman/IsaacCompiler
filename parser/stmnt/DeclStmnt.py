from typing import List, Optional
from .BaseStmnt import BaseStmnt, StmntType


class DeclStmnt(BaseStmnt):
    stmnt_type = StmntType.DECL
    # decl_lst added to init-args for __repr__

    def __init__(self, decl_lst: Optional[List["SingleVarDecl"]] = None):
        self.decl_lst = decl_lst

    def pretty_repr(self, pretty_repr_ctx=None):
        return (
            [self.__class__.__name__, "("]
            + get_pretty_repr(self.decl_lst, pretty_repr_ctx)
            + [")"]
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        ext_spec = 0
        while tokens[c].type_id == TokenType.NAME and tokens[c].str in {
            "extern",
            "static",
            "inline",
            "_Noreturn",
        }:
            if tokens[c].str == "static":
                ext_spec = 1
            elif tokens[c].str == "extern":
                ext_spec = 2
            # inline is a no-op hint for this compiler
            c += 1
        ctor_attr_cursor = c
        ctor_decl_attrs = GNUAttributes()
        while (
            ctor_attr_cursor < end
            and tokens[ctor_attr_cursor].type_id == TokenType.NAME
            and tokens[ctor_attr_cursor].str == "__attribute__"
        ):
            ctor_attr_cursor, attrs = consume_gnu_attrs(
                tokens, ctor_attr_cursor, end, context
            )
            ctor_decl_attrs.merge(attrs)
        if (
            isinstance(context, BaseType)
            and context.type_class_id
            in [TypeClass.STRUCT, TypeClass.CLASS, TypeClass.UNION]
            and tokens[ctor_attr_cursor].str == context.name
            and ctor_attr_cursor + 1 < len(tokens)
            and tokens[ctor_attr_cursor + 1].str == "("
        ):
            base_type = void_t
            # TODO: choose a value that will signal that this is a constructor
            #   or instead, don't enter the 'while c < end_stmnt + 1' loop
            named_qual_type, new_c = proc_typed_decl(
                tokens, ctor_attr_cursor, end, context, base_type
            )
            assert isinstance(named_qual_type, IdentifiedQualType)
            apply_gnu_attributes_to_decl(named_qual_type, ctor_decl_attrs)
            assert isinstance(context, (StructType, ClassType, UnionType))
            typ = named_qual_type.typ
            assert isinstance(typ, BaseType)
            if (
                named_qual_type.name == context.name
                and typ.type_class_id == TypeClass.QUAL
            ):
                assert isinstance(typ, QualType)
                if typ.qual_id == QualType.QUAL_FN:
                    if ext_spec != 0:
                        raise ParsingError(
                            tokens,
                            c,
                            "unexpected 'extern' or 'const' in Constructor declaration",
                        )
                    typ.qual_id = QualType.QUAL_CTOR
                    params = typ.ext_inf
                    assert isinstance(params, list)
                    params.insert(
                        0,
                        IdentifiedQualType(
                            "this",
                            QualType(
                                QualType.QUAL_PTR,
                                QualType(QualType.QUAL_CONST, context),
                            ),
                        ),
                    )
                    stmnt = None
                    if tokens[new_c].str == "{":
                        stmnt = CurlyStmnt()
                        fn_ctx = context.new_scope(LocalScope(named_qual_type.name))
                        for param in params:
                            if param is None:  # variadic sentinel
                                continue
                            assert isinstance(param, (IdentifiedQualType, BaseType))
                            if isinstance(param, IdentifiedQualType):
                                fn_ctx.new_var(
                                    param.name,
                                    ContextVariable(
                                        param.name, param.typ, None, VarDeclMods.IS_ARG
                                    ),
                                )
                        new_c = stmnt.build(tokens, new_c, end, fn_ctx)
                    self.decl_lst = [
                        SingleVarDecl(
                            typ,
                            named_qual_type.name,
                            [] if stmnt is None else [stmnt],
                            0,
                            INIT_CURLY,
                            named_qual_type.attributes,
                        )
                    ]
                    return new_c
        base_decl_attrs = GNUAttributes()
        base_type, c = get_base_type(tokens, c, end, context, base_decl_attrs)
        end_stmnt = c
        lvl = 0
        # TODO: remove this limitation as this would break inline struct definitions (like struct {int a; char b} var)
        # TODO: Done
        while end_stmnt < end and (tokens[end_stmnt].str != ";" or lvl > 0):
            if tokens[end_stmnt].str in OPEN_GROUPS:
                lvl += 1
            elif tokens[end_stmnt].str in CLOSE_GROUPS:
                lvl -= 1
            end_stmnt += 1
        if base_type is None:
            raise SyntaxError("Expected Typename for DeclStmnt")
        self.decl_lst = []
        while c < end_stmnt + 1:
            is_non_semi_colon_end = False
            named_qual_type, c = proc_typed_decl(
                tokens, c, end_stmnt, context, base_type
            )
            if named_qual_type is None:
                raise ParsingError(tokens, c, "Expected Typename for DeclStmnt")
            assert isinstance(named_qual_type, IdentifiedQualType)
            apply_gnu_attributes_to_decl(named_qual_type, base_decl_attrs)
            cur_decl = None
            bf_width = None
            ctx_var = None

            def _copy_named_decl_attrs(inst: "ContextVariable") -> "ContextVariable":
                inst.align_override = named_qual_type.align_override
                inst.section_name = named_qual_type.section_name
                inst.alias_name = named_qual_type.alias_name
                inst.cleanup_name = named_qual_type.cleanup_name
                inst.noreturn = named_qual_type.noreturn
                inst.used = named_qual_type.used
                inst.unused = named_qual_type.unused
                inst.always_inline = named_qual_type.always_inline
                inst.noinline = named_qual_type.noinline
                inst.deprecated = named_qual_type.deprecated
                inst.error_message = named_qual_type.error_message
                inst.warning_message = named_qual_type.warning_message
                inst.attributes = list(named_qual_type.attributes)
                return inst

            def _new_decl_ctx_var() -> "ContextVariable":
                inst = ContextVariable(
                    named_qual_type.name, named_qual_type.typ, None, ext_spec
                )
                return _copy_named_decl_attrs(inst)

            if named_qual_type.name is None:
                if (
                    c < end_stmnt
                    and tokens[c].str == ":"
                    and c + 1 < end_stmnt
                    and tokens[c + 1].type_id
                    in {
                        TokenType.DEC_INT,
                        TokenType.HEX_INT,
                        TokenType.OCT_INT,
                        TokenType.BIN_INT,
                    }
                ):
                    c += 1  # consume ':'
                    bf_width = int(tokens[c].str, 0)
                    c += 1  # consume integer
                    if isinstance(context, StructType):
                        context._consume_padding_bits(named_qual_type.typ, bf_width)
                elif tokens[c].str == ";":
                    anon_type = get_base_prim_type(named_qual_type.typ)
                    if (
                        isinstance(context, (StructType, UnionType))
                        and isinstance(anon_type, (StructType, UnionType))
                        and anon_type.name is None
                    ):
                        inst = ContextVariable(
                            named_qual_type.name,
                            named_qual_type.typ,
                            None,
                            ext_spec,
                        )
                        _copy_named_decl_attrs(inst)
                        context.add_anonymous_member(inst)
                    c += 1
                    break
                elif tokens[c].str == ",":
                    raise ParsingError(tokens, c, "Expected a name before ','")
            elif tokens[c].str == "=":
                ctx_var = context.new_var(named_qual_type.name, _new_decl_ctx_var())
                ctx_var.is_op_fn = named_qual_type.is_op_fn
                c += 1
                expr, c = get_expr(tokens, c, ",", end_stmnt, context)
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    [expr],
                    ext_spec,
                    INIT_ASSIGN,
                    named_qual_type.attributes,
                )
            elif tokens[c].str == "(":
                ctx_var = context.new_var(named_qual_type.name, _new_decl_ctx_var())
                ctx_var.is_op_fn = named_qual_type.is_op_fn
                c += 1
                lvl = 1
                c0 = c
                while lvl > 0 and c0 < end:
                    if tokens[c0].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c0].str in CLOSE_GROUPS:
                        lvl -= 1
                    c0 += 1
                end_p = c0 - 1
                if tokens[end_p].str != ")":
                    raise ParsingError(
                        tokens, end_p, "Expected closing ')' before end of statement"
                    )
                init_args = []
                while c < end_p:
                    expr, c = get_expr(tokens, c, ",", end_p, context)
                    init_args.append(expr)
                    c += 1
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    init_args,
                    ext_spec,
                    INIT_PARENTH,
                    named_qual_type.attributes,
                )
            elif tokens[c].str == "{":
                init_args = []
                prim_type = get_base_prim_type(named_qual_type.typ)
                start = c
                ctx_var = context.new_var(named_qual_type.name, _new_decl_ctx_var())
                ctx_var.is_op_fn = named_qual_type.is_op_fn
                if prim_type.type_class_id == TypeClass.QUAL:
                    assert isinstance(prim_type, QualType)
                    if prim_type.qual_id == QualType.QUAL_FN:
                        stmnt = CurlyStmnt()
                        init_args.append(stmnt)
                        fn_ctx = context.new_scope(LocalScope(named_qual_type.name))
                        assert prim_type.ext_inf is not None
                        assert not isinstance(prim_type.ext_inf, int)
                        params = prim_type.ext_inf
                        if prim_type.qual_id == QualType.QUAL_CL_FN:
                            assert isinstance(context, BaseType)
                            assert context.type_class_id in [
                                TypeClass.STRUCT,
                                TypeClass.CLASS,
                                TypeClass.UNION,
                            ]
                            assert isinstance(
                                context, (StructType, ClassType, UnionType)
                            )
                            params.insert(
                                0,
                                IdentifiedQualType(
                                    "this",
                                    QualType(
                                        QualType.QUAL_PTR,
                                        QualType(QualType.QUAL_CONST, context),
                                    ),
                                ),
                            )
                        for param in prim_type.ext_inf:
                            if param is None:  # variadic sentinel
                                continue
                            assert isinstance(param, (IdentifiedQualType, BaseType))
                            if isinstance(param, IdentifiedQualType):
                                fn_ctx.new_var(
                                    param.name,
                                    ContextVariable(
                                        param.name, param.typ, None, VarDeclMods.IS_ARG
                                    ),
                                )
                        c = stmnt.build(tokens, c, end, fn_ctx)
                        is_non_semi_colon_end = True
                if len(init_args) == 0:
                    expr = CurlyExpr()
                    init_args.append(expr)
                    c = expr.build(tokens, c, end, context)
                if start == c:
                    raise ParsingError(
                        tokens, c, "Could not parse CurlyStmnt or CurlyExpr"
                    )
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    init_args,
                    ext_spec,
                    INIT_CURLY,
                    named_qual_type.attributes,
                )
            elif tokens[c].str == ":":
                c += 1  # consume ':'
                bf_width = int(tokens[c].str, 0)
                c += 1  # consume integer
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    [],
                    ext_spec,
                    attributes=named_qual_type.attributes,
                )
            else:
                # print "else: tokens[%u] = %r" % (c, tokens[c])
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    [],
                    ext_spec,
                    attributes=named_qual_type.attributes,
                )
            if cur_decl is not None:
                self.decl_lst.append(cur_decl)
                if ctx_var is None:
                    inst = ContextVariable(
                        cur_decl.var_name, cur_decl.type_name, None, ext_spec
                    )
                    _copy_named_decl_attrs(inst)
                    if bf_width is not None:
                        inst.bit_field_width = bf_width
                    ctx_var = context.new_var(cur_decl.var_name, inst)
                    ctx_var.is_op_fn = named_qual_type.is_op_fn
                elif bf_width is not None:
                    ctx_var.bit_field_width = bf_width
                # NOTE the following must be true: SingleVarDecl(...).type_name is ContextVariable(...).typ
            if is_non_semi_colon_end:
                break
            elif tokens[c].str == ";":
                c += 1
                break
            elif tokens[c].str == ",":
                c += 1
        return c


from ..type.CompileContext import CompileContext
from ..type.IdentifiedQualType import IdentifiedQualType
from ..type.get_base_type import get_base_type
from ..type.gnu_attrs import GNUAttributes
from ..type.BaseType import BaseType
from ..type.QualType import QualType
from ..type.StructType import StructType
from ..type.UnionType import UnionType
from ..type.ClassType import ClassType
from ..type.ContextVariable import ContextVariable
from ..expr.get_expr import get_expr
from ...lexer.lexer import Token, TokenType
from ...ParseConstants import (
    CLOSE_GROUPS,
    INIT_ASSIGN,
    INIT_CURLY,
    INIT_PARENTH,
    OPEN_GROUPS,
)
from ..ParsingError import ParsingError
from ..type.proc_typed_decl import proc_typed_decl
from .helpers.SingleVarDecl import SingleVarDecl
from ..type.gnu_attrs import consume_gnu_attrs, apply_gnu_attributes_to_decl
from .CurlyStmnt import CurlyStmnt
from ..expr.CurlyExpr import CurlyExpr
from ..type.VarDeclMods import VarDeclMods
from ..type.BaseType import TypeClass
from ..type.qual_atomic_type_util import get_base_prim_type
from ..type.LocalScope import LocalScope
from ..type.PrimitiveType import void_t
from ...PrettyRepr import get_pretty_repr
