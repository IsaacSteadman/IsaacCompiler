from enum import Enum
from typing import List, Optional
from ...PrettyRepr import PrettyRepr


class ExprType(Enum):
    LITERAL = 0
    NAME = 1
    BIN_OP = 2
    UNI_OP = 3
    CURLY = 4
    CAST = 5
    DOT = 6
    PTR_MEMBER = 7
    FN_CALL = 8
    SPARENTH = 9
    PARENTH = 10
    INLINE_IF = 11
    DECL_VAR = 12


class BaseExpr(PrettyRepr):
    t_anot: Optional["BaseType"] = None
    expr_id: ExprType = -1
    # temps is a list of the types of the temporaries owned by the parent Expression Object only (ie 'self')
    temps: Optional[List["BaseType"]] = None
    temps_off: int = 0

    def pretty_repr(self):
        return [self.__class__.__name__, "(", ")"]

    def init_temps(self, main_temps: Optional[List["BaseType"]]) -> Optional[List["BaseType"]]:
        self.temps_off = 0 if main_temps is None else len(main_temps)
        if main_temps is None:
            main_temps = []
        if self.temps is not None:
            main_temps.extend(self.temps)
        self.temps = main_temps
        return main_temps


from ..type.BaseType import BaseType