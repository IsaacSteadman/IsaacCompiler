from typing import List

from .BaseExpr import BaseExpr, ExprType


class PerCpuAddrExpr(BaseExpr):
    expr_id = ExprType.PERCPU_ADDR

    def __init__(self, arg: BaseExpr, result_type: "BaseType"):
        self.arg = arg
        self.t_anot = result_type

    def init_temps(self, main_temps):
        main_temps = super(PerCpuAddrExpr, self).init_temps(main_temps)
        return self.arg.init_temps(main_temps)

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr((self.arg,), pretty_repr_ctx)

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on PerCpuAddrExpr")


from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import BaseType
from ..type.CompileContext import CompileContext
from ...lexer.lexer import Token
