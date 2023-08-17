from typing import Optional, Tuple


def get_user_def_conv_expr(
    expr: "BaseExpr", to_type: "BaseType"
) -> Optional[Tuple["BaseExpr", int]]:
    src_pt = get_base_prim_type(expr.t_anot)
    tgt_pt = get_base_prim_type(to_type)
    if tgt_pt.type_class_id in [TypeClass.CLASS, TypeClass.STRUCT, TypeClass.UNION]:
        assert isinstance(tgt_pt, (StructType, ClassType, UnionType))
        raise NotImplementedError("Not Implemented")
    elif src_pt.type_class_id in [TypeClass.CLASS, TypeClass.STRUCT, TypeClass.UNION]:
        assert isinstance(src_pt, (StructType, ClassType, UnionType))
        raise NotImplementedError("Not Implemented")
    elif tgt_pt.type_class_id == TypeClass.QUAL:
        assert isinstance(tgt_pt, QualType)
        if tgt_pt.qual_id == QualType.QUAL_REF:
            tgt_pt1 = tgt_pt.tgt_type
            if tgt_pt1.type_class_id in [
                TypeClass.CLASS,
                TypeClass.STRUCT,
                TypeClass.UNION,
            ]:
                assert isinstance(tgt_pt1, (StructType, ClassType, UnionType))
                if not compare_no_cvr(src_pt, tgt_pt):
                    raise NotImplementedError(
                        "Not Implemented: %s -> %s"
                        % (
                            get_user_str_from_type(expr.t_anot),
                            get_user_str_from_type(to_type),
                        )
                    )
    elif src_pt.type_class_id == TypeClass.QUAL:
        assert isinstance(src_pt, QualType)
        if src_pt.qual_id == QualType.QUAL_REF:
            src_pt1 = src_pt.tgt_type
            if src_pt1.type_class_id in [
                TypeClass.CLASS,
                TypeClass.STRUCT,
                TypeClass.UNION,
            ]:
                assert isinstance(src_pt1, (StructType, ClassType, UnionType))
                raise NotImplementedError("Not Implemented")
    return expr, 1


from .BaseExpr import BaseExpr
from ..type.BaseType import TypeClass
from ..type.QualType import QualType
from ..type.BaseType import BaseType
from ..type.StructType import StructType
from ..type.ClassType import ClassType
from ..type.UnionType import UnionType
from ..type.get_base_prim_type import get_base_prim_type
from ..type.compare_no_cvr import compare_no_cvr
from ..type.get_user_str_from_type import get_user_str_from_type
