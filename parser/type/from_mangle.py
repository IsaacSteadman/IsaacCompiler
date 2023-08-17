from typing import Tuple


def from_mangle(s: str, c: int) -> Tuple["BaseType", int]:
    if s[c] in QualType.mangle_captures:
        return QualType.from_mangle(s, c)
    elif s[c] in PrimitiveType.mangle_captures:
        return PrimitiveType.from_mangle(s, c)
    elif s[c] in ClassType.mangle_captures:
        return ClassType.from_mangle(s, c)
    elif s[c] in StructType.mangle_captures:
        return StructType.from_mangle(s, c)
    elif s[c] in UnionType.mangle_captures:
        return UnionType.from_mangle(s, c)
    elif s[c] in EnumType.mangle_captures:
        return EnumType.from_mangle(s, c)
    else:
        raise ValueError("Unrecognized mangle capture: '%s' at c = %u in %r" % (s[c], c, s))


from .BaseType import BaseType
from .QualType import QualType
from .PrimitiveType import PrimitiveType
from .ClassType import ClassType
from .StructType import StructType
from .UnionType import UnionType
from .EnumType import EnumType
