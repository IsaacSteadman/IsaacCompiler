from typing import Dict, List, Optional, Tuple
from .CompileContext import CompileContext
from .BaseType import BaseType, TypeClass


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
    def from_mangle(cls, s: str, c: int) -> Tuple["ClassType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return ClassType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl: bool = False) -> str:
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "K%u%s" % (len(name), name)

    def __init__(
        self,
        parent: Optional["CompileContext"],
        name: Optional[str] = None,
        incomplete: bool = True,
        definition: Dict[str, int] = None,
        var_order: List["ContextVariable"] = None,
        defined: bool = False,
        the_base_type: Optional["BaseType"] = None,
    ):
        super(ClassType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.var_order = [] if var_order is None else var_order
        self.defined = defined
        self.the_base_type = the_base_type
        self.align_override: Optional[int] = None
        self.attributes: List[Attribute] = []

    def offset_of(self, attr: str) -> int:
        index = self.definition[attr]
        off = (
            0 if self.the_base_type is None else size_of(self.the_base_type, owner=self)
        )
        for c in range(index):
            align = align_of(self.var_order[c].typ, owner=self)
            off = align_up(off, align)
            off += size_of(self.var_order[c].typ, owner=self)
        if index < len(self.var_order):
            off = align_up(off, align_of(self.var_order[index].typ, owner=self))
        return off

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.var_order,
                self.defined,
                self.the_base_type,
            ),
            pretty_repr_ctx,
        )

    def merge_to(self, other: "ClassType"):
        assert isinstance(other, ClassType)
        super(ClassType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.var_order = self.var_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type
        if self.align_override is not None:
            cur = 0 if other.align_override is None else other.align_override
            other.align_override = max(cur, self.align_override)
        other.attributes.extend(self.attributes)

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
                if s in ("{", "[", "("):
                    lvl += 1
                elif s in ("}", "]", ")"):
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


from ...PrettyRepr import get_pretty_repr
from .ContextVariable import ContextVariable
from .align_size_of import align_of
from .align_util import align_up
from ..ParsingError import ParsingError
from ..try_get_as_name import try_get_as_name
from ...lexer.lexer import Token, tok_to_str
from .Attribute import Attribute
from .get_base_type import get_base_type
from .get_strict_stmnt import get_strict_stmnt
from .VarDeclMods import VarDeclMods
from .align_size_of import size_of
