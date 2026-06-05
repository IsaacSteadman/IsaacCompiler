def _coerce_const_cast(target_type: "BaseType", value):
    target_value_type = get_value_type(target_type)
    if isinstance(value, StaticAddress):
        if isinstance(target_value_type, QualType) and target_value_type.qual_id in {
            QualType.QUAL_PTR,
            QualType.QUAL_REF,
        }:
            return value
        if (
            isinstance(target_value_type, PrimitiveType)
            and size_of(target_value_type) == 8
        ):
            return value
        return None
    if isinstance(target_value_type, EnumType):
        target_value_type = target_value_type.the_base_type
    if isinstance(target_value_type, PrimitiveType):
        if target_value_type.typ in FLT_TYPE_CODES:
            return float(value)
        if target_value_type.typ == PrimitiveTypeId.TYP_BOOL:
            return 1 if value else 0
        return int(value)
    if isinstance(target_value_type, QualType) and target_value_type.qual_id in {
        QualType.QUAL_PTR,
        QualType.QUAL_REF,
    }:
        return int(value)
    return None


def _c_trunc_div(a: int, b: int) -> int:
    quot = abs(a) // abs(b)
    return -quot if (a < 0) ^ (b < 0) else quot


def _c_trunc_mod(a: int, b: int) -> int:
    return a - _c_trunc_div(a, b) * b


def eval_const_expr(expr: "BaseExpr"):

    if isinstance(expr, LiteralExpr):
        if expr.t_lit == LiteralExpr.LIT_STR:
            return None
        if expr.t_lit == LiteralExpr.LIT_BOOL:
            return 1 if expr.l_val else 0
        return expr.l_val
    if isinstance(expr, ParenthExpr):
        if len(expr.lst_expr) != 1:
            return None
        return eval_const_expr(expr.lst_expr[0])
    if isinstance(expr, CastOpExpr):
        inner_value = eval_const_expr(expr.expr)
        if inner_value is None:
            return None
        return _coerce_const_cast(expr.type_name, inner_value)
    if isinstance(expr, NameRefExpr):
        ctx_var = expr.ctx_var
        if (
            isinstance(ctx_var, ContextVariable)
            and isinstance(ctx_var.parent, EnumType)
            and ctx_var.init_expr is not None
        ):
            return eval_const_expr(ctx_var.init_expr)
        return None
    if isinstance(expr, UnaryOpExpr):
        if expr.type_id == UnaryExprSubType.REFERENCE and isinstance(
            expr.a, NameRefExpr
        ):
            ctx_var = expr.a.ctx_var
            if isinstance(ctx_var, ContextVariable) and ctx_var.has_static_storage():
                return StaticAddress(ctx_var.get_link_name())
            return None
        inner_value = eval_const_expr(expr.a)
        if inner_value is None or isinstance(inner_value, StaticAddress):
            return None
        if expr.type_id == UnaryExprSubType.PLUS:
            return +inner_value
        if expr.type_id == UnaryExprSubType.MINUS:
            return -inner_value
        if expr.type_id == UnaryExprSubType.BIT_NOT:
            return ~int(inner_value)
        if expr.type_id == UnaryExprSubType.BOOL_NOT:
            return 0 if inner_value else 1
        return None
    if isinstance(expr, BinaryOpExpr):
        left_value = eval_const_expr(expr.a)
        right_value = eval_const_expr(expr.b)
        if (
            left_value is None
            or right_value is None
            or isinstance(left_value, StaticAddress)
            or isinstance(right_value, StaticAddress)
        ):
            return None
        if expr.type_id == BinaryExprSubType.PLUS:
            return left_value + right_value
        if expr.type_id == BinaryExprSubType.MINUS:
            return left_value - right_value
        if expr.type_id == BinaryExprSubType.MUL:
            return left_value * right_value
        if expr.type_id == BinaryExprSubType.DIV:
            value_type = get_value_type(expr.t_anot)
            if (
                isinstance(value_type, PrimitiveType)
                and value_type.typ in FLT_TYPE_CODES
            ):
                return left_value / right_value
            return _c_trunc_div(int(left_value), int(right_value))
        if expr.type_id == BinaryExprSubType.MOD:
            return _c_trunc_mod(int(left_value), int(right_value))
        if expr.type_id == BinaryExprSubType.AND:
            return int(left_value) & int(right_value)
        if expr.type_id == BinaryExprSubType.OR:
            return int(left_value) | int(right_value)
        if expr.type_id == BinaryExprSubType.XOR:
            return int(left_value) ^ int(right_value)
        if expr.type_id == BinaryExprSubType.LSHIFT:
            return int(left_value) << int(right_value)
        if expr.type_id == BinaryExprSubType.RSHIFT:
            return int(left_value) >> int(right_value)
        if expr.type_id == BinaryExprSubType.LT:
            return int(left_value < right_value)
        if expr.type_id == BinaryExprSubType.GT:
            return int(left_value > right_value)
        if expr.type_id == BinaryExprSubType.LE:
            return int(left_value <= right_value)
        if expr.type_id == BinaryExprSubType.GE:
            return int(left_value >= right_value)
        if expr.type_id == BinaryExprSubType.EQ:
            return int(left_value == right_value)
        if expr.type_id == BinaryExprSubType.NE:
            return int(left_value != right_value)
        if expr.type_id == BinaryExprSubType.SS_AND:
            return int(bool(left_value) and bool(right_value))
        if expr.type_id == BinaryExprSubType.SS_OR:
            return int(bool(left_value) or bool(right_value))
    return None


from ..expr.BinaryOpExpr import BinaryExprSubType, BinaryOpExpr
from ..expr.NameRefExpr import NameRefExpr
from ..expr.ParenthExpr import ParenthExpr
from ..expr.UnaryOpExpr import UnaryExprSubType, UnaryOpExpr
from ..expr.CastOpExpr import CastOpExpr
from ..expr.LiteralExpr import LiteralExpr
from .ContextVariable import ContextVariable
from .EnumType import EnumType
from .PrimitiveType import PrimitiveType
from .StaticAddress import StaticAddress
from .QualType import QualType
from .BaseType import BaseType
from .PrimitiveType import PrimitiveTypeId, FLT_TYPE_CODES
from ..expr.BaseExpr import BaseExpr
from .qual_atomic_type_util import get_value_type
from .align_size_of import size_of
