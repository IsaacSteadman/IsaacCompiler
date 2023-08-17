from typing import Union


def get_base_prim_type(typ: Union["BaseType", "IdentifiedQualType"]) -> "BaseType":
    assert typ is not None
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    base_comp_types = {
        QualType.QUAL_FN,
        QualType.QUAL_PTR,
        QualType.QUAL_ARR,
        QualType.QUAL_REF,
    }
    pass_thru_types = {
        QualType.QUAL_REG,
        QualType.QUAL_CONST,
        QualType.QUAL_DEF,
        QualType.QUAL_VOLATILE,
    }
    if typ.type_class_id == TypeClass.PRIM:
        assert isinstance(typ, PrimitiveType)
        return typ
    elif typ.type_class_id == TypeClass.QUAL:
        assert isinstance(typ, QualType)
        if typ.qual_id in base_comp_types:
            return typ
        elif typ.qual_id in pass_thru_types:
            return get_base_prim_type(typ.tgt_type)
        else:
            raise ValueError("Bad qual_id = %u" % typ.qual_id)
    elif typ.type_class_id == TypeClass.ENUM:
        assert isinstance(typ, EnumType)
        return typ.the_base_type
    elif typ.type_class_id in [TypeClass.CLASS, TypeClass.STRUCT, TypeClass.UNION]:
        assert isinstance(typ, (ClassType, StructType, UnionType))
        return typ
    else:
        raise ValueError("Unrecognized Type: " + repr(typ))


from .BaseType import BaseType, TypeClass
from .ClassType import ClassType
from .IdentifiedQualType import IdentifiedQualType
from .PrimitiveType import PrimitiveType
from .QualType import QualType
from .StructType import StructType
from .EnumType import EnumType
from .UnionType import UnionType
