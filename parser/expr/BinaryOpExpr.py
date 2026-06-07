from enum import Enum
from typing import List
from .BaseExpr import BaseExpr, ExprType
from ..type.get_arithmetic_op_fn_type import get_arithmetic_op_fn_type
from ..type.get_asgn_fn_type import get_asgn_fn_type
from ..type.get_asgn_sh_fn_type import get_asgn_sh_fn_type
from ..type.get_cmp_op_fn_type import get_cmp_op_fn_type
from ..type.get_sh_fn_type import get_sh_fn_type
from ..type.PrimitiveType import (
    FLT_TYPE_CODES,
    PrimitiveType,
    PrimitiveTypeId,
    arithmetic_types,
    bool_t,
    get_complex_component_type,
    int_types,
    make_complex_type,
    native_op_types,
    prim_types,
    size_l_t,
    snz_l_t,
    is_complex_primitive_type,
)


class BinaryExprSubType(Enum):
    ASSGN = 0
    ASSGN_MOD = 1
    ASSGN_DIV = 2
    ASSGN_MUL = 3
    ASSGN_MINUS = 4
    ASSGN_PLUS = 5
    ASSGN_AND = 6
    ASSGN_OR = 7
    ASSGN_XOR = 8
    ASSGN_RSHIFT = 9
    ASSGN_LSHIFT = 10
    MUL = 11
    DIV = 12
    MOD = 13
    MINUS = 14
    PLUS = 15
    LT = 16
    GT = 17
    LE = 18
    GE = 19
    NE = 20
    EQ = 21
    AND = 22
    OR = 23
    XOR = 24
    RSHIFT = 25
    LSHIFT = 26
    SS_AND = 27
    SS_OR = 28


ASSIGNMENT_OPS = {
    BinaryExprSubType.ASSGN,
    BinaryExprSubType.ASSGN_MOD,
    BinaryExprSubType.ASSGN_DIV,
    BinaryExprSubType.ASSGN_MUL,
    BinaryExprSubType.ASSGN_MINUS,
    BinaryExprSubType.ASSGN_PLUS,
    BinaryExprSubType.ASSGN_AND,
    BinaryExprSubType.ASSGN_OR,
    BinaryExprSubType.ASSGN_XOR,
    BinaryExprSubType.ASSGN_RSHIFT,
    BinaryExprSubType.ASSGN_LSHIFT,
}
CMP_OPS = {
    BinaryExprSubType.LT,
    BinaryExprSubType.GT,
    BinaryExprSubType.LE,
    BinaryExprSubType.GE,
    BinaryExprSubType.NE,
    BinaryExprSubType.EQ,
}
DCT_INFIX_OP_NAME = {
    "=": BinaryExprSubType.ASSGN,
    "%=": BinaryExprSubType.ASSGN_MOD,
    "/=": BinaryExprSubType.ASSGN_DIV,
    "*=": BinaryExprSubType.ASSGN_MUL,
    "-=": BinaryExprSubType.ASSGN_MINUS,
    "+=": BinaryExprSubType.ASSGN_PLUS,
    "&=": BinaryExprSubType.ASSGN_AND,
    "|=": BinaryExprSubType.ASSGN_OR,
    "^=": BinaryExprSubType.ASSGN_XOR,
    ">>=": BinaryExprSubType.ASSGN_RSHIFT,
    "<<=": BinaryExprSubType.ASSGN_LSHIFT,
    "*": BinaryExprSubType.MUL,
    "/": BinaryExprSubType.DIV,
    "%": BinaryExprSubType.MOD,
    "-": BinaryExprSubType.MINUS,
    "+": BinaryExprSubType.PLUS,
    "<": BinaryExprSubType.LT,
    ">": BinaryExprSubType.GT,
    "<=": BinaryExprSubType.LE,
    ">=": BinaryExprSubType.GE,
    "!=": BinaryExprSubType.NE,
    "==": BinaryExprSubType.EQ,
    "&": BinaryExprSubType.AND,
    "|": BinaryExprSubType.OR,
    "^": BinaryExprSubType.XOR,
    ">>": BinaryExprSubType.RSHIFT,
    "<<": BinaryExprSubType.LSHIFT,
    "&&": BinaryExprSubType.SS_AND,
    "||": BinaryExprSubType.SS_OR,
}


def _native_type_index(typ: "PrimitiveType") -> int:
    for c, native_type in enumerate(native_op_types):
        if native_type.typ == typ.typ and native_type.sign == typ.sign:
            return c
    raise ValueError("Native operator type not registered: %r" % (typ,))


def _get_common_complex_type(a_type: "BaseType", b_type: "BaseType"):
    float_ranks = {
        PrimitiveTypeId.FLT_F: 0,
        PrimitiveTypeId.FLT_D: 1,
        PrimitiveTypeId.FLT_LD: 2,
    }
    has_complex = False
    best_component = None
    best_rank = -1
    for typ in (get_value_type(a_type), get_value_type(b_type)):
        if is_complex_primitive_type(typ):
            has_complex = True
            component_type = get_complex_component_type(typ)
        elif isinstance(typ, PrimitiveType) and typ.typ in FLT_TYPE_CODES:
            component_type = typ
        else:
            continue
        rank = float_ranks[component_type.typ]
        if rank > best_rank:
            best_rank = rank
            best_component = component_type
    if not has_complex:
        return None
    assert best_component is not None
    return make_complex_type(best_component)


def _get_complex_native_op_type(type_id: BinaryExprSubType, a: BaseExpr, b: BaseExpr):
    if type_id in {
        BinaryExprSubType.PLUS,
        BinaryExprSubType.MINUS,
        BinaryExprSubType.MUL,
        BinaryExprSubType.DIV,
        BinaryExprSubType.EQ,
        BinaryExprSubType.NE,
    }:
        return _get_common_complex_type(a.t_anot, b.t_anot)
    if type_id in {
        BinaryExprSubType.ASSGN_PLUS,
        BinaryExprSubType.ASSGN_MINUS,
        BinaryExprSubType.ASSGN_MUL,
        BinaryExprSubType.ASSGN_DIV,
    }:
        left_type = get_value_type(a.t_anot)
        if is_complex_primitive_type(left_type):
            return left_type
    return None


class BinaryOpExpr(BaseExpr):
    expr_id = ExprType.BIN_OP
    lst_prim_fns = {
        BinaryExprSubType.ASSGN: list(map(get_asgn_fn_type, native_op_types)),
        BinaryExprSubType.ASSGN_MOD: list(map(get_asgn_fn_type, prim_types)),
        BinaryExprSubType.ASSGN_DIV: list(map(get_asgn_fn_type, arithmetic_types)),
        BinaryExprSubType.ASSGN_MUL: list(map(get_asgn_fn_type, arithmetic_types)),
        BinaryExprSubType.ASSGN_MINUS: list(map(get_asgn_fn_type, arithmetic_types)),
        BinaryExprSubType.ASSGN_PLUS: list(map(get_asgn_fn_type, arithmetic_types)),
        BinaryExprSubType.ASSGN_AND: list(map(get_asgn_fn_type, int_types)),
        BinaryExprSubType.ASSGN_OR: list(map(get_asgn_fn_type, int_types)),
        BinaryExprSubType.ASSGN_XOR: list(map(get_asgn_fn_type, int_types)),
        BinaryExprSubType.ASSGN_RSHIFT: list(map(get_asgn_sh_fn_type, int_types)),
        BinaryExprSubType.ASSGN_LSHIFT: list(map(get_asgn_sh_fn_type, int_types)),
        BinaryExprSubType.MUL: list(map(get_arithmetic_op_fn_type, arithmetic_types)),
        BinaryExprSubType.DIV: list(map(get_arithmetic_op_fn_type, arithmetic_types)),
        BinaryExprSubType.MOD: list(map(get_arithmetic_op_fn_type, prim_types)),
        BinaryExprSubType.MINUS: list(map(get_arithmetic_op_fn_type, arithmetic_types)),
        BinaryExprSubType.PLUS: list(map(get_arithmetic_op_fn_type, arithmetic_types)),
        BinaryExprSubType.LT: list(map(get_cmp_op_fn_type, prim_types)),
        BinaryExprSubType.GT: list(map(get_cmp_op_fn_type, prim_types)),
        BinaryExprSubType.LE: list(map(get_cmp_op_fn_type, prim_types)),
        BinaryExprSubType.GE: list(map(get_cmp_op_fn_type, prim_types)),
        BinaryExprSubType.NE: list(map(get_cmp_op_fn_type, native_op_types)),
        BinaryExprSubType.EQ: list(map(get_cmp_op_fn_type, native_op_types)),
        BinaryExprSubType.AND: list(map(get_arithmetic_op_fn_type, int_types)),
        BinaryExprSubType.OR: list(map(get_arithmetic_op_fn_type, int_types)),
        BinaryExprSubType.XOR: list(map(get_arithmetic_op_fn_type, int_types)),
        BinaryExprSubType.RSHIFT: list(map(get_sh_fn_type, int_types)),
        BinaryExprSubType.LSHIFT: list(map(get_sh_fn_type, int_types)),
        # SPECIAL
        BinaryExprSubType.SS_AND: [get_cmp_op_fn_type(bool_t)],
        # SPECIAL
        BinaryExprSubType.SS_OR: [get_cmp_op_fn_type(bool_t)],
    }

    def __init__(self, type_id: BinaryExprSubType, a: BaseExpr, b: BaseExpr):
        self.type_id = type_id
        self.op_fn_type = OperatorType.NATIVE
        self.op_fn_data = None  # should be int for native or ctx_var for function
        if a.t_anot is None or b.t_anot is None:
            self.t_anot = None
            self.op_fn_type = OperatorType.FUNCTION
            print("WARN: could not get type: a = %r, b = %r" % (a, b))
        else:
            complex_type = _get_complex_native_op_type(type_id, a, b)
            if complex_type is not None:
                self.op_fn_data = _native_type_index(complex_type)
                if type_id in ASSIGNMENT_OPS:
                    ref_type = QualType(QualType.QUAL_REF, complex_type)
                    a = get_implicit_conv_expr(a, ref_type)[0]
                    b = get_implicit_conv_expr(b, complex_type)[0]
                    self.t_anot = ref_type
                else:
                    a = get_implicit_conv_expr(a, complex_type)[0]
                    b = get_implicit_conv_expr(b, complex_type)[0]
                    self.t_anot = (
                        bool_t
                        if type_id in {BinaryExprSubType.EQ, BinaryExprSubType.NE}
                        else complex_type
                    )
            else:
                fn_types = BinaryOpExpr.lst_prim_fns[type_id]
                index_fn_t, lst_conv = abstract_overload_resolver([a, b], fn_types)
                if index_fn_t >= len(fn_types):
                    ok = False
                    tgt_pt, tgt_vt, is_tgt_ref = get_tgt_ref_type(a.t_anot)
                    if tgt_vt.type_class_id == TypeClass.QUAL:
                        assert isinstance(tgt_vt, QualType)
                        if tgt_vt.qual_id == QualType.QUAL_PTR:
                            ok = True
                    if not ok:
                        raise TypeError(
                            "No overloaded operator function for %s exists for types: %s and %s"
                            % (
                                type_id.name,
                                get_user_str_from_type(a.t_anot),
                                get_user_str_from_type(b.t_anot),
                            )
                        )
                    self.op_fn_type = OperatorType.PTR_GENERIC
                    self.op_fn_data = 0
                    if type_id == BinaryExprSubType.ASSGN:
                        ref_type = QualType(QualType.QUAL_REF, tgt_vt)
                        a = get_implicit_conv_expr(a, ref_type)[0]
                        b = get_implicit_conv_expr(b, tgt_vt)[0]
                        self.t_anot = ref_type
                        ok = True
                    elif type_id in [
                        BinaryExprSubType.ASSGN_MINUS,
                        BinaryExprSubType.ASSGN_PLUS,
                    ]:
                        ref_type = QualType(QualType.QUAL_REF, tgt_vt)
                        a = get_implicit_conv_expr(a, ref_type)[0]
                        res = get_implicit_conv_expr(b, snz_l_t)
                        if res is None or res[1] == 0:
                            res = get_implicit_conv_expr(b, size_l_t)
                        else:
                            self.op_fn_data = 1
                        assert (
                            res is not None and res[1] != 0
                        ), "Expected resolution of overloaded pointer arithmetic"
                        b = res[0]
                        self.t_anot = ref_type
                        ok = True
                    elif type_id == BinaryExprSubType.PLUS:
                        a = get_implicit_conv_expr(a, tgt_vt)[0]
                        res = get_implicit_conv_expr(b, snz_l_t)
                        if res is None or res[1] == 0:
                            res = get_implicit_conv_expr(b, size_l_t)
                        else:
                            self.op_fn_data = 1
                        assert (
                            res is not None and res[1] != 0
                        ), "Expected resolution of overloaded pointer arithmetic"
                        b = res[0]
                        self.t_anot = tgt_vt
                        ok = True
                    elif type_id == BinaryExprSubType.MINUS:
                        lst_try = [size_l_t, snz_l_t, tgt_vt]
                        lst_try = list(
                            map(
                                lambda to_type: get_implicit_conv_expr(b, to_type),
                                lst_try,
                            )
                        )
                        best = None
                        best_c = 0
                        for c, res in enumerate(lst_try):
                            if res is None or res[1] == 0:
                                continue
                            elif best is None or best[1] > res[1]:
                                best = res
                                best_c = c
                            elif best[1] == res[1]:
                                if best_c == 0 and c == 1:
                                    best = res
                                    best_c = c
                                else:
                                    raise TypeError(
                                        "resolution of overloaded pointer subtraction is ambiguous a = %r, b = %r"
                                        % (a, b)
                                    )
                        if best is not None:
                            self.op_fn_data = best_c
                            if best_c >= 2:
                                assert best_c == 2
                                self.t_anot = snz_l_t
                            else:
                                self.t_anot = tgt_vt
                            b = best[0]
                            a = get_implicit_conv_expr(a, tgt_vt)[0]
                            ok = True
                    elif type_id in CMP_OPS:
                        a = get_implicit_conv_expr(a, tgt_vt)[0]
                        b = get_implicit_conv_expr(b, tgt_vt)[0]
                        self.t_anot = bool_t
                        ok = True
                    if not ok and type_id == BinaryExprSubType.ASSGN:
                        self.op_fn_type = OperatorType.GENERIC
                    if not ok:
                        raise TypeError(
                            "No overloaded operator function for %s exists for types: %s and %s"
                            % (
                                type_id.name,
                                get_user_str_from_type(a.t_anot),
                                get_user_str_from_type(b.t_anot),
                            )
                        )
                else:
                    self.op_fn_data = index_fn_t
                    a = lst_conv[0]
                    b = lst_conv[1]
                    self.t_anot = fn_types[index_fn_t].tgt_type
        self.a = a
        self.b = b
        native_value_type = (
            get_value_type(self.a.t_anot)
            if type_id in ASSIGNMENT_OPS
            else get_value_type(self.t_anot)
        )
        if (
            self.op_fn_type == OperatorType.NATIVE
            and is_complex_primitive_type(native_value_type)
            and type_id != BinaryExprSubType.ASSGN
        ):
            self.temps = [native_value_type, native_value_type]
            if type_id in ASSIGNMENT_OPS:
                self.temps.append(QualType(QualType.QUAL_PTR, native_value_type))
        elif (
            self.op_fn_type == OperatorType.NATIVE
            and self.t_anot is bool_t
            and type_id in {BinaryExprSubType.EQ, BinaryExprSubType.NE}
            and any(is_complex_primitive_type(arg.t_anot) for arg in (self.a, self.b))
        ):
            complex_type = get_value_type(self.a.t_anot)
            if not is_complex_primitive_type(complex_type):
                complex_type = get_value_type(self.b.t_anot)
            self.temps = [complex_type, complex_type]

    def init_temps(self, main_temps):
        main_temps = super(BinaryOpExpr, self).init_temps(main_temps)
        return self.a.init_temps(self.b.init_temps(main_temps))

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on operator expressions")

    def pretty_repr(self, pretty_repr_ctx=None):
        rtn = [
            self.__class__.__name__,
            "(",
            "BinaryExprSubType",
            ".",
            self.type_id.name,
        ]
        for inst in (self.a, self.b):
            rtn.extend([","] + get_pretty_repr(inst, pretty_repr_ctx))
        rtn.append(")")
        return rtn


from .OperatorType import OperatorType
from .abstract_overload_resolver import abstract_overload_resolver
from .get_implicit_conv_expr import get_implicit_conv_expr
from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import TypeClass
from ..type.get_user_str_from_type import get_user_str_from_type
from ..type.CompileContext import CompileContext
from ..type.qual_atomic_type_util import get_tgt_ref_type, get_value_type
from ...lexer.lexer import Token
from ..type.QualType import QualType
