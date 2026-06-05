def get_bc_conv_bits(typ: "BaseType") -> int:
    out_bits = None
    typ = get_base_prim_type(typ)
    if typ.type_class_id == TypeClass.PRIM:
        assert isinstance(typ, PrimitiveType)
        out_bits = get_primitive_conv_bits(typ)
    elif typ.type_class_id == TypeClass.QUAL:
        assert isinstance(typ, QualType)
        if typ.qual_id == QualType.QUAL_PTR:
            out_bits = 3
    if out_bits is None:
        raise TypeError("Cannot cast to Type %s" % repr(typ))
    return out_bits


from ..parser.type.BaseType import BaseType, TypeClass
from ..parser.type.PrimitiveType import (
    PrimitiveType,
    get_primitive_conv_bits,
)
from ..parser.type.QualType import QualType
from ..parser.type.qual_atomic_type_util import get_base_prim_type
