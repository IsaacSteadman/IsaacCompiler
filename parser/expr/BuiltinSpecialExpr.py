from typing import List, Optional

from .BaseExpr import BaseExpr, ExprType


class BuiltinSpecialExpr(BaseExpr):
    expr_id = ExprType.BUILTIN_SPECIAL

    KIND_TRAP = 0
    KIND_UNREACHABLE = 1
    KIND_ALLOCA = 2
    KIND_RETURN_ADDRESS = 3
    KIND_FRAME_ADDRESS = 4
    KIND_PREFETCH = 5
    KIND_COMPLEX = 6

    def __init__(
        self,
        builtin_name: str,
        kind: int,
        args: List[BaseExpr],
        result_type: "BaseType",
        int_value: Optional[int] = None,
    ):
        self.builtin_name = builtin_name
        self.kind = kind
        self.args = args
        self.int_value = int_value
        self.t_anot = result_type

    def init_temps(self, main_temps):
        main_temps = super(BuiltinSpecialExpr, self).init_temps(main_temps)
        for expr in self.args:
            main_temps = expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.builtin_name, self.kind, self.args, self.int_value),
            pretty_repr_ctx,
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on BuiltinSpecialExpr")


from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import BaseType
from ..type.CompileContext import CompileContext
from ...lexer.lexer import Token
