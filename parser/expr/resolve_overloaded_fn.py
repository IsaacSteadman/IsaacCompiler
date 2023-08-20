from typing import List, Optional, Tuple


def resolve_overloaded_fn(call_expr: "FnCallExpr"):
    fn = call_expr.fn
    if fn.expr_id != ExprType.NAME:
        raise ValueError("Only named functions are directly referable")
    assert isinstance(fn, NameRefExpr)
    lst_args = call_expr.lst_args
    n_args = len(lst_args)
    ctx_var = fn.ctx_var
    lst_fns: List[ContextVariable] = [ctx_var]
    if ctx_var.typ.type_class_id == TypeClass.MULTI:
        assert isinstance(ctx_var, OverloadedCtxVar)
        lst_fns = ctx_var.specific_ctx_vars
    lst_viable: List[Optional[Tuple[ContextVariable, List[Tuple[BaseExpr, int]]]]] = [
        None
    ] * len(lst_fns)
    for c, TryFn in enumerate(lst_fns):
        typ = TryFn.typ
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
            conv_expr = get_implicit_conv_expr(
                lst_args[c1], get_actual_type(typ.ext_inf[c1])
            )
            if conv_expr is None:
                break
            lst_conv[c1] = conv_expr
            c1 += 1
        if c1 < n_type:
            if OVERLOAD_VERBOSE:
                print("NOT_VIABLE: %r, %r" % (TryFn, lst_conv))
            continue
        while c1 < n_args:
            conv_expr = get_ellipses_conv_expr(lst_args[c1])
            if conv_expr is None:
                break
            lst_conv[c1] = conv_expr
            c1 += 1
        if c1 >= n_args:
            lst_viable[c] = (TryFn, lst_conv)
        else:
            if OVERLOAD_VERBOSE:
                print("NOT_VIABLE: %r, %r" % (TryFn, lst_conv))
    best_entry: Optional[Tuple[ContextVariable, List[Tuple[BaseExpr, int]]]] = None
    if OVERLOAD_VERBOSE:
        print("OVERLOAD-RESOLUTION: lst_viable = %r" % lst_viable)
    last_ambiguous = None
    for c, Entry in enumerate(lst_viable):
        if Entry is None:
            continue
        if best_entry is None:
            best_entry = Entry
            continue
        best_fn, best_lst_conv = best_entry
        cur_fn, lst_conv = Entry
        if len(lst_conv) != len(best_lst_conv):
            raise ValueError(
                "Inconsistent length %u and %u for lst_conv = %r, best_lst_conv = %r"
                % (len(lst_conv), len(best_lst_conv), lst_conv, best_lst_conv)
            )
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
            last_ambiguous = Entry
        elif status == 2:
            best_entry = Entry
            last_ambiguous = None
    if last_ambiguous is not None:
        raise ValueError(
            "Resolution of Overloaded function '%s' is Ambiguous: %r AND %r"
            % (fn.name, best_entry, last_ambiguous)
        )
    if best_entry is None:
        raise ValueError("Could not resolve overloaded function call: %r" % call_expr)
    fn_var, lst_conv = best_entry
    new_lst_args: List[Optional[BaseExpr]] = [None] * len(lst_conv)
    for c in range(len(lst_conv)):
        new_lst_args[c] = lst_conv[c][0]
    call_expr.lst_args = new_lst_args
    fn.ctx_var = fn_var
    fn.t_anot = QualType(QualType.QUAL_REF, fn.ctx_var.typ)


from .BaseExpr import BaseExpr, ExprType
from .FnCallExpr import FnCallExpr
from .NameRefExpr import NameRefExpr
from .expr_constants import OVERLOAD_VERBOSE
from .get_ellipses_conv_expr import get_ellipses_conv_expr
from .get_implicit_conv_expr import get_implicit_conv_expr
from ..type.BaseType import TypeClass
from ..type.get_actual_type import get_actual_type
from ..type.is_default import is_default
from ..type.types import QualType, ContextVariable, OverloadedCtxVar
