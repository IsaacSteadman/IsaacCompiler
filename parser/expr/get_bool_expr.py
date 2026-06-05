def get_bool_expr(cond: "BaseExpr"):
    if cond.t_anot is not None:
        to_type = bool_t
        res = get_implicit_conv_expr(cond, to_type)
        if res is None:
            # Try pointer-to-bool contextual conversion (not in general overload resolution)
            src_pt, src_vt, is_src_ref = get_tgt_ref_type(cond.t_anot)
            if (
                src_vt.type_class_id == TypeClass.QUAL
                and isinstance(src_vt, QualType)
                and src_vt.qual_id == QualType.QUAL_PTR
            ):
                expr = (
                    CastOpExpr(src_vt, cond, CastType.IMPLICIT) if is_src_ref else cond
                )
                cond = CastOpExpr(to_type, expr, CastType.IMPLICIT)
                cond.init_temps(None)
                return cond
            raise TypeError(
                "Expected boolean expression got \n  %s\n  with type: %s"
                % (
                    format_pretty(cond).replace("\n", "\n  "),
                    get_user_str_from_type(cond.t_anot),
                )
            )
        cond, rank = res
        if not compare_no_cvr(cond.t_anot, to_type):
            raise TypeError("Expected boolean expression")
    return cond


from .BaseExpr import BaseExpr
from .CastOpExpr import CastOpExpr, CastType
from .get_implicit_conv_expr import get_implicit_conv_expr
from ...PrettyRepr import format_pretty
from ..type.BaseType import TypeClass
from ..type.get_user_str_from_type import get_user_str_from_type
from ..type.QualType import QualType
from ..type.PrimitiveType import bool_t
from ..type.qual_atomic_type_util import compare_no_cvr, get_tgt_ref_type
