from typing import List, Optional
from .BaseStmnt import BaseStmnt, StmntType


class TypeDefStmnt(BaseStmnt):
    stmnt_type = StmntType.TYPEDEF

    def __init__(self, id_qual_types: Optional[List["IdentifiedQualType"]] = None):
        self.id_qual_types = id_qual_types

    def pretty_repr(self, pretty_repr_ctx=None):
        return (
            [self.__class__.__name__, "("]
            + get_pretty_repr(self.id_qual_types, pretty_repr_ctx)
            + [")"]
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        c += 1
        base_decl_attrs = GNUAttributes()
        base_type, c = get_base_type(tokens, c, end, context, base_decl_attrs)
        end_stmnt = c
        # TODO: remove this limitation as this would break inline struct definitions (like struct {int a; char b} var)
        # TODO: DONE
        lvl = 0
        while end_stmnt < end and (tokens[end_stmnt].str != ";" or lvl > 0):
            if tokens[end_stmnt].str in OPEN_GROUPS:
                lvl += 1
            elif tokens[end_stmnt].str in CLOSE_GROUPS:
                lvl -= 1
            end_stmnt += 1
        if base_type is None:
            raise SyntaxError("Expected Typename for DeclStmnt")
        self.id_qual_types = []
        while c < end_stmnt + 1:
            named_qual_type, c = proc_typed_decl(
                tokens, c, end_stmnt, context, base_type
            )
            if named_qual_type is None:
                raise ParsingError(tokens, c, "Expected Typename for DeclStmnt")
            assert isinstance(named_qual_type, IdentifiedQualType)
            apply_gnu_attributes_to_decl(named_qual_type, base_decl_attrs)
            if named_qual_type.name is None:
                raise ParsingError(tokens, c, "Expected a name for typedef")
            elif tokens[c].str == "," or tokens[c].str == ";":
                self.id_qual_types.append(named_qual_type)
                context.new_type(
                    named_qual_type.name,
                    TypeDefCtxMember(
                        named_qual_type.name, context, named_qual_type.typ
                    ),
                )
                c += 1
                if tokens[c].str == ";":
                    break
            else:
                raise ParsingError(
                    tokens, c, "Expected a ',' or ';' to delimit the typedef"
                )
        return c


from ..ParsingError import ParsingError
from ..type.CompileContext import CompileContext
from ..type.GNUAttributes import GNUAttributes
from ..type.get_base_type import get_base_type
from ..type.IdentifiedQualType import IdentifiedQualType
from ..type.proc_typed_decl import proc_typed_decl
from ..type.gnu_attrs import apply_gnu_attributes_to_decl
from ...PrettyRepr import get_pretty_repr
from ...lexer.lexer import Token
from ...ParseConstants import OPEN_GROUPS, CLOSE_GROUPS
from ..type.TypeDefCtxMember import TypeDefCtxMember
