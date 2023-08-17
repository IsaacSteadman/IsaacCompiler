def is_prim_type_id(typ: "BaseType", type_id: int) -> bool:
    if typ.type_class_id == TypeClass.PRIM:
        assert isinstance(typ, PrimitiveType)
        return typ.typ == type_id
    return False


from .BaseType import BaseType, TypeClass
from .PrimitiveType import PrimitiveType