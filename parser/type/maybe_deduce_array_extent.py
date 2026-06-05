from typing import List, Union, Optional


def _deduce_array_extent_from_init(
    arr_type: "QualType", init_args: List[Union["BaseExpr", "CurlyStmnt"]]
) -> Optional[int]:
    if arr_type.ext_inf is not None or len(init_args) != 1:
        return arr_type.ext_inf
    expr = init_args[0]
    if isinstance(expr, LiteralExpr) and expr.t_lit == LiteralExpr.LIT_STR:
        return len(expr.l_val) + 1
    if isinstance(expr, CurlyExpr) and expr.lst_expr is not None:
        deduced = 0
        next_index = 0
        for elem in expr.lst_expr:
            if (
                isinstance(elem, DesigInitExpr)
                and elem.kind == DesigInitExpr.KIND_INDEX
            ):
                next_index = elem.designator
            deduced = max(deduced, next_index + 1)
            next_index += 1
        return deduced
    return None


def maybe_deduce_array_extent(
    decl_type: "BaseType", init_args: List[Union["BaseExpr", "CurlyStmnt"]]
) -> None:
    if isinstance(decl_type, QualType) and decl_type.qual_id == QualType.QUAL_ARR:
        deduced = _deduce_array_extent_from_init(decl_type, init_args)
        if deduced is not None:
            decl_type.ext_inf = deduced


from .QualType import QualType
from .BaseType import BaseType
from ..stmnt.CurlyStmnt import CurlyStmnt
from ..expr.BaseExpr import BaseExpr
from ..expr.LiteralExpr import LiteralExpr
from ..expr.CurlyExpr import CurlyExpr
from ..expr.DesigInitExpr import DesigInitExpr
