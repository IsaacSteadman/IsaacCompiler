from typing import List


def make_void_fn(arg_types: List["BaseType"]):
    return QualType(QualType.QUAL_FN, void_t, arg_types)


from .BaseType import BaseType
from .types import QualType, void_t
