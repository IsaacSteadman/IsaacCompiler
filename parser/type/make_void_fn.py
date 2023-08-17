from typing import List


def make_void_fn(arg_types: List["BaseType"]):
    return QualType(QualType.QUAL_FN, void_t, arg_types)


from .QualType import QualType
from .PrimitiveType import void_t
from .BaseType import BaseType