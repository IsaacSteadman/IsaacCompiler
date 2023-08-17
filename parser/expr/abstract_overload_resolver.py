from typing import List, Optional, Tuple


def abstract_overload_resolver(
    lst_args: List["BaseExpr"],
    fn_types: List["BaseType"]
) -> Tuple[int, Optional[List["BaseExpr"]]]:
    n_args = len(lst_args)
    lst_viable: List[Optional[Tuple[BaseType, Optional[List[Tuple[BaseExpr, int]]]]]] = [None] * len(fn_types)
    for c, typ in enumerate(fn_types):
        assert typ.type_class_id == TypeClass.QUAL
        assert isinstance(typ, QualType)
        assert typ.qual_id == QualType.QUAL_FN
        variadic = False
        assert typ.ext_inf is not None
        assert not isinstance(typ.ext_inf, int)
        n_type = len(typ.ext_inf)
        viable = False
        if n_type == n_args:
            viable = True
        elif n_type < n_args and variadic:
            viable = True
        elif n_type > n_args:
            c1 = n_args
            while c1 < n_type:
                if not is_default(typ.ext_inf[c1]):
                    break
                c1 += 1
            if c1 >= n_type:
                viable = True
        if not viable:
            continue
        c1 = 0
        lst_conv: List[Optional[Tuple[BaseExpr, int]]] = [None] * n_args
        while c1 < n_type:
            conv_expr = get_implicit_conv_expr(lst_args[c1], get_actual_type(typ.ext_inf[c1]))
            if conv_expr is None:
                break
            lst_conv[c1] = conv_expr
            c1 += 1
        if c1 < n_type:
            if OVERLOAD_VERBOSE:
                print("NOT_VIABLE: %r, %r" % (typ, lst_conv))
            continue
        while c1 < n_args:
            conv_expr = get_ellipses_conv_expr(lst_args[c1])
            if conv_expr is None:
                break
            lst_conv[c1] = conv_expr
            c1 += 1
        if c1 >= n_args:
            lst_viable[c] = (typ, lst_conv)
        else:
            if OVERLOAD_VERBOSE:
                print("NOT_VIABLE: %r, %r" % (typ, lst_conv))
    if OVERLOAD_VERBOSE:
        print("OVERLOAD-RESOLUTION: lst_viable = %r" % lst_viable)
    best_entry: Optional[Tuple[int, List[Tuple[BaseExpr, int]]]] = None
    last_ambiguous = None
    for c, entry in enumerate(lst_viable):
        if entry is None:
            continue
        if best_entry is None:
            best_entry = c, entry[1]
            continue
        best_c, best_lst_conv = best_entry
        cur_fn, lst_conv = entry
        if len(lst_conv) != len(best_lst_conv):
            raise ValueError(
                "Inconsistent length %u and %u for lst_conv = %r, best_lst_conv = %r" % (
                    len(lst_conv), len(best_lst_conv), lst_conv, best_lst_conv))
        status = 0  # 0 is ambiguous, 1 is eliminated, 2 is promoted
        for c1 in range(len(lst_conv)):
            a = lst_conv[c1]
            b = best_lst_conv[c1]
            if a[1] < b[1]:
                status = 2
                break
            elif a[1] > b[1]:
                status = 1
                break
        if status == 0:
            last_ambiguous = (c, entry[1])
        elif status == 2:
            last_ambiguous = None
            best_entry = c, entry[1]
    if last_ambiguous is not None:
        raise ValueError(
            "Resolution of Overloaded function is Ambiguous: %r AND %r" % (best_entry, last_ambiguous))
    if best_entry is None:
        return len(fn_types), None  # TODO: find better error code
    else:
        return best_entry[0], [expr for expr, priority in best_entry[1]]


from .BaseExpr import BaseExpr
from .expr_constants import OVERLOAD_VERBOSE
from .get_ellipses_conv_expr import get_ellipses_conv_expr
from .get_implicit_conv_expr import get_implicit_conv_expr
from ..type.BaseType import BaseType, TypeClass
from ..type.QualType import QualType
from ..type.get_actual_type import get_actual_type
from ..type.is_default import is_default