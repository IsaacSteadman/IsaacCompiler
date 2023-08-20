from ..expr.expr_constants import ExprType
from ..expr.BaseExpr import BaseExpr
from ...PrettyRepr import get_pretty_repr


class DeclVarExpr(BaseExpr):
    expr_id = ExprType.DECL_VAR

    def __init__(self, typ):
        self.t_anot = typ

    def pretty_repr(self, pretty_repr_ctx=None):
        return (
            [self.__class__.__name__, "("]
            + get_pretty_repr(self.t_anot, pretty_repr_ctx)
            + [")"]
        )
