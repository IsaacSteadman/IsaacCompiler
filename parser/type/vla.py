from typing import Union


def is_vla_bound(bound) -> bool:
    return isinstance(bound, BaseExpr)


def _strip_cv_qualifiers(typ: "BaseType") -> "BaseType":
    while isinstance(typ, QualType) and typ.qual_id in {
        QualType.QUAL_CONST,
        QualType.QUAL_DEF,
        QualType.QUAL_REG,
        QualType.QUAL_VOLATILE,
        QualType.QUAL_ATOMIC,
    }:
        typ = typ.tgt_type
    return typ


def is_variable_length_array_type(typ: Union["BaseType", "IdentifiedQualType"]) -> bool:
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    typ = _strip_cv_qualifiers(typ)
    return (
        isinstance(typ, QualType)
        and typ.qual_id == QualType.QUAL_ARR
        and is_vla_bound(typ.ext_inf)
    )


def contains_variable_length_array_type(
    typ: Union["BaseType", "IdentifiedQualType"]
) -> bool:
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    typ = _strip_cv_qualifiers(typ)
    if isinstance(typ, QualType) and typ.qual_id == QualType.QUAL_ARR:
        return is_vla_bound(typ.ext_inf) or contains_variable_length_array_type(
            typ.tgt_type
        )
    return False


def vla_metadata_size(typ: Union["BaseType", "IdentifiedQualType"]) -> int:
    if not contains_variable_length_array_type(typ):
        raise TypeError("expected a variable-length array type")
    return 8


from ..expr.BaseExpr import BaseExpr
from .BaseType import BaseType
from .IdentifiedQualType import IdentifiedQualType
from .QualType import QualType
