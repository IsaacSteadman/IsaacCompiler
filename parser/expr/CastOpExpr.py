from enum import Enum
from typing import List
from .BaseExpr import BaseExpr, ExprType


class CastType(Enum):
    PROMOTION = 0
    IMPLICIT = 1
    EXPLICIT = 2


class CastOpExpr(BaseExpr):
    expr_id = ExprType.CAST

    def __init__(
        self,
        type_name: "BaseType",
        expr: BaseExpr,
        cast_type: CastType = CastType.EXPLICIT,
    ):
        assert expr.t_anot is not None, repr(expr)
        src_pt, src_vt, is_src_ref = get_tgt_ref_type(expr.t_anot)
        tgt_pt, tgt_vt, is_tgt_ref = get_tgt_ref_type(type_name)
        self.type_name = type_name
        self.expr = expr
        if compare_no_cvr(src_vt, tgt_vt) and (not is_src_ref) and is_tgt_ref:
            self.temps = [tgt_vt]
        self.cast_type = cast_type
        self.t_anot = type_name

    def init_temps(self, main_temps):
        # NOTE: figure out why temp_links is inconsistent between compile-time and parse-time
        main_temps = super(CastOpExpr, self).init_temps(main_temps)
        res = self.expr.init_temps(main_temps)
        assert (
            self.temps is self.expr.temps
        ), "self.temps = %r, self.expr.temps = %r" % (self.temps, self.expr.temps)
        return res

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on C-Style Cast operator")

    def pretty_repr(self, pretty_repr_ctx=None):
        rtn = [self.__class__.__name__] + get_pretty_repr(
            (self.type_name, self.expr), pretty_repr_ctx
        )
        if self.cast_type != CastType.EXPLICIT:
            rtn[-1:-1] = [",", "CastType", ".", self.cast_type.name]
        return rtn


from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import BaseType
from ..type.types import CompileContext, compare_no_cvr, get_tgt_ref_type
from ...lexer.lexer import Token
