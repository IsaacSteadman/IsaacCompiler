from typing import List
from .BaseExpr import BaseExpr, ExprType


class SpecialDotExpr(BaseExpr):
    expr_id = ExprType.DOT

    def __init__(self, obj: "BaseExpr", attr: str):
        self.obj = obj
        self.attr = attr
        self.do_deref = False
        if self.obj.t_anot is None:
            return
        src_pt, src_vt, is_src_ref = get_tgt_ref_type(self.obj.t_anot)
        if src_vt.type_class_id not in [
            TypeClass.STRUCT,
            TypeClass.UNION,
            TypeClass.CLASS,
        ]:
            raise TypeError(
                "Cannot use '.' operator on non-class/struct/union types, got src_vt = %s, obj = %s"
                % (get_user_str_from_type(src_vt), obj)
            )
        assert isinstance(src_vt, (StructType, UnionType, ClassType))
        ctx_var = None
        member_res = None
        if src_vt.type_class_id in {TypeClass.STRUCT, TypeClass.UNION}:
            assert isinstance(src_vt, (StructType, UnionType))
            member_res = src_vt.resolve_member(attr)
            if member_res is not None:
                ctx_var = member_res.member
        else:
            assert isinstance(src_vt, (StructType, ClassType))
            var_index = src_vt.definition.get(attr, -1)
            if var_index != -1:
                ctx_var = src_vt.var_order[var_index]
        if ctx_var is None:
            raise AttributeError(
                "Instance of union/class/struct '%s' has no member '%s'"
                % (src_vt.name, attr)
            )
        attr_pt, attr_vt, is_attr_ref = get_tgt_ref_type(ctx_var.typ)
        if is_src_ref and not is_attr_ref:
            self.t_anot = QualType(QualType.QUAL_REF, attr_pt)
        else:
            if is_attr_ref:
                self.do_deref = True
            self.t_anot = attr_pt
        # Annotate bit-field info: (byte_offset, bit_shift, bit_mask, storage_sz)
        self.bit_field_info = None if member_res is None else member_res.bit_field_info

    def init_temps(self, main_temps):
        main_temps = super(SpecialDotExpr, self).init_temps(main_temps)
        return self.obj.init_temps(main_temps)

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on operator expressions")

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.obj, self.attr), pretty_repr_ctx
        )


from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import TypeClass
from ..type.get_user_str_from_type import get_user_str_from_type
from ..type.types import (
    ClassType,
    CompileContext,
    QualType,
    StructType,
    UnionType,
    get_tgt_ref_type,
)
from ...lexer.lexer import Token
