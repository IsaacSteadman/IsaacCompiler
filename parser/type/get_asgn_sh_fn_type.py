def get_asgn_sh_fn_type(typ: "BaseType", is_const_ref: bool = False):
    arg_t = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C, 1)
    if is_const_ref:
        arg_t = QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, arg_t))
    lvalue_type = QualType(QualType.QUAL_REF, typ)
    return QualType(QualType.QUAL_FN, lvalue_type, [lvalue_type, arg_t])


from .PrimitiveType import PrimitiveType, PrimitiveTypeId
from .QualType import QualType
from .BaseType import BaseType
