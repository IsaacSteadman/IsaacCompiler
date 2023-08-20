from typing import List, Optional, Union
from .BaseExpr import BaseExpr, ExprType


class NameRefExpr(BaseExpr):
    expr_id = ExprType.NAME
    # init-args added for __repr__

    def __init__(self, name: Optional[Union[str, "ContextVariable"]] = None):
        self.is_op_fn = False
        if name is None:
            self.name = None
            self.ctx_var = None
        elif isinstance(name, str):
            self.name = name
            self.ctx_var = None
        else:
            assert isinstance(name, ContextVariable)
            self.name = name.name
            self.ctx_var = name
            self.is_op_fn = name.is_op_fn

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        assert c < end
        if tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "Expected a name")
        self.name, c = get_name_from_tokens(tokens, c)
        if self.name.rsplit("::", 1)[-1].startswith("operator"):
            self.is_op_fn = True
        ctx_var = context.scoped_get(self.name)
        if ctx_var is None:
            raise ParsingError(tokens, c, "Undefined Identifier '%s'" % self.name)
        if not isinstance(ctx_var, ContextVariable):
            raise ParsingError(tokens, c, "Expected Variable")
        self.ctx_var = ctx_var
        if ctx_var.typ.type_class_id != TypeClass.MULTI:
            self.t_anot = QualType(QualType.QUAL_REF, get_value_type(ctx_var.typ))
        return c

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.name) + [")"]


from ..ParsingError import ParsingError
from ..get_name_from_tokens import get_name_from_tokens
from ...PrettyRepr import get_pretty_repr
from ..type.BaseType import TypeClass
from ..type.types import QualType, get_value_type, CompileContext, ContextVariable
from ...lexer.lexer import Token, TokenType
