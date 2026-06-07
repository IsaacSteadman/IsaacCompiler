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
    DESIG_INIT = 13  # designated initializer element: .field = expr  or  [index] = expr
    STMNT_EXPR = 14  # GNU statement expression: ({ ... })
    VA_INTRINSIC = 15  # va_start / va_arg / va_end / va_copy compiler intrinsics
    COMPOUND_LITERAL = 16  # C compound literal: (type){ ... }
    BUILTIN_CALL = 17  # compiler intrinsic call lowered by helper/runtime support
    ATOMIC_INTRINSIC = 18  # StackVM-backed atomic compiler intrinsics
    PERCPU_ADDR = 19  # StackVM current-core per-CPU address calculation
    BUILTIN_SPECIAL = 20  # compiler-only builtin with custom code generation
    LABEL_ADDRESS = 21  # GNU labels-as-values: &&label


class BaseExpr(PrettyRepr):
    t_anot: Optional["BaseType"] = None
    expr_id: ExprType = -1
    bit_field_info: Optional["BitFieldInfo"] = None
    # temps is a list of the types of the temporaries owned by the parent Expression Object only (ie 'self')
    temps: Optional[List["BaseType"]] = None
    temps_off: int = 0
    temps_stack_size: int = 0

    def init_temps(
        self, main_temps: Optional[List["BaseType"]]
    ) -> Optional[List["BaseType"]]:
        self.temps_off = 0 if main_temps is None else len(main_temps)
        self.temps_stack_size = 0
        if main_temps is None:
            main_temps = []
        if self.temps is not None:
            main_temps.extend(self.temps)
        self.temps = main_temps
        return main_temps


from ..type.BaseType import BaseType
from ..type.BitFieldInfo import BitFieldInfo
