from typing import List, Optional, Tuple, Union
from .BaseExpr import BaseExpr, ExprType
from ...lexer.constants import TokenType


LITERAL_TYPES = {
    TokenType.DBL_QUOTE,
    TokenType.UNI_QUOTE,
    TokenType.FLOAT,
    TokenType.DEC_INT,
    TokenType.OCT_INT,
    TokenType.HEX_INT,
    TokenType.BIN_INT,
}


class LiteralExpr(BaseExpr):
    expr_id = ExprType.LITERAL
    LIT_INT = 0
    LIT_FLOAT = 1
    LIT_CHR = 2
    LIT_STR = 3
    LIT_BOOL = 4
    LIT_lst = ["LIT_INT", "LIT_FLOAT", "LIT_CHR", "LIT_STR", "LIT_BOOL"]

    @classmethod
    def is_literal_token(cls, tok: "Token") -> bool:
        """
        :param Token tok:
        :rtype: bool
        """
        return tok.type_id in LITERAL_TYPES or (
            tok.type_id == TokenType.NAME and (tok.str == "true" or tok.str == "false")
        )

    @classmethod
    def literal_to_value(cls, tok: "Token") -> Union[str, int, float, bool]:
        s = tok.str
        if tok.type_id == TokenType.DBL_QUOTE:
            vals, uni_spec = cls.parse_str_lit(s)
            return "".join(map(chr, vals))
        elif tok.type_id == TokenType.UNI_QUOTE:
            uni_spec = 0
            if s.startswith("u"):
                uni_spec = 2
            elif s.startswith("U"):
                uni_spec = 3
            elif s.startswith("b"):
                uni_spec = 1
            elif not s.startswith("'"):
                raise ValueError("Unrecognized literal prefix")
            s_q = s.find("'") + 1
            e_q = s.rfind("'")
            lst_res, c1 = cls.parse_char_part(s_q, s, uni_spec)
            if len(lst_res) != 1 or c1 < e_q:
                raise ValueError("Expected only one char")
            return lst_res[0]
        elif tok.type_id == TokenType.BIN_INT:
            assert s.startswith("0b") or s.startswith("0B")
            return int(s[2:], 2)
        elif tok.type_id == TokenType.DEC_INT:
            return int(s)
        elif tok.type_id == TokenType.OCT_INT:
            assert s.startswith("0o") or s.startswith("0O") or s.startswith("0")
            return int(s[2:], 8)
        elif tok.type_id == TokenType.HEX_INT:
            assert s.startswith("0x") or s.startswith("0X")
            return int(s[2:], 16)
        elif tok.type_id == TokenType.FLOAT:
            return float(s)
        elif tok.type_id == TokenType.NAME:
            if s == "true":
                return True
            elif s == "false":
                return False
            else:
                raise ValueError("Expected boolean")

    @classmethod
    def parse_char_part(cls, c, v_lit, uni_spec=0, backslash_strict=True):
        if uni_spec == 0:
            uni_spec = 1
        lst_res = []
        if v_lit[c] == "\\":
            c += 1
            pos = "btnvfr".find(v_lit[c])
            if pos != -1:
                lst_res.append(8 + pos)
                c += 1
            elif v_lit[c] in "\"'\\":
                lst_res.append(ord(v_lit[c]))
                c += 1
            elif v_lit[c].lower() == "x":
                c += 1
                res = int(v_lit[c : c + 2], 16)
                if isinstance(res, str):
                    raise SyntaxError("Expected 2-digit hex: %s" % res)
                assert isinstance(res, int)
                lst_res.append(res)
                c += 2
            elif v_lit[c] == "u" and uni_spec >= 2:
                c += 1
                res = int(v_lit[c : c + 4], 16)
                if isinstance(res, str):
                    raise SyntaxError("Expected 4-digit hex: %s" % res)
                assert isinstance(res, int)
                lst_res.append(res)
                c += 4
            elif v_lit[c] == "U" and uni_spec >= 3:
                c += 1
                res = int(v_lit[c : c + 8], 16)
                if isinstance(res, str):
                    raise SyntaxError("Expected 8-digit hex: %s" % res)
                assert isinstance(res, int)
                lst_res.append(res)
                c += 8
            else:
                v = ord(v_lit[c]) - ord("0")
                if 0 <= v <= 7:
                    c += 1
                    res = 0
                    n = 1
                    while 0 <= v <= 7 and n < 3:
                        res <<= 3
                        res |= v
                        v = ord(v_lit[c]) - ord("0")
                        c += 1
                        n += 1
                    lst_res.append(res)
                elif backslash_strict:
                    raise ValueError("invalid string escape %s" % v_lit[c - 1 : c + 1])
                else:
                    lst_res.extend([ord(v_lit[c - 1]), ord(v_lit[c])])
                    c += 1
        else:
            lst_res.append(ord(v_lit[c]))
            c += 1
        return lst_res, c

    @classmethod
    def parse_str_lit(cls, v_lit, backslash_strict=True):
        s_q = v_lit.find('"')
        e_q = v_lit.rfind('"')
        uni_spec = 0
        is_raw = False
        uni_specs = ["B", "b", "u", "U"]
        for c in range(s_q):
            if v_lit[c] in uni_specs:
                if uni_spec != 0:
                    raise SyntaxError(
                        "cannot specify more than one string type specifier"
                    )
                uni_spec = uni_specs.index(v_lit[c])
                if uni_spec == 0:
                    uni_spec = 1
            elif v_lit[c].lower() == "r":
                if is_raw:
                    raise SyntaxError(
                        "cannot specify 'r' more than once in string type specifier"
                    )
                is_raw = True
        lst_res = []
        c = s_q + 1
        while c < e_q:
            cur_res, c = cls.parse_char_part(c, v_lit, uni_spec, backslash_strict)
            lst_res.extend(cur_res)
        return lst_res, uni_spec

    # init-args added for __repr__
    def __init__(self, t_lit: Optional[int] = None, v_lit: Optional[str] = None):
        self.t_lit = t_lit
        self.v_lit = v_lit
        self.l_val = None

    def pretty_repr(self, pretty_repr_ctx=None):
        c_name = self.__class__.__name__
        rtn = [c_name, "("]
        if isinstance(self.t_lit, int) and 0 <= self.t_lit < len(self.LIT_lst):
            rtn.extend([c_name, ".", self.LIT_lst[self.t_lit]])
        else:
            rtn.extend(get_pretty_repr(self.t_lit, pretty_repr_ctx))
        rtn.extend([","] + get_pretty_repr(self.v_lit, pretty_repr_ctx) + [")"])
        return rtn

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        del end
        del context
        s = tokens[c].str
        if not self.is_literal_token(tokens[c]):
            raise ParsingError(tokens, c, "Expected literal")
        if tokens[c].type_id in {
            TokenType.DEC_INT,
            TokenType.HEX_INT,
            TokenType.BIN_INT,
            TokenType.OCT_INT,
        }:
            self.t_lit = LiteralExpr.LIT_INT
            end_pos = len(s)
            for c0 in range(len(s) - 1, -1, -1):
                if s[c0].isdigit() or ("a" <= s[c0].lower() <= "f"):
                    end_pos = c0 + 1
                    break
            c0 = end_pos
            i_lvl = 0
            unsign = 0
            while c0 < len(s):
                if c0 + 1 < len(s) and s[c0 : c0 + 2].lower() == "ll":
                    if i_lvl != 0:
                        raise ParsingError(
                            tokens, c, "cannot specify 'll' or 'l' more than once"
                        )
                    i_lvl = 2
                    c0 += 1
                elif s[c0].lower() == "u":
                    unsign = 1
                elif s[c0].lower() == "l":
                    if i_lvl != 0:
                        raise ParsingError(
                            tokens, c, "cannot specify 'll' or 'l' more than once"
                        )
                    i_lvl = 1
                else:
                    raise ParsingError(tokens, c, "Invalid suffix")
                c0 += 1
            assert 0 <= i_lvl <= 2
            data = None
            int_base_type = tokens[c].type_id
            if int_base_type == TokenType.DEC_INT:
                data = int(s[:end_pos])
            elif int_base_type == TokenType.HEX_INT:
                data = int(s[2:end_pos], 16)
            elif int_base_type == TokenType.BIN_INT:
                data = int(s[2:end_pos], 2)
            elif int_base_type == TokenType.OCT_INT:
                if s.startswith("0o"):
                    data = int(s[2:end_pos], 8)
                else:
                    data = int(s[1:end_pos], 8)
            assert data is not None
            self.l_val = data
            lst_opts: List[Tuple[PrimitiveTypeId, int]] = (
                [
                    (PrimitiveTypeId.INT_I, unsign),
                    (PrimitiveTypeId.INT_L, unsign),
                    (PrimitiveTypeId.INT_LL, unsign),
                ][i_lvl:]
                if int_base_type == TokenType.DEC_INT or unsign
                else [
                    (PrimitiveTypeId.INT_I, 0),
                    (PrimitiveTypeId.INT_I, 1),
                    (PrimitiveTypeId.INT_L, 0),
                    (PrimitiveTypeId.INT_L, 1),
                    (PrimitiveTypeId.INT_LL, 0),
                    (PrimitiveTypeId.INT_LL, 1),
                ][2 * i_lvl :]
            )
            typ = None
            for TypeCode, Unsigned in lst_opts:
                typ = PrimitiveType.from_type_code(TypeCode, 1 if Unsigned else -1)
                minim = 0
                maxim = 1 << (size_of(typ) * 8)
                if not Unsigned:
                    off = maxim >> 1
                    minim -= off
                    maxim -= off
                if minim <= data < maxim:
                    break
                else:
                    typ = None
            if typ is None:
                raise ParsingError(tokens, c, "Integer too large, Opts = %r" % lst_opts)
            self.t_anot = typ
        elif tokens[c].type_id == TokenType.FLOAT:
            self.t_lit = LiteralExpr.LIT_FLOAT
            end_pos = len(s)
            ch = s[-1].lower()
            if ch == "f":
                ch1 = s[-2].lower()
                if ch1 == "s":
                    ch = ch1
                    end_pos -= 1
            elif ch == "d":
                ch1 = s[-2].lower()
                if ch1 == "l":
                    ch = ch1
                    end_pos -= 1
            if ch == "f":
                end_pos -= 1
                self.t_anot = PrimitiveType.from_type_code(PrimitiveTypeId.FLT_F)
            elif ch == "s":
                end_pos -= 1
                self.t_anot = PrimitiveType.from_str_name(["short", "float"])
            elif ch == "d":
                end_pos -= 1
                self.t_anot = PrimitiveType.from_type_code(PrimitiveTypeId.FLT_D)
            if ch == "l":
                end_pos -= 1
                self.t_anot = PrimitiveType.from_type_code(PrimitiveTypeId.FLT_LD)
            else:
                self.t_anot = PrimitiveType.from_type_code(PrimitiveTypeId.FLT_D)
            self.l_val = float(s[:end_pos])
        elif tokens[c].type_id == TokenType.UNI_QUOTE:
            self.t_lit = LiteralExpr.LIT_CHR
            uni_spec = 0
            if s.startswith("u"):
                uni_spec = 2
            elif s.startswith("U"):
                uni_spec = 3
            elif s.startswith("b"):
                uni_spec = 1
            elif not s.startswith("'"):
                raise ParsingError(tokens, c, "Unrecognized literal prefix")
            ch_type = None
            if uni_spec == 1:
                ch_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C)
            elif uni_spec == 2:
                ch_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C16)
            elif uni_spec == 3:
                ch_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C32)
            if ch_type is None:
                ch_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C)
            s_q = s.find("'") + 1
            e_q = s.rfind("'")
            lst_res, c1 = LiteralExpr.parse_char_part(s_q, s, uni_spec)
            if len(lst_res) != 1:
                raise ParsingError(
                    tokens,
                    c,
                    "Expected one character in character literal: s_q = %u, e_q = %u, c1 = %u, lst_res = %r"
                    % (s_q, e_q, c1, lst_res),
                )
            self.l_val = lst_res[0]
            self.t_anot = QualType(QualType.QUAL_CONST, ch_type)
        elif tokens[c].type_id == TokenType.DBL_QUOTE:
            self.t_lit = LiteralExpr.LIT_STR
            lst_vals, uni_spec = LiteralExpr.parse_str_lit(s)
            self.l_val = lst_vals
            ch_type = None
            if uni_spec == 1:
                ch_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C)
            elif uni_spec == 2:
                ch_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C16)
            elif uni_spec == 3:
                ch_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C32)
            if ch_type is None:
                ch_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C)
            self.t_anot = QualType(
                QualType.QUAL_REF,
                QualType(
                    QualType.QUAL_ARR,
                    QualType(QualType.QUAL_CONST, ch_type),
                    len(lst_vals) + 1,  # plus 1 for null terminator
                ),
            )
        elif tokens[c].type_id == TokenType.NAME:
            self.t_lit = LiteralExpr.LIT_BOOL
            if s == "true":
                self.l_val = True
            elif s == "false":
                self.l_val = False
            else:
                raise ParsingError(
                    tokens, c, "Expected a boolean literal (true or false)"
                )
            self.t_anot = PrimitiveType.from_type_code(PrimitiveTypeId.TYP_BOOL)
        self.v_lit = s
        c += 1
        return c


from ..ParsingError import ParsingError
from ...PrettyRepr import get_pretty_repr
from ..type.types import (
    CompileContext,
    PrimitiveType,
    PrimitiveTypeId,
    QualType,
    size_of,
)
from ...lexer.lexer import Token
