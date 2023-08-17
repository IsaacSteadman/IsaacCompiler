def size_of(typ, is_arg: bool = False):
    if isinstance(typ, QualType):
        if typ.qual_id == QualType.QUAL_ARR:
            if is_arg or typ.ext_inf is None:
                return 8
            return size_of(typ.tgt_type) * typ.ext_inf
        elif typ.qual_id in {QualType.QUAL_FN, QualType.QUAL_PTR, QualType.QUAL_REF}:
            return 8
        elif typ.qual_id in {
            QualType.QUAL_CONST,
            QualType.QUAL_DEF,
            QualType.QUAL_REG,
            QualType.QUAL_VOLATILE,
        }:
            return size_of(typ.tgt_type)
        else:
            raise ValueError("Unrecognized QualType.qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return size_of(typ.typ)
    elif isinstance(typ, PrimitiveType):
        return typ.size
    elif isinstance(typ, EnumType):
        return size_of(typ.the_base_type)
    elif isinstance(typ, (StructType, ClassType)):
        sz = 0 if typ.the_base_type is None else size_of(typ.the_base_type)
        # TODO: add 'packed' boolean attribute to StructType and ClassType1
        for ctx_var in typ.var_order:
            sz += size_of(ctx_var.typ)
        return sz
    elif isinstance(typ, UnionType):
        # TODO: remove BaseType from UnionType
        sz = 0
        for k in typ.definition:
            v = typ.definition[k]
            assert isinstance(v, ContextVariable)
            sz = max(sz, size_of(v.typ))
        return sz
    else:
        raise TypeError("Unrecognized type: %s" % typ.__class__.__name__)
    # TODO: add Typedef support


from .EnumType import EnumType
from .IdentifiedQualType import IdentifiedQualType
from .PrimitiveType import PrimitiveType
from .QualType import QualType
from .StructType import StructType
from .UnionType import UnionType
from ..context.ContextVariable import ContextVariable

from .ClassType import ClassType
