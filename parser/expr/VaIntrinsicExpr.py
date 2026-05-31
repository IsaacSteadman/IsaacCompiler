from typing import List, Optional
from .BaseExpr import BaseExpr, ExprType


class VaIntrinsicExpr(BaseExpr):
    """AST node for va_start / va_arg / va_end / va_copy compiler intrinsics."""

    expr_id = ExprType.VA_INTRINSIC

    INTRINSIC_VA_START = 0  # va_start(ap, last)
    INTRINSIC_VA_ARG = 1  # va_arg(ap, T)
    INTRINSIC_VA_END = 2  # va_end(ap)
    INTRINSIC_VA_COPY = 3  # va_copy(dst, src)

    _NAMES = ["va_start", "va_arg", "va_end", "va_copy"]

    def __init__(
        self,
        intrinsic_id: int,
        args: List[BaseExpr],
        arg_type: Optional["BaseType"] = None,
    ):
        self.intrinsic_id = intrinsic_id
        self.args = args
        # arg_type is only used by va_arg: the type T to read from the va_list
        self.arg_type = arg_type

    def pretty_repr(self, pretty_repr_ctx=None):
        from ...PrettyRepr import get_pretty_repr

        return (
            [self.__class__.__name__, "(", self._NAMES[self.intrinsic_id], ","]
            + get_pretty_repr(self.args, pretty_repr_ctx)
            + [")"]
        )
