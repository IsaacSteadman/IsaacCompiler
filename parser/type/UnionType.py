from typing import List, Tuple
from .BaseType import BaseType, TypeClass
from ..context.CompileContext import CompileContext


class UnionType(CompileContext, BaseType):
    def to_user_str(self):
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_init(
        self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None
    ):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.UNION
    mangle_captures = {"U": None}

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["UnionType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return UnionType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "U%u%s" % (len(name), name)

    def __init__(
        self,
        parent,
        name=None,
        incomplete=True,
        definition=None,
        defined=False,
        the_base_type=None,
    ):
        """
        :param CompileContext|None parent:
        :param str|None name:
        :param bool incomplete:
        :param dict[str,ContextVariable]|None definition:
        :param bool defined:
        :param BaseType|None the_base_type:
        """
        super(UnionType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.defined = defined
        self.the_base_type = the_base_type

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.defined,
                self.the_base_type,
            )
        )

    def merge_to(self, other: "UnionType"):
        assert isinstance(other, UnionType)
        super(UnionType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            raise ParsingError(tokens, c, "Inheritance is not allowed for unions")
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
                raise ParsingError(tokens, start, "Expected closing '}' for union")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].str in {"public", "private", "protected"}:
                    # TODO: IDEA: store a current access specifier variable
                    # TODO:   then combine that with inst in the definition of function: 'NewVar(self, V, inst)'
                    raise ParsingError(
                        tokens, c, "access specifier keywords not allowed"
                    )
                stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def new_var(self, v: str, inst: "ContextVariable"):
        assert isinstance(inst, ContextVariable)
        if inst.mods == VarDeclMods.STATIC:
            super(UnionType, self).new_var(v, inst)
        else:
            self.definition[v] = inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


from ..ParsingError import ParsingError
from ...ParseConstants import CLOSE_GROUPS, OPEN_GROUPS
from ...PrettyRepr import get_pretty_repr
from ..context.ContextVariable import ContextVariable, VarDeclMods
from ...lexer.lexer import Token, tok_to_str
from ..try_get_as_name import try_get_as_name
from ..stmnt.get_strict_stmnt import get_strict_stmnt
