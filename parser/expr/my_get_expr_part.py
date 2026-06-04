from typing import Dict, List, NamedTuple, Optional, Tuple
from ..util import try_catch_wrapper0

"""def GetTypeName(tokens, c, end, context, Strict=False):
    type_name = TypeNameInf()
    try:
        c = type_name.build(tokens, c, end, context)
    except Exception as Exc:
        if Strict:
            raise
        else: return None, c
    return type_name, c"""

# TODO: find out why MyGetExprPart(..from LangTest.py, 107, 391, ..context) returns ?, 2


@try_catch_wrapper0
def my_get_expr_part(
    tokens: List["Token"],
    c: int,
    end: int,
    context: "CompileContext",
) -> Tuple["BaseOpPart", int]:
    s = tokens[c].str
    if LiteralExpr.is_literal_token(tokens[c]):
        rtn = LiteralExpr()
        c = rtn.build(tokens, c, end, context)
        return ExprOpPart(rtn), c
    elif s == ".":
        line, col = tokens[c].line, tokens[c].col
        c += 1
        if tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "expected name after '.'")
        s += tokens[c].str
        c += 1
        return SimpleOpPart(BreakSymClass(s, line, col)), c
    elif s == "->":
        line, col = tokens[c].line, tokens[c].col
        c += 1
        if tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "expected name after '.'")
        s += tokens[c].str
        c += 1
        return SimpleOpPart(OperatorClass(s, line, col)), c
    elif s in DCT_FIXES:
        rtn = SimpleOpPart(tokens[c])
        c += 1
        return rtn, c
    elif s == "(":
        lvl = 1
        start = c
        c += 1
        comma_count = 0
        while lvl > 0:
            s = tokens[c].str
            if s in OPEN_GROUPS:
                lvl += 1
            elif s in CLOSE_GROUPS:
                lvl -= 1
            elif s == "," and lvl == 1:
                comma_count += 1
            c += 1
        end_t = c
        end_p = end_t - 1
        c = start + 1
        if c == end_p:
            c = end_t
            return ParenthOpPart([]), c
        # GNU statement expression: ({ ... })
        if tokens[c].str == "{":
            stmnt_expr = StmntExpr()
            c = stmnt_expr.build(tokens, c, end_p, context)
            # c is now at ')'; advance past it
            c = end_t
            return ExprOpPart(stmnt_expr), c
        if comma_count == 0:
            type_name, type_c = proc_typed_decl(tokens, c, end_p, context)
            if type_c > start + 1 and type_name is not None:
                type_name.typ, type_c = _consume_abstract_decl_suffixes(
                    tokens, type_c, end_p, context, type_name.typ
                )
            if type_name is not None and type_c == end_p:
                assert isinstance(type_name, IdentifiedQualType)
                if type_name.name is not None:
                    print(
                        "WARN: (c = %u) Unexpected name in C-Style Cast Operator: '%s'"
                        % (type_c, type_name.name)
                    )
                if end_t < end and tokens[end_t].str == "{":
                    expr = CurlyExpr()
                    c = expr.build(tokens, end_t, end, context)
                    _deduce_compound_literal_array_extent(type_name.typ, expr)
                    return ExprOpPart(CompoundLiteralExpr(type_name.typ, expr)), c
                c = end_t
                return CastOpPart(type_name.typ), c
        lst_expr = [None] * (comma_count + 1)
        n_expr = 0
        while c < end_p:
            lst_expr[n_expr], c = get_expr(tokens, c, ",", end_p, context)
            c += 1
            n_expr += 1
        return ParenthOpPart(lst_expr), c
    elif s == "[":
        c += 1
        expr, c = get_expr(tokens, c, "]", end, context)
        if tokens[c].str != "]":
            raise ParsingError(
                tokens, c, "Only single expression inside '[' and ']' is allowed"
            )
        c += 1
        return SParenthOpPart(expr), c
    elif s == "{":
        expr = CurlyExpr()
        # TODO: fix the incorrect usage (will throw error if '}' is encountered)
        c = expr.build(tokens, c, end, context)
        c += 1  # TODO: verify this is correct usage of return value
        return ExprOpPart(expr), c
    elif s == "?":
        c += 1
        expr, c = get_expr(tokens, c, ":", end, context)
        c += 1
        return InlineIfOpPart(expr), c
    elif s == "__builtin_expect" and c + 1 < end and tokens[c + 1].str == "(":
        expr, c = _build_builtin_expect_expr(tokens, c + 2, end, context)
        return ExprOpPart(expr), c
    elif (
        s == "__builtin_types_compatible_p"
        and c + 1 < end
        and tokens[c + 1].str == "("
    ):
        expr, c = _build_builtin_types_compatible_expr(tokens, c + 2, end, context)
        return ExprOpPart(expr), c
    elif s == "__builtin_offsetof" and c + 1 < end and tokens[c + 1].str == "(":
        expr, c = _build_builtin_offsetof_expr(tokens, c + 2, end, context)
        return ExprOpPart(expr), c
    elif s in _builtin_unary_specs and c + 1 < end and tokens[c + 1].str == "(":
        expr, c = _build_builtin_unary_expr(s, tokens, c + 2, end, context)
        return ExprOpPart(expr), c
    elif s in _builtin_forward_specs and c + 1 < end and tokens[c + 1].str == "(":
        expr, c = _build_builtin_forward_expr(s, tokens, c + 2, end, context)
        return ExprOpPart(expr), c
    elif s in _atomic_intrinsic_specs and c + 1 < end and tokens[c + 1].str == "(":
        expr, c = _build_atomic_intrinsic_expr(s, tokens, c + 2, end, context)
        return ExprOpPart(expr), c
    elif (
        s in {"va_start", "va_arg", "va_end", "va_copy"}
        and c + 1 < end
        and tokens[c + 1].str == "("
    ):
        intrinsic_name = s
        c += 2  # consume name + '('
        paren_end = _find_call_paren_end(tokens, c, end)
        # paren_end is at ')'
        rtn_expr = _build_va_intrinsic(intrinsic_name, tokens, c, paren_end, context)
        c = paren_end + 1
        return ExprOpPart(rtn_expr), c
    elif tokens[c].type_id == TokenType.NAME:
        rtn = NameRefExpr()
        c = rtn.build(tokens, c, end, context)
        return ExprOpPart(rtn), c
    else:
        raise ParsingError(tokens, c, "Unrecognized Token Type")


from .CompoundLiteralExpr import CompoundLiteralExpr
from .CurlyExpr import CurlyExpr
from .DesigInitExpr import DesigInitExpr
from .AtomicIntrinsicExpr import AtomicIntrinsicExpr
from .BuiltinCallExpr import BuiltinCallExpr
from .CastOpExpr import CastOpExpr
from .LiteralExpr import LiteralExpr
from .NameRefExpr import NameRefExpr
from .ParenthExpr import ParenthExpr
from .StmntExpr import StmntExpr
from .VaIntrinsicExpr import VaIntrinsicExpr
from .get_implicit_conv_expr import get_implicit_conv_expr
from .get_expr import get_expr
from ..ParsingError import ParsingError
from ..constants import DCT_FIXES
from .expr_part.BaseOpPart import BaseOpPart
from .expr_part.CastOpPart import CastOpPart
from .expr_part.ExprOpPart import ExprOpPart
from .expr_part.InlineIfOpPart import InlineIfOpPart
from .expr_part.ParentOpPart import ParenthOpPart
from .expr_part.SParenthOpPart import SParenthOpPart
from .expr_part.SimpleOpPart import SimpleOpPart
from ...ParseConstants import CLOSE_GROUPS, OPEN_GROUPS
from ..type.types import (
    ClassType,
    CompileContext,
    ContextVariable,
    PrimitiveType,
    IdentifiedQualType,
    QualType,
    StructType,
    UnionType,
    bool_t,
    compare_no_cvr,
    get_value_type,
    is_atomic_type,
    proc_typed_decl,
    size_l_t,
    void_t,
)
from ...lexer.lexer import BreakSymClass, OperatorClass, Token, TokenType


_builtin_result_int_t = PrimitiveType.from_str_name(["signed", "int"])
_builtin_arg_u16_t = PrimitiveType.from_str_name(["unsigned", "short"])
_builtin_arg_u32_t = PrimitiveType.from_str_name(["unsigned", "int"])
_builtin_arg_u64_t = size_l_t
_builtin_ret_u16_t = PrimitiveType.from_str_name(["unsigned", "short"])
_builtin_ret_u32_t = PrimitiveType.from_str_name(["unsigned", "int"])
_builtin_ret_u64_t = size_l_t


class _BuiltinUnarySpec(NamedTuple):
    helper_name: str
    arg_type: "BaseType"
    result_type: "BaseType"


class _BuiltinForwardSpec(NamedTuple):
    helper_name: str
    arg_types: List["BaseType"]
    result_type: "BaseType"
    link_arg_types: List["BaseType"]


class _AtomicIntrinsicSpec(NamedTuple):
    intrinsic_id: int
    arg_count: int


def _get_builtin_helper_link_name(helper_name, arg_types, result_type, context):
    helper_ctx = CompileContext(
        "",
        None,
        None,
        name_mangling_mode=context.name_mangling_mode,
    )
    helper_type = QualType(QualType.QUAL_FN, result_type, list(arg_types))
    helper_var = ContextVariable(helper_name, helper_type)
    helper_ctx.new_var(helper_name, helper_var)
    return helper_var.get_link_name()


def _make_builtin_unary_spec(helper_name, arg_type, result_type):
    return _BuiltinUnarySpec(
        helper_name,
        arg_type,
        result_type,
    )


def _make_builtin_forward_spec(helper_name, arg_types, result_type):
    return _make_builtin_forward_spec_with_link_types(
        helper_name, arg_types, result_type, arg_types
    )


def _make_builtin_forward_spec_with_link_types(
    helper_name, arg_types, result_type, link_arg_types
):
    return _BuiltinForwardSpec(
        helper_name,
        list(arg_types),
        result_type,
        list(link_arg_types),
    )


_builtin_unary_specs: Dict[str, _BuiltinUnarySpec] = {
    "__builtin_clz": _make_builtin_unary_spec(
        "__svm_clz4", _builtin_arg_u32_t, _builtin_result_int_t
    ),
    "__builtin_clzl": _make_builtin_unary_spec(
        "__svm_clz8", _builtin_arg_u64_t, _builtin_result_int_t
    ),
    "__builtin_clzll": _make_builtin_unary_spec(
        "__svm_clz8", _builtin_arg_u64_t, _builtin_result_int_t
    ),
    "__builtin_ctz": _make_builtin_unary_spec(
        "__svm_ctz4", _builtin_arg_u32_t, _builtin_result_int_t
    ),
    "__builtin_ctzl": _make_builtin_unary_spec(
        "__svm_ctz8", _builtin_arg_u64_t, _builtin_result_int_t
    ),
    "__builtin_ctzll": _make_builtin_unary_spec(
        "__svm_ctz8", _builtin_arg_u64_t, _builtin_result_int_t
    ),
    "__builtin_popcount": _make_builtin_unary_spec(
        "__svm_popcnt4", _builtin_arg_u32_t, _builtin_result_int_t
    ),
    "__builtin_popcountl": _make_builtin_unary_spec(
        "__svm_popcnt8", _builtin_arg_u64_t, _builtin_result_int_t
    ),
    "__builtin_popcountll": _make_builtin_unary_spec(
        "__svm_popcnt8", _builtin_arg_u64_t, _builtin_result_int_t
    ),
    "__builtin_bswap16": _make_builtin_unary_spec(
        "__svm_bswap2", _builtin_arg_u16_t, _builtin_ret_u16_t
    ),
    "__builtin_bswap32": _make_builtin_unary_spec(
        "__svm_bswap4", _builtin_arg_u32_t, _builtin_ret_u32_t
    ),
    "__builtin_bswap64": _make_builtin_unary_spec(
        "__svm_bswap8", _builtin_arg_u64_t, _builtin_ret_u64_t
    ),
    "__builtin_ffs": _make_builtin_unary_spec(
        "__svm_ffs4", _builtin_arg_u32_t, _builtin_result_int_t
    ),
    "__builtin_ffsl": _make_builtin_unary_spec(
        "__svm_ffs8", _builtin_arg_u64_t, _builtin_result_int_t
    ),
    "__builtin_ffsll": _make_builtin_unary_spec(
        "__svm_ffs8", _builtin_arg_u64_t, _builtin_result_int_t
    ),
}

_builtin_void_ptr_t = QualType(QualType.QUAL_PTR, void_t)
_builtin_const_void_ptr_t = QualType(
    QualType.QUAL_PTR, QualType(QualType.QUAL_CONST, void_t)
)
_builtin_char_t = PrimitiveType.from_str_name(["char"])
_builtin_const_char_ptr_t = QualType(
    QualType.QUAL_PTR,
    QualType(QualType.QUAL_CONST, _builtin_char_t),
)

_builtin_forward_specs: Dict[str, _BuiltinForwardSpec] = {
    "__builtin_memcpy": _make_builtin_forward_spec_with_link_types(
        "memcpy",
        [_builtin_void_ptr_t, _builtin_void_ptr_t, size_l_t],
        _builtin_void_ptr_t,
        [_builtin_void_ptr_t, _builtin_const_void_ptr_t, size_l_t],
    ),
    "__builtin_memset": _make_builtin_forward_spec(
        "memset",
        [_builtin_void_ptr_t, _builtin_char_t, size_l_t],
        _builtin_void_ptr_t,
    ),
    "__builtin_strlen": _make_builtin_forward_spec(
        "strlen",
        [_builtin_const_char_ptr_t],
        size_l_t,
    ),
}

_atomic_intrinsic_specs: Dict[str, _AtomicIntrinsicSpec] = {
    "__svm_atomic_load_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_LOAD, 2
    ),
    "__svm_atomic_store_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_STORE, 3
    ),
    "__svm_atomic_exchange_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_XCHG, 3
    ),
    "__svm_atomic_compare_exchange_strong_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_CAS_STRONG, 5
    ),
    "__svm_atomic_fetch_add_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_FADD, 3
    ),
    "__svm_atomic_fetch_sub_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_FSUB, 3
    ),
    "__svm_atomic_fetch_and_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_FAND, 3
    ),
    "__svm_atomic_fetch_or_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_FOR, 3
    ),
    "__svm_atomic_fetch_xor_explicit": _AtomicIntrinsicSpec(
        AtomicIntrinsicExpr.INTRINSIC_FXOR, 3
    ),
}


def _deduce_compound_literal_array_extent(typ, expr):
    if not isinstance(typ, QualType) or typ.qual_id != QualType.QUAL_ARR:
        return
    if typ.ext_inf is not None or expr.lst_expr is None:
        return
    deduced = 0
    next_index = 0
    for elem in expr.lst_expr:
        if isinstance(elem, DesigInitExpr) and elem.kind == DesigInitExpr.KIND_INDEX:
            next_index = elem.designator
        deduced = max(deduced, next_index + 1)
        next_index += 1
    typ.ext_inf = deduced


def _consume_abstract_decl_suffixes(tokens, c, end, context, typ):
    while c < end and tokens[c].type_id == TokenType.BRK_OP and tokens[c].str == "[":
        c += 1
        ext_inf = None
        if tokens[c].str != "]":
            expr, c = get_expr(tokens, c, "]", end, context)
            if not isinstance(expr, LiteralExpr) or expr.t_lit != LiteralExpr.LIT_INT:
                raise ParsingError(tokens, c, "Expected literal integer for bounds of array")
            ext_inf = expr.l_val
        if tokens[c].str != "]":
            raise ParsingError(tokens, c, "Expected closing ']' in abstract declarator")
        c += 1
        typ = QualType(QualType.QUAL_ARR, typ, ext_inf)
    return typ, c


def _parse_builtin_type_arg(tokens, c, end, context, arg_name):
    type_decl, type_c = proc_typed_decl(tokens, c, end, context)
    if type_decl is not None and type_c > c:
        type_decl.typ, type_c = _consume_abstract_decl_suffixes(
            tokens, type_c, end, context, type_decl.typ
        )
    if (
        type_decl is None
        or type_c != end
        or not isinstance(type_decl, IdentifiedQualType)
        or type_decl.name is not None
    ):
        raise ParsingError(
            tokens,
            c,
            "__builtin_types_compatible_p %s must be a type" % arg_name,
        )
    return type_decl.typ


def _find_call_paren_end(tokens, c, end):
    lvl = 1
    while c < end:
        if tokens[c].str in OPEN_GROUPS:
            lvl += 1
        elif tokens[c].str in CLOSE_GROUPS:
            lvl -= 1
            if lvl == 0:
                return c
        c += 1
    raise ParsingError(tokens, end - 1, "Expected ')' to terminate builtin call")


def _build_builtin_unary_expr(name, tokens, c, end, context):
    spec = _builtin_unary_specs[name]
    paren_end = _find_call_paren_end(tokens, c, end)
    expr, c = get_expr(tokens, c, ",", paren_end, context)
    if expr is None:
        raise ParsingError(tokens, c, "%s expects one argument" % name)
    if c != paren_end:
        raise ParsingError(tokens, c, "%s expects exactly one argument" % name)
    converted = get_implicit_conv_expr(expr, spec.arg_type)
    if converted is None:
        raise ParsingError(
            tokens,
            c,
            "%s expects an integer argument convertible to %s"
            % (name, spec.arg_type.to_user_str()),
        )
    expr, _ = converted
    return (
        BuiltinCallExpr(
            name,
            [expr],
            _get_builtin_helper_link_name(
                spec.helper_name,
                [spec.arg_type],
                spec.result_type,
                context,
            ),
            spec.result_type,
        ),
        paren_end + 1,
    )


def _build_builtin_forward_expr(name, tokens, c, end, context):
    spec = _builtin_forward_specs[name]
    paren_end = _find_call_paren_end(tokens, c, end)
    args = []
    while c < paren_end:
        expr, c = get_expr(tokens, c, ",", paren_end, context)
        if expr is None:
            break
        args.append(expr)
        if c < paren_end:
            if tokens[c].str != ",":
                raise ParsingError(tokens, c, "Expected ',' in %s argument list" % name)
            c += 1
    if len(args) != len(spec.arg_types):
        raise ParsingError(
            tokens,
            c,
            "%s expects exactly %u arguments" % (name, len(spec.arg_types)),
        )

    converted_args = []
    for index, (arg, arg_type) in enumerate(zip(args, spec.arg_types), start=1):
        converted = get_implicit_conv_expr(arg, arg_type)
        if converted is None:
            raise ParsingError(
                tokens,
                c,
                "%s argument %u must be convertible to %s"
                % (name, index, arg_type.to_user_str()),
            )
        converted_args.append(converted[0])
    return (
        BuiltinCallExpr(
            name,
            converted_args,
            _get_builtin_helper_link_name(
                spec.helper_name,
                spec.link_arg_types,
                spec.result_type,
                context,
            ),
            spec.result_type,
        ),
        paren_end + 1,
    )


def _unwrap_atomic_const_expr(expr):
    while isinstance(expr, ParenthExpr) and len(expr.lst_expr) == 1:
        expr = expr.lst_expr[0]
    while isinstance(expr, CastOpExpr):
        expr = expr.expr
    return expr


def _parse_atomic_order_expr(name, arg_name, expr, tokens, c):
    expr = _unwrap_atomic_const_expr(expr)
    if not isinstance(expr, LiteralExpr) or expr.t_lit != LiteralExpr.LIT_INT:
        raise ParsingError(
            tokens,
            c,
            "%s %s must be an integer constant memory_order"
            % (name, arg_name),
        )
    order = int(expr.l_val)
    if order < 0 or order > 3:
        raise ParsingError(
            tokens,
            c,
            "%s %s must be between 0 and 3 for StackVM ordering bytes"
            % (name, arg_name),
        )
    return order


def _require_atomic_object_ptr(name, tokens, c, expr, arg_name):
    ptr_type = get_value_type(expr.t_anot)
    if not isinstance(ptr_type, QualType) or ptr_type.qual_id != QualType.QUAL_PTR:
        raise ParsingError(tokens, c, "%s %s must be a pointer" % (name, arg_name))
    if not is_atomic_type(ptr_type.tgt_type):
        raise ParsingError(
            tokens, c, "%s %s must point to an _Atomic-qualified object" % (name, arg_name)
        )
    return ptr_type, get_value_type(ptr_type.tgt_type)


def _require_expected_ptr(name, tokens, c, expr, value_type):
    ptr_type = get_value_type(expr.t_anot)
    if not isinstance(ptr_type, QualType) or ptr_type.qual_id != QualType.QUAL_PTR:
        raise ParsingError(tokens, c, "%s expected argument must be a pointer" % name)
    pointee_type = get_value_type(ptr_type.tgt_type)
    if not compare_no_cvr(pointee_type, value_type):
        raise ParsingError(
            tokens,
            c,
            "%s expected argument must point to %s"
            % (name, value_type.to_user_str()),
        )
    return ptr_type


def _build_atomic_intrinsic_expr(name, tokens, c, end, context):
    spec = _atomic_intrinsic_specs[name]
    paren_end = _find_call_paren_end(tokens, c, end)
    args = []
    while c < paren_end:
        expr, c = get_expr(tokens, c, ",", paren_end, context)
        if expr is None:
            break
        args.append(expr)
        if c < paren_end:
            if tokens[c].str != ",":
                raise ParsingError(tokens, c, "Expected ',' in %s argument list" % name)
            c += 1
    if len(args) != spec.arg_count:
        raise ParsingError(
            tokens,
            c,
            "%s expects exactly %u arguments" % (name, spec.arg_count),
        )

    obj_ptr_type, value_type = _require_atomic_object_ptr(
        name, tokens, c, args[0], "first argument"
    )

    if spec.intrinsic_id == AtomicIntrinsicExpr.INTRINSIC_LOAD:
        order = _parse_atomic_order_expr(name, "second argument", args[1], tokens, c)
        expr = AtomicIntrinsicExpr(spec.intrinsic_id, [args[0]], value_type, order)
        expr.t_anot = value_type
        return expr, paren_end + 1

    if spec.intrinsic_id == AtomicIntrinsicExpr.INTRINSIC_STORE:
        converted = get_implicit_conv_expr(args[1], value_type)
        if converted is None:
            raise ParsingError(
                tokens,
                c,
                "%s second argument must be convertible to %s"
                % (name, value_type.to_user_str()),
            )
        order = _parse_atomic_order_expr(name, "third argument", args[2], tokens, c)
        expr = AtomicIntrinsicExpr(
            spec.intrinsic_id,
            [args[0], converted[0]],
            value_type,
            order,
        )
        expr.t_anot = void_t
        return expr, paren_end + 1

    if spec.intrinsic_id == AtomicIntrinsicExpr.INTRINSIC_CAS_STRONG:
        expected_ptr_type = _require_expected_ptr(name, tokens, c, args[1], value_type)
        converted = get_implicit_conv_expr(args[2], value_type)
        if converted is None:
            raise ParsingError(
                tokens,
                c,
                "%s desired argument must be convertible to %s"
                % (name, value_type.to_user_str()),
            )
        succ = _parse_atomic_order_expr(name, "success order", args[3], tokens, c)
        fail = _parse_atomic_order_expr(name, "failure order", args[4], tokens, c)
        expr = AtomicIntrinsicExpr(
            spec.intrinsic_id,
            [args[0], args[1], converted[0]],
            value_type,
            succ,
            fail,
        )
        expr.t_anot = bool_t
        expr.temps = [expected_ptr_type, value_type]
        return expr, paren_end + 1

    converted = get_implicit_conv_expr(args[1], value_type)
    if converted is None:
        raise ParsingError(
            tokens,
            c,
            "%s second argument must be convertible to %s"
            % (name, value_type.to_user_str()),
        )
    order = _parse_atomic_order_expr(name, "third argument", args[2], tokens, c)
    expr = AtomicIntrinsicExpr(
        spec.intrinsic_id,
        [args[0], converted[0]],
        value_type,
        order,
    )
    expr.t_anot = value_type
    return expr, paren_end + 1


def _build_builtin_expect_expr(tokens, c, end, context):
    paren_end = _find_call_paren_end(tokens, c, end)
    expr, c = get_expr(tokens, c, ",", paren_end, context)
    if expr is None or c >= paren_end or tokens[c].str != ",":
        raise ParsingError(tokens, c, "__builtin_expect expects two arguments")
    c += 1
    hint_expr, c = get_expr(tokens, c, ",", paren_end, context)
    if hint_expr is None or c != paren_end:
        raise ParsingError(tokens, c, "__builtin_expect expects exactly two arguments")
    return expr, paren_end + 1


def _build_builtin_types_compatible_expr(tokens, c, end, context):
    paren_end = _find_call_paren_end(tokens, c, end)
    comma_pos = _find_top_level_call_comma(tokens, c, paren_end)
    if comma_pos is None:
        raise ParsingError(tokens, c, "__builtin_types_compatible_p expects two arguments")
    lhs_type = _parse_builtin_type_arg(tokens, c, comma_pos, context, "first argument")
    rhs_type = _parse_builtin_type_arg(
        tokens, comma_pos + 1, paren_end, context, "second argument"
    )
    value = 1 if compare_no_cvr(lhs_type, rhs_type) else 0
    expr = LiteralExpr(LiteralExpr.LIT_INT, str(value))
    expr.l_val = value
    expr.t_anot = _builtin_result_int_t
    return expr, paren_end + 1


def _find_top_level_call_comma(tokens, c, end):
    lvl = 1
    while c < end:
        if tokens[c].str in OPEN_GROUPS:
            lvl += 1
        elif tokens[c].str in CLOSE_GROUPS:
            lvl -= 1
        elif tokens[c].str == "," and lvl == 1:
            return c
        c += 1
    return None


def _build_builtin_offsetof_expr(tokens, c, end, context):
    paren_end = _find_call_paren_end(tokens, c, end)
    comma_pos = _find_top_level_call_comma(tokens, c, paren_end)
    if comma_pos is None:
        raise ParsingError(tokens, c, "__builtin_offsetof expects two arguments")
    type_decl, type_c = proc_typed_decl(tokens, c, comma_pos, context)
    if type_decl is not None and type_c > c:
        type_decl.typ, type_c = _consume_abstract_decl_suffixes(
            tokens, type_c, comma_pos, context, type_decl.typ
        )
    if type_decl is None or type_c != comma_pos:
        raise ParsingError(tokens, c, "__builtin_offsetof first argument must be a type")
    member_c = comma_pos + 1
    if member_c >= paren_end or tokens[member_c].type_id != TokenType.NAME:
        raise ParsingError(
            tokens, member_c, "__builtin_offsetof second argument must be a member name"
        )
    member_name = tokens[member_c].str
    member_c += 1
    if member_c != paren_end:
        raise ParsingError(
            tokens,
            member_c,
            "__builtin_offsetof currently expects a single member name",
        )
    agg_type = get_value_type(type_decl.typ)
    if not isinstance(agg_type, (ClassType, StructType, UnionType)):
        raise ParsingError(
            tokens,
            c,
            "__builtin_offsetof first argument must name a struct, union, or class type",
        )
    try:
        offset = agg_type.offset_of(member_name)
    except KeyError:
        raise ParsingError(
            tokens,
            comma_pos + 1,
            "Type '%s' has no member '%s'" % (agg_type.to_user_str(), member_name),
        )
    expr = LiteralExpr(LiteralExpr.LIT_INT, str(offset))
    expr.l_val = offset
    expr.t_anot = size_l_t
    return expr, paren_end + 1


def _build_va_intrinsic(name, tokens, c, end, context):
    if name == "va_start":
        ap_expr, c = get_expr(tokens, c, ",", end, context)
        assert tokens[c].str == ",", "va_start expects two arguments"
        c += 1  # skip ','
        last_expr, _c = get_expr(tokens, c, None, end, context)
        from .BaseExpr import ExprType

        rtn = VaIntrinsicExpr(VaIntrinsicExpr.INTRINSIC_VA_START, [ap_expr, last_expr])
        rtn.t_anot = void_t
        return rtn
    elif name == "va_arg":
        ap_expr, c = get_expr(tokens, c, ",", end, context)
        assert tokens[c].str == ",", "va_arg expects two arguments"
        c += 1  # skip ','
        type_decl, _c = proc_typed_decl(tokens, c, end, context)
        assert type_decl is not None, "va_arg: second argument must be a type"
        rtn = VaIntrinsicExpr(
            VaIntrinsicExpr.INTRINSIC_VA_ARG, [ap_expr], arg_type=type_decl.typ
        )
        rtn.t_anot = type_decl.typ
        return rtn
    elif name == "va_end":
        ap_expr, _c = get_expr(tokens, c, None, end, context)
        rtn = VaIntrinsicExpr(VaIntrinsicExpr.INTRINSIC_VA_END, [ap_expr])
        rtn.t_anot = void_t
        return rtn
    elif name == "va_copy":
        dst_expr, c = get_expr(tokens, c, ",", end, context)
        assert tokens[c].str == ",", "va_copy expects two arguments"
        c += 1  # skip ','
        src_expr, _c = get_expr(tokens, c, None, end, context)
        rtn = VaIntrinsicExpr(VaIntrinsicExpr.INTRINSIC_VA_COPY, [dst_expr, src_expr])
        rtn.t_anot = void_t
        return rtn
    else:
        raise ValueError("Unknown va intrinsic: %s" % name)
