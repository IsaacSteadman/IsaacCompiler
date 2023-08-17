from typing import List
from .BaseExpr import BaseExpr, ExprType


class ParenthExpr(BaseExpr):
    expr_id = ExprType.PARENTH

    def __init__(self, lst_expr: List[BaseExpr]):
        self.lst_expr = lst_expr
        if len(self.lst_expr):
            self.t_anot = self.lst_expr[-1].t_anot

    def init_temps(self, main_temps):
        main_temps = super(ParenthExpr, self).init_temps(main_temps)
        for expr in self.lst_expr:
            main_temps = expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.lst_expr) + [")"]

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on ParenthExpr")


from ..context.CompileContext import CompileContext
from ...PrettyRepr import get_pretty_repr
from ..context.CompileContext import CompileContext
from ...lexer.lexer import Token
