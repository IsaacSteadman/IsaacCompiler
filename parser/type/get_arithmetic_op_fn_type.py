def get_arithmetic_op_fn_type(typ: "BaseType", is_const_ref: bool = False):
    arg_t = typ
    if is_const_ref:
        arg_t = QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, arg_t))
    return QualType(QualType.QUAL_FN, typ, [arg_t, arg_t])


from .QualType import QualType
from .BaseType import BaseType
