from typing import List, Tuple, Optional

GNU_TYPE_PREFIX_ATTRS = {"packed", "aligned"}


def split_top_level_commas(tokens: List["Token"]) -> List[List["Token"]]:
    groups = []
    start = 0
    lvl = 0
    for c, tok in enumerate(tokens):
        s = tok.str
        if s in OPEN_GROUPS:
            lvl += 1
        elif s in CLOSE_GROUPS:
            lvl -= 1
        elif s == "," and lvl == 0:
            groups.append(tokens[start:c])
            start = c + 1
    groups.append(tokens[start:])
    return [group for group in groups if len(group) > 0]


def parse_attribute_segment(
    tokens: List["Token"],
) -> Optional["ParsedAttributeSpec"]:
    tokens = _unwrap_paren_wrappers(tokens)
    if len(tokens) == 0 or tokens[0].type_id != TokenType.NAME:
        return None
    attr_name = _normalize_gnu_attr_name(tokens[0].str)
    args = []
    arg_tokens = []
    if len(tokens) > 1:
        if (
            tokens[1].str != "("
            or tokens[-1].str != ")"
            or not _fully_wrapped_in_parens(tokens[1:])
        ):
            return None
        arg_tokens = split_top_level_commas(tokens[2:-1])
        args = ["".join(map(tok_to_str, group)) for group in arg_tokens]
    return ParsedAttributeSpec(Attribute(attr_name, args), arg_tokens)


def skip_gnu_attrs(tokens: List["Token"], c: int, end: int) -> int:
    while (
        c < end
        and tokens[c].type_id == TokenType.NAME
        and tokens[c].str == "__attribute__"
    ):
        c, _specs = parse_single_gnu_attr_specs(tokens, c, end)
    return c


def _normalize_gnu_attr_name(name: str) -> str:
    if len(name) > 4 and name.startswith("__") and name.endswith("__"):
        return name[2:-2]
    return name


def _fully_wrapped_in_parens(tokens: List["Token"]) -> bool:
    if len(tokens) < 2 or tokens[0].str != "(" or tokens[-1].str != ")":
        return False
    depth = 0
    for c, tok in enumerate(tokens):
        if tok.str == "(":
            depth += 1
        elif tok.str == ")":
            depth -= 1
            if depth == 0:
                return c == len(tokens) - 1
    return False


def _unwrap_paren_wrappers(tokens: List["Token"]) -> List["Token"]:
    while _fully_wrapped_in_parens(tokens):
        tokens = tokens[1:-1]
    return tokens


def parse_single_gnu_attr_specs(
    tokens: List["Token"], c: int, end: int
) -> Tuple[int, List["ParsedAttributeSpec"]]:
    specs = []
    if c >= end or tokens[c].str != "__attribute__":
        return c, specs
    c += 1
    if c >= end or tokens[c].str != "(":
        return c, specs
    lvl = 1
    c += 1
    attr_tokens = []
    while c < end and lvl > 0:
        s = tokens[c].str
        if s == "(":
            lvl += 1
        elif s == ")":
            lvl -= 1
        if lvl > 0:
            attr_tokens.append(tokens[c])
        c += 1
    attr_tokens = _unwrap_paren_wrappers(attr_tokens)
    for segment in split_top_level_commas(attr_tokens):
        spec = parse_attribute_segment(segment)
        if spec is not None:
            specs.append(spec)
    return c, specs


def consume_gnu_attrs(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
) -> Tuple[int, "GNUAttributes"]:
    attrs = GNUAttributes()
    while (
        c < end
        and tokens[c].type_id == TokenType.NAME
        and tokens[c].str == "__attribute__"
    ):
        c, specs = parse_single_gnu_attr_specs(tokens, c, end)
        for spec in specs:
            dispatch_gnu_attr_spec(attrs, spec, context)
    return c, attrs


def apply_gnu_attributes_to_type(typ: "BaseType", attrs: "GNUAttributes") -> "BaseType":
    apply_gnu_attributes_to_decl(typ, attrs)
    if isinstance(typ, StructType):
        if attrs.packed:
            typ.is_packed = True
        if attrs.align_override is not None:
            cur = 0 if typ.align_override is None else typ.align_override
            typ.align_override = max(cur, attrs.align_override)
        typ._invalidate_layout()
    elif isinstance(typ, UnionType):
        if attrs.packed:
            typ.is_packed = True
        if attrs.align_override is not None:
            cur = 0 if typ.align_override is None else typ.align_override
            typ.align_override = max(cur, attrs.align_override)
    elif isinstance(typ, ClassType) and attrs.align_override is not None:
        cur = 0 if typ.align_override is None else typ.align_override
        typ.align_override = max(cur, attrs.align_override)
    return typ


def apply_gnu_attributes_to_decl(decl: object, attrs: "GNUAttributes") -> object:
    if not hasattr(decl, "attributes") or getattr(decl, "attributes") is None:
        decl.attributes = []
    decl.attributes.extend(attrs.attributes)
    if attrs.align_override is not None and hasattr(decl, "align_override"):
        cur = getattr(decl, "align_override")
        cur = 0 if cur is None else cur
        decl.align_override = max(cur, attrs.align_override)
    if attrs.section_name is not None and hasattr(decl, "section_name"):
        cur = getattr(decl, "section_name")
        if cur is not None and cur != attrs.section_name:
            raise TypeError("conflicting section attributes")
        decl.section_name = attrs.section_name
    return decl


def eval_attr_align_expr(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
) -> Optional[int]:
    expr, c_expr = get_expr(tokens, c, None, end, context)
    if expr is None or c_expr != end:
        return None
    value = eval_const_expr(expr)
    if isinstance(value, StaticAddress) or value is None:
        return None
    return int(value)


def dispatch_gnu_attr_spec(
    attrs: "GNUAttributes",
    spec: "ParsedAttributeSpec",
    context: "CompileContext",
) -> None:
    attr = spec.attribute
    attrs.attributes.append(attr)
    if attr.name == "packed":
        attrs.packed = True
    elif attr.name == "aligned":
        if len(spec.arg_tokens) > 0:
            align = eval_attr_align_expr(
                spec.arg_tokens[0], 0, len(spec.arg_tokens[0]), context
            )
            if align is not None and align > 0:
                cur = 0 if attrs.align_override is None else attrs.align_override
                attrs.align_override = max(cur, align)
    elif attr.name == "section":
        if (
            len(spec.arg_tokens) != 1
            or len(spec.arg_tokens[0]) != 1
            or spec.arg_tokens[0][0].type_id != TokenType.DBL_QUOTE
        ):
            raise TypeError("section attribute requires one string literal")
        attrs.section_name = str(LiteralExpr.literal_to_value(spec.arg_tokens[0][0]))
        if not attrs.section_name or "\0" in attrs.section_name:
            raise ValueError("section attribute name must be non-empty")
    elif attr.name == "weak":
        attrs.weak = True
    elif attr.name == "noreturn":
        attrs.noreturn = True
    elif attr.name == "always_inline":
        attrs.always_inline = True
    elif attr.name == "noinline":
        attrs.noinline = True
    elif attr.name == "unused":
        attrs.unused = True
    elif attr.name == "deprecated":
        attrs.deprecated = True
    elif attr.name == "format":
        attrs.format_attr = attr
    elif attr.name == "constructor":
        attrs.constructor_attr = attr
    elif attr.name == "destructor":
        attrs.destructor_attr = attr
    else:
        attrs.attributes.pop()


from ...lexer.lexer import Token, TokenType, tok_to_str
from .CompileContext import CompileContext
from .GNUAttributes import GNUAttributes
from .ClassType import ClassType
from .StructType import StructType
from .UnionType import UnionType
from .ParsedAttributeSpec import ParsedAttributeSpec
from ...ParseConstants import (
    CLOSE_GROUPS,
    OPEN_GROUPS,
)
from .Attribute import Attribute
from .BaseType import BaseType
from .StaticAddress import StaticAddress
from ..expr.get_expr import get_expr
from .eval_const_expr import eval_const_expr
from ..expr.LiteralExpr import LiteralExpr
