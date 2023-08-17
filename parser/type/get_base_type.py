from typing import List, Optional, Tuple


def get_base_type(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
) -> Tuple[Optional["BaseType"], int]:
    main_start = c
    str_name = []
    base_type = None
    is_prim = False
    while c < end:
        if tokens[c].type_id == TokenType.NAME and tokens[c].str in KEYWORDS:
            meta_type_type = -1
            try:
                meta_type_type = META_TYPE_LST.index(tokens[c].str)
            except ValueError:
                pass
            if meta_type_type != -1:
                c += 1
                cls = MetaTypeCtors[meta_type_type](context)
                c = cls.build(tokens, c, end, context)
                cls = merge_type_context(cls, context)
                assert cls is not None, "ISSUE with MergeType_Context"
                if base_type is None and not is_prim:
                    base_type = cls
                else:
                    # raise ParsingError(tokens, c, "Cannot specify different typenames as one type")
                    return None, main_start
            elif tokens[c].str == "typename":
                c += 1
                base_name, c = try_get_as_name(tokens, c, end, context)
                if base_name is None:
                    raise ParsingError(tokens, c, "Expected name after 'typename'")
                name = "".join(map(tok_to_str, base_name))
                cls = context.scoped_get(name)
                if not cls.is_type():
                    raise ParsingError(
                        tokens,
                        c,
                        "Expected a typename to follow 'typename', got %s" % name,
                    )
                if base_type is None and not is_prim:
                    base_type = cls.get_underlying_type()
                else:
                    raise ParsingError(
                        tokens, c, "Cannot specify different typenames as one type"
                    )
            elif tokens[c].str in PRIM_TYPE_WORDS:
                str_name.append(tokens[c].str)
                is_prim = True
                c += 1
            elif tokens[c].str in MODIFIERS:
                str_name.append(tokens[c].str)
                c += 1
            else:
                # raise ParsingError(tokens, c, "Keyword not allowed in declaration")
                return None, main_start
        else:
            start = c
            base_name, c = try_get_as_name(tokens, c, end, context)
            if base_name is None and base_type is None and not is_prim:
                # raise ParsingError(tokens, c, "Expected name after 'typename'")
                return None, main_start
            elif base_name is None:
                break
            elif is_prim or base_type is not None:
                # v = context.ScopedGet_Strict("".join(map(TokToStr, base_name)))
                # if v is not None: raise ParsingError(tokens, c, "??Redefinition ?")
                c = start  # Do something about the name
                break
            elif not is_prim and base_type is None:
                v = context.scoped_get("".join(map(tok_to_str, base_name)))
                if v is None:
                    raise ParsingError(tokens, c, "Undefined Identifier")
                elif v.is_type():
                    base_type = v.get_underlying_type()
                else:
                    return None, main_start
            else:
                raise ParsingError(tokens, c, "Unrecognized if path")
    if is_prim:
        str_name.sort(
            key=lambda k: (
                2
                if k in SINGLE_TYPES1
                else (0 if k in BASE_TYPE_MODS else (1 if k in INT_TYPES1 else 3))
            )
        )
        c0 = len(str_name)
        while c0 > 0:
            c0 -= 1
            if str_name[c0] in PRIM_TYPE_WORDS:
                c0 += 1
                break
        base_type = PrimitiveType.from_str_name(str_name[:c0])
        # assert c0 == len(str_name), "expected c0 = len(str_name), c0=%u, str_name=%r" % (c0, str_name)
        str_name = str_name[c0:]
    if base_type is None:
        print("BASE_TYPE NONE:", tokens[c - 2])
    assert isinstance(base_type, BaseType), "type = %s" % base_type.__class__.__name__
    for s in str_name:
        base_type = QualType(QualType.QUAL_Dct[s], base_type)
    return base_type, c


from .BaseType import BaseType
from .PrimitiveType import PrimitiveType
from ..constants import (
    PRIM_TYPE_WORDS,
    SINGLE_TYPES1,
    BASE_TYPE_MODS,
    KEYWORDS,
    INT_TYPES1,
    MODIFIERS,
)
from .QualType import QualType
from ..ParsingError import ParsingError
from ..try_get_as_name import try_get_as_name
from ...lexer.lexer import tok_to_str, Token, TokenType
from ...ParseConstants import META_TYPE_LST
from ..context.CompileContext import CompileContext
from ..context.merge_type_context import merge_type_context
from .ClassType import ClassType
from .StructType import StructType
from .UnionType import UnionType
from .EnumType import EnumType


MetaTypeCtors = [EnumType, ClassType, StructType, UnionType]
