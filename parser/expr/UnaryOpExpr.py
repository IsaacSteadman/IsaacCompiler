from enum import Enum
from typing import List
from .BaseExpr import BaseExpr, ExprType
from .CastOpExpr import CastOpExpr, CastType
from .OperatorType import OperatorType
from .abstract_overload_resolver import abstract_overload_resolver
from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import TypeClass
from ..type.get_uni_op_fn_type import (
    get_uni_op_fn_type_r__r,
    get_uni_op_fn_type_r__v,
    get_uni_op_fn_type_v__v,
)
from ..type.get_user_str_from_type import get_user_str_from_type
from ..type.types import (
    CompileContext,
    QualType,
    bool_t,
    get_tgt_ref_type,
    int_types,
    prim_types,
    signed_num_types,
    size_of,
)
from ...lexer.lexer import Token


class UnaryExprSubType(Enum):
    BOOL_NOT = 0
    PRE_DEC = 1
    POST_DEC = 2
    PRE_INC = 3
    POST_INC = 4
    BIT_NOT = 5
    STAR = 6
    REFERENCE = 7
    MINUS = 8
    PLUS = 9


DCT_PREFIX_OP_NAME = {
    "!": UnaryExprSubType.BOOL_NOT,
    "--": UnaryExprSubType.PRE_DEC,
    "++": UnaryExprSubType.PRE_INC,
    "~": UnaryExprSubType.BIT_NOT,
    "*": UnaryExprSubType.STAR,
    "&": UnaryExprSubType.REFERENCE,
    "-": UnaryExprSubType.MINUS,
    "+": UnaryExprSubType.PLUS,
}

DCT_POSTFIX_OP_NAME = {
    "--": UnaryExprSubType.POST_DEC,
    "++": UnaryExprSubType.POST_INC,
}


class UnaryOpExpr(BaseExpr):
    expr_id = ExprType.UNI_OP
    lst_prim_fns = {
        UnaryExprSubType.BOOL_NOT: [get_uni_op_fn_type_v__v(bool_t)],
        UnaryExprSubType.PRE_DEC: list(map(get_uni_op_fn_type_r__r, prim_types)),
        UnaryExprSubType.POST_DEC: list(map(get_uni_op_fn_type_r__v, prim_types)),
        UnaryExprSubType.PRE_INC: list(map(get_uni_op_fn_type_r__r, prim_types)),
        UnaryExprSubType.POST_INC: list(map(get_uni_op_fn_type_r__v, prim_types)),
        UnaryExprSubType.BIT_NOT: list(map(get_uni_op_fn_type_v__v, int_types)),
        UnaryExprSubType.STAR: None,
        UnaryExprSubType.REFERENCE: None,
        UnaryExprSubType.MINUS: list(map(get_uni_op_fn_type_v__v, signed_num_types)),
        UnaryExprSubType.PLUS: list(map(get_uni_op_fn_type_v__v, prim_types)),
    }

    def __init__(self, type_id: UnaryExprSubType, a: BaseExpr):
        self.type_id = type_id
        self.op_fn_type = OperatorType.NATIVE
        self.op_fn_data = None
        assert a.t_anot is not None
        if UnaryOpExpr.lst_prim_fns[type_id] is not None:
            fn_types = UnaryOpExpr.lst_prim_fns[type_id]
            index_fn_t, lst_conv = abstract_overload_resolver([a], fn_types)
            if index_fn_t >= len(fn_types):
                tgt_type = None
                src_vt = None
                if type_id in [
                    UnaryExprSubType.PRE_DEC,
                    UnaryExprSubType.POST_DEC,
                    UnaryExprSubType.PRE_INC,
                    UnaryExprSubType.POST_INC,
                ]:
                    src_pt, src_vt, is_src_ref = get_tgt_ref_type(a.t_anot)
                    if src_vt.type_class_id == TypeClass.QUAL:
                        assert isinstance(src_vt, QualType)
                        if src_vt.qual_id == QualType.QUAL_PTR and is_src_ref:
                            tgt_type = src_vt.tgt_type
                if tgt_type is None:
                    raise TypeError(
                        "No overloaded operator function for %s exists for type: %s"
                        % (type_id.name, get_user_str_from_type(a.t_anot))
                    )
                assert isinstance(src_vt, QualType)
                if type_id in [UnaryExprSubType.PRE_DEC, UnaryExprSubType.PRE_INC]:
                    self.t_anot = a.t_anot
                else:
                    self.t_anot = src_vt
                self.op_fn_type = OperatorType.PTR_GENERIC
                self.op_fn_data = size_of(tgt_type)
            else:
                self.op_fn_data = index_fn_t
                a = lst_conv[0]
                self.t_anot = fn_types[index_fn_t].tgt_type
        elif type_id == UnaryExprSubType.REFERENCE:
            src_pt, src_vt, is_src_ref = get_tgt_ref_type(a.t_anot)
            if not is_src_ref:
                raise TypeError(
                    "Cannot get the pointer to a non-reference type %s"
                    % get_user_str_from_type(a.t_anot)
                )
            self.t_anot = QualType(QualType.QUAL_PTR, src_vt)
        elif type_id == UnaryExprSubType.STAR:
            src_pt, src_vt, is_src_ref = get_tgt_ref_type(a.t_anot)
            tgt_type = None
            if src_vt.type_class_id == TypeClass.QUAL:
                assert isinstance(src_vt, QualType)
                if src_vt.qual_id == QualType.QUAL_PTR:
                    tgt_type = src_vt.tgt_type
            if tgt_type is None:
                err_fmt = "\n".join(
                    [
                        "Expected a pointer type for UnaryExprSubType.STAR, given complete type %s,",
                        "  obtained prim_type = %s",
                        "  val_type = %s",
                    ]
                )
                raise TypeError(
                    err_fmt
                    % (
                        get_user_str_from_type(a.t_anot),
                        get_user_str_from_type(src_pt),
                        get_user_str_from_type(src_vt),
                    )
                )
            if is_src_ref:
                a = CastOpExpr(src_vt, a, CastType.IMPLICIT)
            self.t_anot = QualType(QualType.QUAL_REF, src_vt.tgt_type)
        else:
            raise NotImplementedError("type_id = %s, is not implemented" % type_id.name)
        self.a = a

    def init_temps(self, main_temps):
        main_temps = super(UnaryOpExpr, self).init_temps(main_temps)
        return self.a.init_temps(main_temps)

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on operator expressions")

    def pretty_repr(self):
        return (
            [
                self.__class__.__name__,
                "(",
                "UnaryExprSubType",
                ".",
                self.type_id.name,
                ",",
            ]
            + get_pretty_repr(self.a)
            + [")"]
        )
