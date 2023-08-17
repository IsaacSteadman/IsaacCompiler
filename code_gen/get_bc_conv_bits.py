def get_bc_conv_bits(typ: "BaseType") -> int:
    out_bits = None
    typ = get_base_prim_type(typ)
    if typ.type_class_id == TypeClass.PRIM:
        assert isinstance(typ, PrimitiveType)
        sz_cls = typ.size.bit_length() - 1
        if 1 << sz_cls != typ.size or sz_cls > 3:
            raise TypeError("Bad Primitive Type Size: %u for %r" % (typ.size, typ))
        if typ.typ in INT_TYPE_CODES:
            out_bits = sz_cls << 1
            out_bits |= int(typ.sign)
        elif typ.typ in FLT_TYPE_CODES:
            sz_cls -= 1
            out_bits = sz_cls | 0x08
    elif typ.type_class_id == TypeClass.QUAL:
        assert isinstance(typ, QualType)
        if typ.qual_id == QualType.QUAL_PTR:
            out_bits = 3
    if out_bits is None:
        raise TypeError("Cannot cast to Type %s" % repr(typ))
    return out_bits


from ..parser.type.BaseType import BaseType,TypeClass
from ..parser.type.PrimitiveType import PrimitiveType, FLT_TYPE_CODES, INT_TYPE_CODES
from ..parser.type.QualType import QualType
from ..parser.type.get_base_prim_type import get_base_prim_type