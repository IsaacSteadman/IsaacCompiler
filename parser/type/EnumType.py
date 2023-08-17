from typing import Dict, List, Optional, Tuple
from .BaseType import BaseType, TypeClass
from ..context.CompileContext import CompileContext


class EnumType(CompileContext, BaseType):
    def to_user_str(self):
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.ENUM
    mangle_captures = {
        'E': None
    }

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["EnumType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return EnumType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "E%u%s" % (len(name), name)

    def __init__(
            self,
            parent: Optional["CompileContext"],
            name: Optional[str] = None,
            incomplete: bool = True,
            variables: Dict[str, "ContextVariable"] = None,
            defined: bool = False,
            the_base_type: Optional["BaseType"] = None
    ):
        super(EnumType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.the_base_type = the_base_type
        if variables is not None:
            self.vars.update(variables)
        self.defined = defined

    def compile_var_init(self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None):
        return self.the_base_type.compile_var_init(cmpl_obj, init_args, context, ref, cmpl_data, temp_links)

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((
            self.parent, self.name, self.incomplete, self.vars, self.defined, self.the_base_type))

    def merge_to(self, other):
        assert isinstance(other, EnumType)
        super(EnumType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.the_base_type = self.the_base_type
        other.defined = self.defined

    def build(self, tokens: List[Token], c: int, end: int, context: "CompileContext") -> int:
        # TODO: (mentioned later in this function)
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(tokens, c, "Expected a Type to follow ':' in enum declaration")
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, c, "Expected closing '}' for enum")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].type_id == TokenType.NAME:
                    name = tokens[c].str
                    if self.has_var_strict(name):
                        raise ParsingError(tokens, c, "Redefinition of enumerated name: '%s'" % name)
                    expr, c = get_expr(tokens, c, ",", end_p, context)
                    self.new_var(name, ContextVariable(name, self.the_base_type).const_init(expr))
                    # TODO: assert ConstExpr
                else:
                    raise ParsingError(tokens, c, "Expected type_id=TokenType.NAME Token in enum")
                c += 1
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def is_namespace(self):
        return False

    def is_type(self):
        return True


from .get_base_type import get_base_type
from ..ParsingError import ParsingError
from ..try_get_as_name import try_get_as_name
from ...ParseConstants import CLOSE_GROUPS, OPEN_GROUPS
from ...PrettyRepr import get_pretty_repr
from ..context.ContextVariable import ContextVariable
from ..expr.get_expr import get_expr
from ...lexer.lexer import Token, TokenType, tok_to_str
