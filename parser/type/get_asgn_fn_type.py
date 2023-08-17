def get_asgn_fn_type(typ: "BaseType", is_const_ref: bool = False) -> "QualType":
    arg_t = typ
    if is_const_ref:
        arg_t = QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, arg_t))
    lvalue_type = QualType(QualType.QUAL_REF, typ)
    return QualType(QualType.QUAL_FN, lvalue_type, [lvalue_type, arg_t])


from .BaseType import BaseType
from .QualType import QualType

