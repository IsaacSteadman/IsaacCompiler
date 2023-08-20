from typing import List
from .BaseExpr import BaseExpr, ExprType


class FnCallExpr(BaseExpr):
    expr_id = ExprType.FN_CALL

    def __init__(self, fn: BaseExpr, lst_args: List[BaseExpr]):
        self.fn = fn
        self.lst_args = lst_args
        resolve_overloaded_fn(self)
        fn_vt = get_value_type(self.fn.t_anot)
        assert fn_vt.type_class_id == TypeClass.QUAL
        assert isinstance(fn_vt, QualType)
        assert fn_vt.qual_id == QualType.QUAL_FN
        self.t_anot = fn_vt.tgt_type

    def init_temps(self, main_temps):
        main_temps = super(FnCallExpr, self).init_temps(main_temps)
        main_temps = self.fn.init_temps(main_temps)
        for expr in self.lst_args:
            main_temps = expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr_enum(
            (self.fn, self.lst_args)
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        raise NotImplementedError("Cannot call 'build' on FnCallExpr")


from .resolve_overloaded_fn import resolve_overloaded_fn
from ...PrettyRepr import get_pretty_repr_enum
from ..type.BaseType import TypeClass
from ..type.types import CompileContext, QualType, get_value_type
from ...lexer.lexer import Token
