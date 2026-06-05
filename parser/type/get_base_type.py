from typing import List, Optional, Tuple


def get_base_type(
    tokens: List["Token"],
    c: int,
    end: int,
    context: "CompileContext",
    decl_attrs: Optional["GNUAttributes"] = None,
) -> Tuple[Optional["BaseType"], int]:
    main_start = c
    str_name = []
    base_type = None
    is_prim = False
    pending_gnu_attrs = GNUAttributes()
    while c < end:
        if tokens[c].type_id == TokenType.NAME and tokens[c].str == "__attribute__":
            c1, specs = parse_single_gnu_attr_specs(tokens, c, end)
            if (
                c1 < end
                and tokens[c1].type_id == TokenType.NAME
                and tokens[c1].str in META_TYPE_LST
                and base_type is None
                and not is_prim
            ):
                for spec in specs:
                    if spec.attribute.name in GNU_TYPE_PREFIX_ATTRS:
                        dispatch_gnu_attr_spec(pending_gnu_attrs, spec, context)
                    elif decl_attrs is not None:
                        dispatch_gnu_attr_spec(decl_attrs, spec, context)
                c = c1
                continue
            if decl_attrs is not None:
                for spec in specs:
                    dispatch_gnu_attr_spec(decl_attrs, spec, context)
                c = c1
                continue
            if base_type is not None or is_prim or len(str_name) > 0:
                break
            return None, main_start
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
                apply_gnu_attributes_to_type(cls, pending_gnu_attrs)
                pending_gnu_attrs = GNUAttributes()
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
            elif tokens[c].str in ("_Noreturn",):
                # C11 function specifier — no-op, silently skip.
                c += 1
            elif tokens[c].str == "typeof":
                # typeof(type-name) or typeof(expression) — compile-time type query,
                # no code generation; yields the unqualified value type of its argument.
                c += 1  # consume 'typeof'
                if c >= end or tokens[c].str != "(":
                    raise ParsingError(tokens, c, "Expected '(' after 'typeof'")
                paren_pos = c
                c += 1  # consume '('
                # Locate the matching ')' tracking nested groups.
                lvl = 1
                inner_end = c
                while inner_end < end and lvl > 0:
                    s = tokens[inner_end].str
                    if s in OPEN_GROUPS:
                        lvl += 1
                    elif s in CLOSE_GROUPS:
                        lvl -= 1
                    if lvl > 0:
                        inner_end += 1
                if lvl != 0:
                    raise ParsingError(tokens, paren_pos, "Unmatched '(' in typeof")
                # inner_end points to the closing ')'.
                # 1. Try to parse the argument as a type name (no declarator name).
                t_typeof = None
                try:
                    type_decl, c2 = proc_typed_decl(tokens, c, inner_end, context)
                    if (
                        type_decl is not None
                        and c2 == inner_end
                        and type_decl.name is None
                    ):
                        t_typeof = type_decl.typ
                except Exception:
                    pass
                if t_typeof is None:
                    # 2. Fall back: parse as expression and take its annotated type.
                    expr, _c2 = get_expr(tokens, c, None, inner_end, context)
                    if expr is None:
                        raise ParsingError(
                            tokens, c, "Expected type-name or expression in typeof"
                        )
                    # Strip QUAL_REF (typeof yields a value type, not a reference).
                    pt = get_base_prim_type(expr.t_anot)
                    if (
                        pt.type_class_id == TypeClass.QUAL
                        and isinstance(pt, QualType)
                        and pt.qual_id == QualType.QUAL_REF
                    ):
                        pt = get_base_prim_type(pt.tgt_type)
                    t_typeof = pt
                c = inner_end + 1  # advance past ')'
                if base_type is None and not is_prim:
                    base_type = t_typeof
                else:
                    return None, main_start
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


from .BaseType import BaseType, TypeClass
from .PrimitiveType import PrimitiveType
from .QualType import QualType
from .GNUAttributes import GNUAttributes
from .gnu_attrs import apply_gnu_attributes_to_type
from ..constants import (
    BASE_TYPE_MODS,
    INT_TYPES1,
    KEYWORDS,
    MODIFIERS,
    PRIM_TYPE_WORDS,
    SINGLE_TYPES1,
)
from ..try_get_as_name import try_get_as_name
from ..ParsingError import ParsingError
from .gnu_attrs import (
    GNU_TYPE_PREFIX_ATTRS,
    parse_single_gnu_attr_specs,
    dispatch_gnu_attr_spec,
)
from ...lexer.lexer import Token, TokenType, tok_to_str
from .CompileContext import CompileContext
from ...ParseConstants import (
    CLOSE_GROUPS,
    META_TYPE_LST,
    OPEN_GROUPS,
)
from .qual_atomic_type_util import get_base_prim_type
from ..expr.get_expr import get_expr
from .EnumType import EnumType
from .ClassType import ClassType
from .StructType import StructType
from .UnionType import UnionType
from .merge_type_context import merge_type_context
from .proc_typed_decl import proc_typed_decl

MetaTypeCtors = [EnumType, ClassType, StructType, UnionType]
