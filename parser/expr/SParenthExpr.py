from typing import List
from .BaseExpr import BaseExpr, ExprType
from ..type.PrimitiveType import size_l_t, snz_l_t


# SParenth means '[' (Square)
class SParenthExpr(BaseExpr):
    expr_id = ExprType.SPARENTH

    def __init__(self, left_expr, inner_expr):
        """
        :param BaseExpr left_expr:
        :param BaseExpr inner_expr:
        """
        if left_expr.t_anot is not None and inner_expr.t_anot is not None:
            p_t, l_t, is_l_ref = get_tgt_ref_type(left_expr.t_anot)
            if l_t.type_class_id == TypeClass.QUAL:
                assert isinstance(l_t, QualType)
                if l_t.qual_id == QualType.QUAL_PTR or (l_t.qual_id == QualType.QUAL_ARR and is_l_ref):
                    if l_t.qual_id == QualType.QUAL_PTR and is_l_ref:
                        left_expr = CastOpExpr(l_t, left_expr, CastType.IMPLICIT)
                    self.t_anot = QualType(QualType.QUAL_REF, l_t.tgt_type)
                    res = get_implicit_conv_expr(inner_expr, size_l_t)
                    if res is None:
                        res = get_implicit_conv_expr(inner_expr, snz_l_t)
                    # print "RESULT of SParenthExpr(%r, %r) : res = %r" % (LeftExpr, InnerExpr, res)
                    if res is None:
                        raise TypeError("Could not convert %r to %s" % (inner_expr, get_user_str_from_type(size_l_t)))
                    b, code = res
                    if code == 0:
                        raise TypeError("Could not convert %r to %s" % (inner_expr, get_user_str_from_type(size_l_t)))
                    inner_expr = b
                else:
                    raise TypeError(
                        "Unsupported type %s (wanted array reference or pointer) for '[]' operator" %
                        get_user_str_from_type(left_expr.t_anot)
                    )
            if self.t_anot is None:
                raise TypeError("Unsupported type %s for '[]' operator" % get_user_str_from_type(left_expr.t_anot))
        else:
            raise TypeError(
                "Required type annotation for SParenthExpr, LeftExpr = %r, InnerExpr = %r" % (
                    left_expr, inner_expr
                )
            )
        if self.t_anot is None:
            raise TypeError("ESCAPED Unsupported type %s for '[]' operator" % get_user_str_from_type(left_expr.t_anot))
        self.left_expr = left_expr
        self.inner_expr = inner_expr

    def init_temps(self, main_temps):
        main_temps = super(SParenthExpr, self).init_temps(main_temps)
        return self.inner_expr.init_temps(self.left_expr.init_temps(main_temps))

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.left_expr, self.inner_expr))

    def build(self, tokens: List["Token"], c: int, end: int, context: "CompileContext") -> int:
        raise NotImplementedError("Cannot call 'build' on SParenthExpr")


from .CastOpExpr import CastOpExpr, CastType
from .get_implicit_conv_expr import get_implicit_conv_expr
from ...PrettyRepr import get_pretty_repr
from ..context.CompileContext import CompileContext
from ..type.BaseType import TypeClass
from ..type.QualType import QualType
from ..type.get_tgt_ref_type import get_tgt_ref_type
from ..type.get_user_str_from_type import get_user_str_from_type
from ...lexer.lexer import Token