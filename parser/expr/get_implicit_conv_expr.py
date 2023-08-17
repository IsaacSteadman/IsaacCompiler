from typing import Optional, Tuple


def get_implicit_conv_expr(expr: "BaseExpr", to_type: "BaseType") -> Optional[Tuple["BaseExpr", int]]:
    """
    Rating is
      0 if conversion could not be done
      1 if no conversion necessary
      2 if exact match rank done
      3 if promotion rank done
      4 if conversion rank done
      5 if conversion is user defined
      6 if conversion is ellipses
    """
    res1 = get_standard_conv_expr(expr, to_type)
    if res1 is None:
        if OVERLOAD_VERBOSE:
            print("First Conversion failed")
        return None
    expr1, rate1 = res1
    res2 = get_user_def_conv_expr(expr1, to_type)
    if res2 is None:
        if OVERLOAD_VERBOSE:
            print("Middle Conversion failed")
        return None
    expr2, rate2 = res2
    res3 = get_standard_conv_expr(expr2, to_type)
    if res3 is None:
        if OVERLOAD_VERBOSE:
            print("Last Conversion failed")
        return None
    expr3, rate3 = res3
    if rate3 == 0:
        if OVERLOAD_VERBOSE:
            print("Last Conversion failed id")
        return None
    if expr3.t_anot is not to_type and not compare_no_cvr(expr3.t_anot, to_type):
        if OVERLOAD_VERBOSE:
            print("Conversion attempt failed, got expr3.t_anot = %s\n  to_type = %s" % (repr(expr3.t_anot), repr(to_type)))
        return None
    return expr3, max([rate1, rate2, rate3])


from .BaseExpr import BaseExpr
from .expr_constants import OVERLOAD_VERBOSE
from .get_standard_conv_expr import get_standard_conv_expr
from .get_user_def_conv_expr import get_user_def_conv_expr
from ..type.BaseType import BaseType
from ..type.compare_no_cvr import compare_no_cvr
