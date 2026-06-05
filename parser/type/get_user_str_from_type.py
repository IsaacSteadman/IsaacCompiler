from typing import Union, TYPE_CHECKING


def get_user_str_from_type(typ: Union["BaseType", "IdentifiedQualType"]) -> str:
    return typ.to_user_str()


if TYPE_CHECKING:
    from .BaseType import BaseType
    from .IdentifiedQualType import IdentifiedQualType
