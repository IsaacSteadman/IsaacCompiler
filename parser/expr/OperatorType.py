from enum import Enum


class OperatorType(Enum):
    NATIVE = 0
    FUNCTION = 1
    PTR_GENERIC = 2
    GENERIC = 3