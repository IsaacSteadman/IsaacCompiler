def get_value_type(typ: "BaseType", do_arr_to_ptr_decay: bool = False):
    if isinstance(typ, (PrimitiveType, UnionType, ClassType, StructType)):
        return typ
    elif isinstance(typ, QualType):
        if typ.qual_id in [QualType.QUAL_CONST, QualType.QUAL_REG, QualType.QUAL_VOLATILE, QualType.QUAL_DEF]:
            return get_value_type(typ.tgt_type)
        elif typ.qual_id == QualType.QUAL_ARR:
            if do_arr_to_ptr_decay:
                return QualType(QualType.QUAL_PTR, typ.tgt_type)
            else:
                return typ
        elif typ.qual_id in [QualType.QUAL_FN, QualType.QUAL_PTR]:
            return typ
        elif typ.qual_id == QualType.QUAL_REF:
            return get_value_type(typ.tgt_type)
        else:
            raise ValueError("Unrecognized qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return get_value_type(typ.typ)
    else:
        raise TypeError("Unrecognized Type: %s" % repr(typ))


from .BaseType import BaseType
from .ClassType import ClassType
from .IdentifiedQualType import IdentifiedQualType
from .PrimitiveType import PrimitiveType
from .QualType import QualType
from .StructType import StructType
from .UnionType import UnionType