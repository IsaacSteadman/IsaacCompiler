from typing import List
from .BaseExpr import BaseExpr, ExprType


class InlineIfExpr(BaseExpr):
    expr_id = ExprType.INLINE_IF

    def __init__(self, cond: BaseExpr, if_true: BaseExpr, if_false: BaseExpr):
        self.cond = cond
        self.if_true = if_true
        self.if_false = if_false

    def init_temps(self, main_temps):
        main_temps = super(InlineIfExpr, self).init_temps(main_temps)
        main_temps = self.cond.init_temps(main_temps)
        main_temps = self.if_true.init_temps(main_temps)
        main_temps = self.if_false.init_temps(main_temps)
        return main_temps

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.cond, self.if_true, self.if_false)
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on InlineIfExpr")


from ..context.CompileContext import CompileContext
from ...PrettyRepr import get_pretty_repr
from ..context.CompileContext import CompileContext
from ...lexer.lexer import Token
