from ...PrettyRepr import get_pretty_repr
from .BaseExpr import BaseExpr, ExprType
from ..type.types import QualType


class CompoundLiteralExpr(BaseExpr):
    expr_id = ExprType.COMPOUND_LITERAL

    def __init__(self, obj_type, init_expr):
        self.obj_type = obj_type
        self.init_expr = init_expr
        self.t_anot = QualType(QualType.QUAL_REF, self.obj_type)
        self.temps = [self.obj_type]

    def init_temps(self, main_temps):
        main_temps = super(CompoundLiteralExpr, self).init_temps(main_temps)
        return self.init_expr.init_temps(main_temps)

    def pretty_repr(self, pretty_repr_ctx=None):
        return (
            [self.__class__.__name__, "("]
            + get_pretty_repr((self.obj_type, self.init_expr), pretty_repr_ctx)
            + [")"]
        )
