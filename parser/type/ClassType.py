from typing import List, Tuple
from .BaseType import BaseType, TypeClass
from ..context.CompileContext import CompileContext


class ClassType(CompileContext, BaseType):
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

    type_class_id = TypeClass.CLASS
    mangle_captures = {"K": None}

    @classmethod
    def from_mangle(cls, s, c):
        """
        :param str s:
        :param int c:
        :rtype: (ClassType1, int)
        """
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return ClassType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "K%u%s" % (len(name), name)

    def __init__(
        self,
        parent,
        name=None,
        incomplete=True,
        definition=None,
        var_order=None,
        defined=False,
        the_base_type=None,
    ):
        """
        :param CompileContext|None parent:
        :param unicode|str|None name:
        :param bool incomplete:
        :param dict[str,int] definition:
        :param list[ContextVariable] var_order:
        :param bool defined:
        :param BaseType|None the_base_type:
        """
        super(ClassType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.var_order = [] if var_order is None else var_order
        self.defined = defined
        self.the_base_type = the_base_type

    def offset_of(self, attr):
        """
        :param str attr:
        :rtype: int
        """
        # TODO: improve speed of OffsetOf by tracking the offsets along-side the types
        index = self.definition[attr]
        off = 0
        for c in range(index):
            off += size_of(self.var_order[0].typ)
        return off

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.var_order,
                self.defined,
                self.the_base_type,
            )
        )

    def merge_to(self, other: "ClassType"):
        assert isinstance(other, ClassType)
        super(ClassType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.var_order = self.var_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(
                    tokens, c, "Expected a Type to follow ':' in class declaration"
                )
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
                raise ParsingError(tokens, start, "Expected closing '}' for class")
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

    def new_var(self, v: str, inst: "ContextVariable") -> "ContextVariable":
        if inst.mods == VarDeclMods.STATIC:
            return super(ClassType, self).new_var(v, inst)
        self.definition[v] = len(self.var_order)
        self.var_order.append(inst)
        return inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


from ...lexer.lexer import Token, tok_to_str
from ..try_get_as_name import try_get_as_name
from .size_of import size_of
from ..ParsingError import ParsingError
from ...ParseConstants import CLOSE_GROUPS, OPEN_GROUPS
from ...PrettyRepr import get_pretty_repr
from ..context.ContextVariable import ContextVariable, VarDeclMods
from ..stmnt.get_strict_stmnt import get_strict_stmnt
from .get_base_type import get_base_type
