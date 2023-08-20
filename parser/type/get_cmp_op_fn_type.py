def get_cmp_op_fn_type(typ: "BaseType", is_const_ref: bool = False):
    arg_t = typ
    if is_const_ref:
        arg_t = QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, arg_t))
    return QualType(QualType.QUAL_FN, bool_t, [arg_t, arg_t])


from .BaseType import BaseType
from .types import QualType, bool_t
