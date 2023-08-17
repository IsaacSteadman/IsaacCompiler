from typing import Tuple


def get_tgt_ref_type(typ: "BaseType") -> Tuple["BaseType", "BaseType", bool]:
    """
    returns primitive type, v value type, is reference
    """
    vt = pt = get_base_prim_type(typ)
    is_ref = False
    if pt.type_class_id == TypeClass.QUAL:
        assert isinstance(pt, QualType)
        if pt.qual_id == QualType.QUAL_REF:
            is_ref = True
            vt = get_base_prim_type(pt.tgt_type)
    return pt, vt, is_ref


from .BaseType import BaseType, TypeClass
from .QualType import QualType
from .get_base_prim_type import get_base_prim_type