from typing import List
from .BaseExpr import BaseExpr, ExprType


class SpecialPtrMemberExpr(BaseExpr):
    expr_id = ExprType.PTR_MEMBER

    def __init__(self, obj: BaseExpr, attr: str):
        self.obj = obj
        self.attr = attr
        if self.obj.t_anot is None:
            return
        src_ptr_pt, src_ptr_vt, is_src_ptr_ref = get_tgt_ref_type(self.obj.t_anot)
        if src_ptr_vt.type_class_id != TypeClass.QUAL:
            raise TypeError("Expected Pointer type for '->' operator")
        assert isinstance(src_ptr_vt, QualType)
        if src_ptr_vt.qual_id != QualType.QUAL_PTR:
            raise TypeError("Expected Pointer type for '->' operator")
        if is_src_ptr_ref:
            self.obj = CastOpExpr(src_ptr_vt, obj)
        src_vt = get_base_prim_type(src_ptr_vt.tgt_type)
        if src_vt.type_class_id not in [
            TypeClass.STRUCT,
            TypeClass.UNION,
            TypeClass.CLASS,
        ]:
            raise TypeError(
                "Cannot use '->' operator on non-class/struct/union pointer types"
            )
        assert isinstance(src_vt, (StructType, UnionType, ClassType))
        ctx_var = None
        if src_vt.type_class_id == TypeClass.UNION:
            assert isinstance(src_vt, UnionType)
            ctx_var = src_vt.definition.get(attr, ctx_var)
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
        if is_attr_ref:
            self.do_deref = True
            self.t_anot = attr_pt
        else:
            self.t_anot = QualType(QualType.QUAL_REF, attr_pt)

    def init_temps(self, main_temps):
        main_temps = super(SpecialPtrMemberExpr, self).init_temps(main_temps)
        return self.obj.init_temps(main_temps)

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on operator expressions")

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.obj, self.attr))


from .CastOpExpr import CastOpExpr
from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import TypeClass
from ..type.types import (
    ClassType,
    CompileContext,
    QualType,
    StructType,
    UnionType,
    get_base_prim_type,
    get_tgt_ref_type,
)
from ...lexer.lexer import Token
