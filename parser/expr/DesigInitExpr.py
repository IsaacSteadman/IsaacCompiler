from typing import Optional, Union
from .BaseExpr import BaseExpr, ExprType
from ...PrettyRepr import get_pretty_repr


class DesigInitExpr(BaseExpr):
    """
    A single element in a designated initialiser list, e.g.::

        .field_name = expr   →  kind=KIND_FIELD, designator='field_name'
        [3]         = expr   →  kind=KIND_INDEX, designator=3
    """

    expr_id = ExprType.DESIG_INIT

    KIND_FIELD = "field"
    KIND_INDEX = "index"

    def __init__(
        self,
        kind: str,
        designator: Union[str, int],
        expr: Optional[BaseExpr] = None,
    ):
        self.kind = kind  # KIND_FIELD or KIND_INDEX
        self.designator = designator  # str for struct field, int for array index
        self.expr = expr  # the RHS expression

    def init_temps(self, main_temps):
        main_temps = super(DesigInitExpr, self).init_temps(main_temps)
        if self.expr is not None:
            main_temps = self.expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self, pretty_repr_ctx=None):
        if self.kind == self.KIND_FIELD:
            prefix = [".%s" % self.designator, "="]
        else:
            prefix = ["[%d]" % self.designator, "="]
        return (
            [self.__class__.__name__, "("]
            + prefix
            + get_pretty_repr(self.expr, pretty_repr_ctx)
            + [")"]
        )
