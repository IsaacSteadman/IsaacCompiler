def get_bool_expr(cond: "BaseExpr"):
    if cond.t_anot is not None:
        to_type = bool_t
        res = get_implicit_conv_expr(cond, to_type)
        if res is None:
            raise TypeError("Expected boolean expression got \n  %s\n  with type: %s" % (
                format_pretty(cond).replace("\n", "\n  "), get_user_str_from_type(cond.t_anot)
            ))
        cond, rank = res
        if not compare_no_cvr(cond.t_anot, to_type):
            raise TypeError("Expected boolean expression")
    return cond


from .BaseExpr import BaseExpr
from .get_implicit_conv_expr import get_implicit_conv_expr
from ...PrettyRepr import format_pretty
from ..type.PrimitiveType import bool_t
from ..type.compare_no_cvr import compare_no_cvr
from ..type.get_user_str_from_type import get_user_str_from_type