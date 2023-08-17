def is_prim_or_ptr(typ: "BaseType") -> bool:
    if typ.type_class_id == TypeClass.PRIM:
        return True
    elif typ != TypeClass.QUAL:
        return False
    assert isinstance(typ, QualType)
    return typ.qual_id == QualType.QUAL_PTR


from .BaseType import BaseType, TypeClass
from .QualType import QualType