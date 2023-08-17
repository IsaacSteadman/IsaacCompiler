from typing import List
from .BaseStmnt import BaseStmnt, StmntType


class DeclStmnt(BaseStmnt):
    stmnt_type = StmntType.DECL
    # decl_lst added to init-args for __repr__

    def __init__(self, decl_lst=None):
        """
        :param list[SingleVarDecl]|None decl_lst:
        """
        self.decl_lst = decl_lst

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.decl_lst) + [")"]

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        ext_spec = 0
        if tokens[c].type_id == TokenType.NAME:
            if tokens[c].str == "static":
                ext_spec = 1
                c += 1
            elif tokens[c].str == "extern":
                ext_spec = 2
                c += 1
        if (
            isinstance(context, BaseType)
            and context.type_class_id
            in [TypeClass.STRUCT, TypeClass.CLASS, TypeClass.UNION]
            and tokens[c].str == context.name
            and c + 1 < len(tokens)
            and tokens[c + 1].str == "("
        ):
            base_type = void_t
            # TODO: choose a value that will signal that this is a constructor
            #   or instead, don't enter the 'while c < end_stmnt + 1' loop
            named_qual_type, new_c = proc_typed_decl(tokens, c, end, context, base_type)
            assert isinstance(named_qual_type, IdentifiedQualType)
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
                        )
                    ]
                    return new_c
        base_type, c = get_base_type(tokens, c, end, context)
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
            cur_decl = None
            if named_qual_type.name is None:
                pass
            elif tokens[c].str == "=":
                c += 1
                expr, c = get_expr(tokens, c, ",", end_stmnt, context)
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    [expr],
                    ext_spec,
                    INIT_ASSIGN,
                )
            elif tokens[c].str == "(":
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
                )
            elif tokens[c].str == "{":
                init_args = []
                prim_type = get_base_prim_type(named_qual_type.typ)
                start = c
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
                )
            else:
                # print "else: tokens[%u] = %r" % (c, tokens[c])
                cur_decl = SingleVarDecl(
                    named_qual_type.typ, named_qual_type.name, [], ext_spec
                )
            if cur_decl is not None:
                self.decl_lst.append(cur_decl)
                ctx_var = context.new_var(
                    cur_decl.var_name,
                    ContextVariable(
                        cur_decl.var_name, cur_decl.type_name, None, ext_spec
                    ),
                )
                ctx_var.is_op_fn = named_qual_type.is_op_fn
                # NOTE the following must be true: SingleVarDecl(...).type_name is ContextVariable(...).typ
            if is_non_semi_colon_end:
                break
            elif tokens[c].str == ";":
                c += 1
                break
            elif tokens[c].str == ",":
                c += 1
        return c


from ..ParsingError import ParsingError
from ...lexer.lexer import Token, TokenType
from ..context.CompileContext import CompileContext
from ..context.ContextVariable import ContextVariable, VarDeclMods
from ...PrettyRepr import get_pretty_repr
from ...ParseConstants import (
    INIT_ASSIGN,
    INIT_PARENTH,
    INIT_CURLY,
    OPEN_GROUPS,
    CLOSE_GROUPS,
)
from .helpers.SingleVarDecl import SingleVarDecl
from ..type.IdentifiedQualType import IdentifiedQualType
from ..type.BaseType import BaseType, TypeClass
from ..type.QualType import QualType
from ..type.StructType import StructType
from ..type.ClassType import ClassType
from ..type.UnionType import UnionType
from ..type.PrimitiveType import void_t
from .CurlyStmnt import CurlyStmnt
from ..context.LocalScope import LocalScope
from ..expr.CurlyExpr import CurlyExpr
from ..type.get_base_prim_type import get_base_prim_type
from ..type.proc_typed_decl import proc_typed_decl
from ..type.get_base_type import get_base_type
from ..expr.get_expr import get_expr
