from typing import Tuple, Union


def strip_cv_qualifiers(typ: "BaseType") -> "BaseType":
    while isinstance(typ, QualType) and typ.qual_id in {
        QualType.QUAL_CONST,
        QualType.QUAL_DEF,
        QualType.QUAL_REG,
        QualType.QUAL_VOLATILE,
        QualType.QUAL_ATOMIC,
    }:
        typ = typ.tgt_type
    return typ


def is_volatile_type(
    typ: Union["BaseType", "IdentifiedQualType"], through_ref: bool = False
) -> bool:
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    if through_ref and isinstance(typ, QualType) and typ.qual_id == QualType.QUAL_REF:
        typ = typ.tgt_type
    while isinstance(typ, QualType) and typ.qual_id in {
        QualType.QUAL_CONST,
        QualType.QUAL_DEF,
        QualType.QUAL_REG,
        QualType.QUAL_VOLATILE,
        QualType.QUAL_ATOMIC,
    }:
        if typ.qual_id == QualType.QUAL_VOLATILE:
            return True
        typ = typ.tgt_type
    return False


def is_atomic_type(
    typ: Union["BaseType", "IdentifiedQualType"], through_ref: bool = False
) -> bool:
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    if through_ref and isinstance(typ, QualType) and typ.qual_id == QualType.QUAL_REF:
        typ = typ.tgt_type
    while isinstance(typ, QualType) and typ.qual_id in {
        QualType.QUAL_CONST,
        QualType.QUAL_DEF,
        QualType.QUAL_REG,
        QualType.QUAL_VOLATILE,
        QualType.QUAL_ATOMIC,
    }:
        if typ.qual_id == QualType.QUAL_ATOMIC:
            return True
        typ = typ.tgt_type
    return False


def is_volatile_storage_type(
    typ: Union["BaseType", "IdentifiedQualType"], through_ref: bool = False
) -> bool:
    if is_volatile_type(typ, through_ref):
        return True
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    if through_ref and isinstance(typ, QualType) and typ.qual_id == QualType.QUAL_REF:
        typ = typ.tgt_type
    if isinstance(typ, QualType) and typ.qual_id == QualType.QUAL_ARR:
        return is_volatile_storage_type(typ.tgt_type)
    return False


def is_atomic_storage_type(
    typ: Union["BaseType", "IdentifiedQualType"], through_ref: bool = False
) -> bool:
    if is_atomic_type(typ, through_ref):
        return True
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    if through_ref and isinstance(typ, QualType) and typ.qual_id == QualType.QUAL_REF:
        typ = typ.tgt_type
    if isinstance(typ, QualType) and typ.qual_id == QualType.QUAL_ARR:
        return is_atomic_storage_type(typ.tgt_type)
    return False


def add_volatile_qualifier(typ: "BaseType") -> "BaseType":
    if is_volatile_type(typ):
        return typ
    return QualType(QualType.QUAL_VOLATILE, typ)


def add_atomic_qualifier(typ: "BaseType") -> "BaseType":
    if is_atomic_type(typ):
        return typ
    return QualType(QualType.QUAL_ATOMIC, typ)


def is_flexible_array_type(typ: "BaseType") -> bool:
    typ = strip_cv_qualifiers(typ)
    return (
        isinstance(typ, QualType)
        and typ.qual_id == QualType.QUAL_ARR
        and typ.ext_inf is None
    )


def get_base_prim_type(typ: Union["BaseType", "IdentifiedQualType"]) -> "BaseType":
    assert typ is not None
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    base_comp_types = {
        QualType.QUAL_FN,
        QualType.QUAL_PTR,
        QualType.QUAL_ARR,
        QualType.QUAL_REF,
    }
    pass_thru_types = {
        QualType.QUAL_REG,
        QualType.QUAL_CONST,
        QualType.QUAL_DEF,
        QualType.QUAL_VOLATILE,
        QualType.QUAL_ATOMIC,
    }
    if typ.type_class_id == TypeClass.PRIM:
        assert isinstance(typ, PrimitiveType)
        return typ
    elif typ.type_class_id == TypeClass.QUAL:
        assert isinstance(typ, QualType)
        if typ.qual_id in base_comp_types:
            return typ
        elif typ.qual_id in pass_thru_types:
            return get_base_prim_type(typ.tgt_type)
        else:
            raise ValueError("Bad qual_id = %u" % typ.qual_id)
    elif typ.type_class_id == TypeClass.ENUM:
        assert isinstance(typ, EnumType)
        return typ.the_base_type
    elif typ.type_class_id in [TypeClass.CLASS, TypeClass.STRUCT, TypeClass.UNION]:
        assert isinstance(typ, (ClassType, StructType, UnionType))
        return typ
    else:
        raise ValueError("Unrecognized Type: " + repr(typ))


# Compare types ignoring [C]onst [V]olatile and [R]egister
def compare_no_cvr(
    type_a: "BaseType", type_b: "BaseType", ignore_ref: bool = False
) -> bool:
    type_a = get_value_type(type_a) if ignore_ref else get_base_prim_type(type_a)
    type_b = get_value_type(type_b) if ignore_ref else get_base_prim_type(type_b)
    while (
        type_a.type_class_id == TypeClass.QUAL
        and type_b.type_class_id == TypeClass.QUAL
    ):
        assert isinstance(type_a, QualType)
        assert isinstance(type_b, QualType)
        if type_a.qual_id != type_b.qual_id:
            return False
        elif type_a.qual_id == QualType.QUAL_FN:
            _var_a = (
                isinstance(type_a.ext_inf, list)
                and len(type_a.ext_inf) > 0
                and type_a.ext_inf[-1] is None
            )
            _var_b = (
                isinstance(type_b.ext_inf, list)
                and len(type_b.ext_inf) > 0
                and type_b.ext_inf[-1] is None
            )
            if _var_a != _var_b:
                return False
            _params_a = type_a.ext_inf[:-1] if _var_a else type_a.ext_inf
            _params_b = type_b.ext_inf[:-1] if _var_b else type_b.ext_inf
            if len(_params_a) != len(_params_b):
                return False
            if not compare_no_cvr(type_a.tgt_type, type_b.tgt_type):
                return False
            for c in range(len(_params_a)):
                if not compare_no_cvr(_params_a[c], _params_b[c]):
                    return False
            return True
        elif type_a.qual_id == QualType.QUAL_ARR:
            if type_a.ext_inf is not None and type_b.ext_inf is not None:
                if type_a.ext_inf != type_b.ext_inf:
                    return False
        type_a = get_base_prim_type(type_a.tgt_type)
        type_b = get_base_prim_type(type_b.tgt_type)
    if type_a.type_class_id != type_b.type_class_id:
        return False
    elif type_a.type_class_id == TypeClass.PRIM:
        assert isinstance(type_a, PrimitiveType)
        assert isinstance(type_b, PrimitiveType)
        return type_a.typ == type_b.typ and type_a.sign == type_b.sign
    else:
        assert isinstance(type_a, (EnumType, UnionType, StructType, ClassType))
        assert isinstance(type_b, (EnumType, UnionType, StructType, ClassType))
        assert type_a.parent is not None, "parent should not be None"
        assert type_b.parent is not None, "parent should not be None"
        if type_a.parent is not type_b.parent:
            return False
        elif type_a.name != type_b.name:
            return False
    return True


def get_value_type(typ: "BaseType", do_arr_to_ptr_decay: bool = False):
    if isinstance(typ, (PrimitiveType, UnionType, ClassType, StructType)):
        return typ
    elif isinstance(typ, QualType):
        if typ.qual_id in [
            QualType.QUAL_CONST,
            QualType.QUAL_REG,
            QualType.QUAL_VOLATILE,
            QualType.QUAL_ATOMIC,
            QualType.QUAL_DEF,
        ]:
            return get_value_type(typ.tgt_type)
        elif typ.qual_id == QualType.QUAL_ARR:
            if do_arr_to_ptr_decay:
                return QualType(QualType.QUAL_PTR, typ.tgt_type)
            else:
                return typ
        elif typ.qual_id in [QualType.QUAL_FN, QualType.QUAL_PTR]:
            return typ
        elif typ.qual_id == QualType.QUAL_REF:
            return get_value_type(typ.tgt_type)
        else:
            raise ValueError("Unrecognized qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return get_value_type(typ.typ)
    else:
        raise TypeError("Unrecognized Type: %s" % repr(typ))


def get_tgt_ref_type(typ: "BaseType") -> Tuple["BaseType", "BaseType", bool]:
    """
    returns primitive type, v value type, is reference
    """
    vt = pt = get_base_prim_type(typ)
    is_ref = False
    if pt.type_class_id == TypeClass.QUAL:
        assert isinstance(pt, QualType)
        if pt.qual_id == QualType.QUAL_REF:
            is_ref = True
            vt = get_base_prim_type(pt.tgt_type)
    return pt, vt, is_ref


def is_prim_or_ptr(typ: "BaseType") -> bool:
    if typ.type_class_id == TypeClass.PRIM:
        return True
    elif typ.type_class_id != TypeClass.QUAL:
        return False
    assert isinstance(typ, QualType)
    return typ.qual_id == QualType.QUAL_PTR


from .BaseType import BaseType, TypeClass
from .IdentifiedQualType import IdentifiedQualType
from .PrimitiveType import PrimitiveType
from .QualType import QualType
from .StructType import StructType
from .UnionType import UnionType
from .ClassType import ClassType
from .EnumType import EnumType
