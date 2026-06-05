from typing import List
from .BaseExpr import BaseExpr, ExprType


class BuiltinCallExpr(BaseExpr):
    expr_id = ExprType.BUILTIN_CALL

    def __init__(
        self,
        builtin_name: str,
        args: List[BaseExpr],
        helper_link_name: str,
        result_type: "BaseType",
    ):
        self.builtin_name = builtin_name
        self.args = args
        self.helper_link_name = helper_link_name
        self.t_anot = result_type

    def init_temps(self, main_temps):
        main_temps = super(BuiltinCallExpr, self).init_temps(main_temps)
        for expr in self.args:
            main_temps = expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.builtin_name, self.args, self.helper_link_name), pretty_repr_ctx
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on BuiltinCallExpr")


from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import BaseType
from ..type.CompileContext import CompileContext
from ...lexer.lexer import Token
