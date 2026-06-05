def is_fn_type(typ: "BaseType") -> bool:
    v_type = get_base_prim_type(typ)
    if v_type.type_class_id == TypeClass.QUAL:
        assert isinstance(v_type, QualType)
        if v_type.qual_id == QualType.QUAL_FN:
            return True
    return False


from .BaseType import BaseType, TypeClass
from .QualType import QualType
from .qual_atomic_type_util import get_base_prim_type
