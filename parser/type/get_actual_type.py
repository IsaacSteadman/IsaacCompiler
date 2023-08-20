from typing import Union


def get_actual_type(typ: Union["BaseType", "IdentifiedQualType"]) -> "BaseType":
    return typ.typ if isinstance(typ, IdentifiedQualType) else typ


from .types import IdentifiedQualType
from .BaseType import BaseType
