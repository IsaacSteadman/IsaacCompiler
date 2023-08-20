def get_uni_op_fn_type(
    typ: "BaseType", is_ref: bool = True, is_const: bool = False, res_ref: bool = True
) -> "QualType":
    arg_t = typ
    res_t = typ
    if is_const:
        arg_t = QualType(QualType.QUAL_CONST, arg_t)
    if is_ref:
        arg_t = QualType(QualType.QUAL_REF, arg_t)
    if res_ref:
        res_t = QualType(QualType.QUAL_REF, res_t)
    return QualType(QualType.QUAL_FN, res_t, [arg_t])


def get_uni_op_fn_type_r__r(typ):
    return get_uni_op_fn_type(typ, True, False, True)


def get_uni_op_fn_type_r__v(typ):
    return get_uni_op_fn_type(typ, True, False, False)


def get_uni_op_fn_type_c_r__v(typ):
    return get_uni_op_fn_type(typ, True, True, False)


def get_uni_op_fn_type_v__v(typ):
    return get_uni_op_fn_type(typ, False, False, False)


from .BaseType import BaseType
from .types import QualType
