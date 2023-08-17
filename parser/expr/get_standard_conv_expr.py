from typing import Optional, Tuple


def get_standard_conv_expr(
    expr: "BaseExpr", to_type: "BaseType"
) -> Optional[Tuple["BaseExpr", int]]:
    """
    returns None if conversion invalid
    returns (expr, 0) if conversion could not be done
    returns (expr, 1) if no conversion necessary
    returns (new expr, 2) if exact match rank done
    returns (new expr, 3) if promotion rank done
    returns (new expr, 4) if conversion rank done
    """
    src_pt, src_vt, is_src_ref = get_tgt_ref_type(expr.t_anot)
    tgt_pt, tgt_vt, is_tgt_ref = get_tgt_ref_type(to_type)
    if compare_no_cvr(src_vt, tgt_vt):
        if is_tgt_ref ^ is_src_ref:
            return CastOpExpr(to_type, expr, CastType.IMPLICIT), 2
        return expr, 1
    elif is_src_ref and not is_tgt_ref and is_prim_or_ptr(src_vt):
        return CastOpExpr(src_vt, expr, CastType.IMPLICIT), 4
    if (
        src_vt.type_class_id == TypeClass.PRIM
        and tgt_vt.type_class_id == TypeClass.PRIM
    ):
        assert isinstance(src_vt, PrimitiveType)
        assert isinstance(tgt_vt, PrimitiveType)
        if src_vt.typ != tgt_vt.typ:
            if is_src_ref:
                return CastOpExpr(src_vt, expr, CastType.IMPLICIT), 2
            rtn = CastOpExpr(tgt_vt, expr, CastType.IMPLICIT)
            if tgt_vt.size > src_vt.size:
                if tgt_vt.typ in INT_TYPE_CODES and src_vt.typ in INT_TYPE_CODES:
                    if tgt_vt.typ == PrimitiveTypeId.INT_I:
                        return rtn, 3
                elif tgt_vt.typ in FLT_TYPE_CODES and src_vt.typ in FLT_TYPE_CODES:
                    if tgt_vt.typ == PrimitiveTypeId.FLT_D:
                        return rtn, 3
            return rtn, 4
        return expr, 1
    if (
        src_vt.type_class_id == TypeClass.QUAL
        and tgt_vt.type_class_id == TypeClass.QUAL
    ):
        assert isinstance(src_vt, QualType)
        assert isinstance(tgt_vt, QualType)
        if tgt_vt.qual_id == QualType.QUAL_PTR:
            if src_vt.qual_id == QualType.QUAL_PTR or (
                OVERLOAD_BAN_ARR_VAL
                and src_vt.qual_id == QualType.QUAL_ARR
                and src_vt.ext_inf is None
            ):
                if is_src_ref and is_tgt_ref:
                    return None
                elif is_src_ref:
                    return CastOpExpr(src_vt, expr, CastType.IMPLICIT), 2
                if compare_no_cvr(src_vt.tgt_type, tgt_vt.tgt_type):
                    if compare_no_cvr(src_vt, tgt_vt):
                        return expr, 1
                    else:
                        return CastOpExpr(tgt_vt, expr, CastType.IMPLICIT), 2
                elif is_prim_type_id(tgt_vt.tgt_type, PrimitiveTypeId.TYP_VOID):
                    return CastOpExpr(tgt_vt, expr, CastType.IMPLICIT), 4
                if OVERLOAD_VERBOSE:
                    print("REASON: src_vt Pointer General")
                return None
            elif src_vt.qual_id == QualType.QUAL_FN:
                if not is_src_ref:
                    if OVERLOAD_VERBOSE:
                        print("REASON: Cannot cast function value")
                    return None
                if is_prim_type_id(tgt_vt.tgt_type, PrimitiveTypeId.TYP_VOID):
                    return (
                        CastOpExpr(
                            QualType(QualType.QUAL_PTR, src_vt), expr, CastType.IMPLICIT
                        ),
                        2,
                    )
                elif compare_no_cvr(src_vt, tgt_vt.tgt_type):
                    return CastOpExpr(tgt_vt, expr, CastType.IMPLICIT), 2
                if OVERLOAD_VERBOSE:
                    print("REASON: src_vt Function General")
                return None
            elif src_vt.qual_id == QualType.QUAL_ARR:
                if OVERLOAD_BAN_ARR_VAL and not is_src_ref:
                    if OVERLOAD_VERBOSE:
                        print("REASON: src_pt is not a reference to array")
                    return None
                if compare_no_cvr(src_vt.tgt_type, tgt_vt.tgt_type):
                    return CastOpExpr(tgt_vt, expr, CastType.IMPLICIT), 2
                elif is_prim_type_id(tgt_vt.tgt_type, PrimitiveTypeId.TYP_VOID):
                    return (
                        CastOpExpr(
                            QualType(QualType.QUAL_PTR, src_vt.tgt_type),
                            expr,
                            CastType.IMPLICIT,
                        ),
                        2,
                    )
                if OVERLOAD_VERBOSE:
                    print("REASON: src_vt Array General")
                return None
            if OVERLOAD_VERBOSE:
                print("REASON: tgt_vt Pointer General")
        return None
    if OVERLOAD_VERBOSE:
        print(
            "REASON: Unhandled Type conversion encountered %r -> %r"
            % (expr.t_anot, to_type)
        )
    return None


from .expr_constants import OVERLOAD_VERBOSE, OVERLOAD_BAN_ARR_VAL
from .BaseExpr import BaseExpr
from .CastOpExpr import CastOpExpr
from ..type.BaseType import BaseType
