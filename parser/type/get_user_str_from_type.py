from typing import Union


def get_user_str_from_type(typ: Union["BaseType", "IdentifiedQualType"]) -> str:
    return typ.to_user_str()


from .BaseType import BaseType
from .IdentifiedQualType import IdentifiedQualType