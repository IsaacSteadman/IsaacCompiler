# Compare types ignoring [C]onst [V]olatile and [R]egister
def compare_no_cvr(
    type_a: "BaseType", type_b: "BaseType", ignore_ref: bool = False
) -> bool:
    type_a = get_value_type(type_a) if ignore_ref else get_base_prim_type(type_a)
    type_b = get_value_type(type_b) if ignore_ref else get_base_prim_type(type_b)
    while (
        type_a.type_class_id == TypeClass.QUAL
        and type_b.type_class_id == TypeClass.QUAL
    ):
        assert isinstance(type_a, QualType)
        assert isinstance(type_b, QualType)
        if type_a.qual_id != type_b.qual_id:
            return False
        elif type_a.qual_id == QualType.QUAL_FN:
            if len(type_a.ext_inf) != len(type_b.ext_inf):
                return False
            if not compare_no_cvr(type_a.tgt_type, type_b.tgt_type):
                return False
            for c in range(len(type_a.ext_inf)):
                if not compare_no_cvr(type_a.ext_inf[c], type_b.ext_inf[c]):
                    return False
            return True
        elif type_a.qual_id == QualType.QUAL_ARR:
            if type_a.ext_inf is not None and type_b.ext_inf is not None:
                if type_a.ext_inf != type_b.ext_inf:
                    return False
        type_a = get_base_prim_type(type_a.tgt_type)
        type_b = get_base_prim_type(type_b.tgt_type)
    if type_a.type_class_id != type_b.type_class_id:
        return False
    elif type_a.type_class_id == TypeClass.PRIM:
        assert isinstance(type_a, PrimitiveType)
        assert isinstance(type_b, PrimitiveType)
        return type_a.typ == type_b.typ and type_a.sign == type_b.sign
    else:
        assert isinstance(type_a, (EnumType, UnionType, StructType, ClassType))
        assert isinstance(type_b, (EnumType, UnionType, StructType, ClassType))
        assert type_a.parent is not None, "parent should not be None"
        assert type_b.parent is not None, "parent should not be None"
        if type_a.parent is not type_b.parent:
            return False
        elif type_a.name != type_b.name:
            return False
    return True


from .BaseType import BaseType, TypeClass
from .EnumType import EnumType
from .PrimitiveType import PrimitiveType
from .QualType import QualType
from .StructType import StructType
from .UnionType import UnionType
from .ClassType import ClassType
from .get_value_type import get_value_type
from .get_base_prim_type import get_base_prim_type
