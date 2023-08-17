from ..PyIsaacUtils.TextAlgo import is_non_break_sym, is_breaking_sym
from io import TextIOBase
from typing import Union, Tuple, Optional, List
from .constants import TokenType, LST_OPS


THROW_ON_EOL_QUOTE = True


class Token(object):
    type_id = 0

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.str)

    def __init__(self, s: str, ln: int, col: int):
        self.str = s
        self.line = ln
        self.col = col

    def can_prev_take(self, prev: "Token"):
        return None

    def take(self, cur: "Token") -> Optional["Token"]:
        res = cur.can_prev_take(self)
        if res is None:
            return cur
        assert isinstance(res, type)
        assert issubclass(res, Token)
        if res == self.__class__:
            self.str += cur.str
            return None
        else:
            rtn = res(self.str + cur.str, self.line, self.col)
            return rtn


class LnCommentClass(Token):
    type_id = TokenType.LN_COMMENT
    done = False

    def take(self, cur_cls: Token):
        if self.done:
            return cur_cls
        else:
            self.str += cur_cls.str
            self.done = self.str.endswith("\n")
            return None


class BlkCommentClass(Token):
    type_id = TokenType.BLK_COMMENT
    done = False

    def take(self, cur_cls: Token):
        if self.done:
            return cur_cls
        else:
            self.str += cur_cls.str
            self.done = self.str.endswith("*/")
            return None


class UniQuoteClass(Token):
    type_id = TokenType.UNI_QUOTE
    done = False
    backslash = False

    def take(self, cur_cls: Token):
        if self.done:
            return cur_cls
        else:
            if THROW_ON_EOL_QUOTE and "\n" in cur_cls.str and not self.backslash:
                raise ValueError(
                    'unexpected EOL before closing "\'" at position %u:%u'
                    % (self.line + 1, self.col + 1)
                )
            self.str += cur_cls.str
            if cur_cls.str == "\\":
                self.backslash = not self.backslash
            elif cur_cls.str == "'" and not self.backslash:
                self.done = True
            else:
                self.backslash = False
            return None

    def can_prev_take(self, prev_cls: Token):
        if prev_cls.type_id == TokenType.NAME:
            return UniQuoteClass
        else:
            return None


class DblQuoteClass(Token):
    type_id = TokenType.DBL_QUOTE
    done = False
    backslash = False

    def take(self, cur_cls: Token):
        if self.done:
            return cur_cls
        else:
            if THROW_ON_EOL_QUOTE and "\n" in cur_cls.str and not self.backslash:
                raise ValueError(
                    "unexpected EOL before closing '\"' at position %u:%u"
                    % (self.line, self.col)
                )
            self.str += cur_cls.str
            if cur_cls.str == "\\":
                self.backslash = not self.backslash
            elif cur_cls.str == '"' and not self.backslash:
                self.done = True
            else:
                self.backslash = False
            return None

    def can_prev_take(self, prev_cls: Token):
        if prev_cls.type_id == TokenType.NAME:
            return UniQuoteClass
        else:
            return None


class BackslashClass(Token):
    type_id = TokenType.BACK_SLASH
    Done = False

    def take(self, cur_cls: Token):
        if self.Done:
            return cur_cls
        rtn = super(BackslashClass, self).take(cur_cls)
        if rtn is self and len(self.Str) == 2:
            self.done = True
        return rtn


class BlankClass(Token):
    type_id = TokenType.BLANK

    def __init__(self, ln: int, col: int):
        super(BlankClass, self).__init__("", ln, col)

    def __repr__(self):
        return self.__class__.__name__ + "()"

    def can_prev_take(self, prev_cls: Token):
        return prev_cls.__class__


def promote_type(cur_cls: Token) -> Token:
    if cur_cls.type_id == TokenType.DOT:
        return BreakSymClass(cur_cls.str, cur_cls.line, cur_cls.col)
    elif cur_cls.type_id == TokenType.PLUS_MINUS:
        return OperatorClass(cur_cls.str, cur_cls.line, cur_cls.col)
    else:
        return cur_cls


def classify(ch, ln, col):
    """

    :param str ch:
    :param int ln:
    :param int col:
    :rtype: Token
    """
    if ch.isspace():
        return WSClass(ch, ln, col)
    elif ch.isdigit():
        return DecIntClass(ch, ln, col)
    elif ch.isalpha() or ch in ["$", "_"]:
        return NameClass(ch, ln, col)
    elif ch in {"+", "-"}:
        return PlusMinusClass(ch, ln, col)
    elif ch == ".":
        return DotClass(ch, ln, col)
    elif ch == "'":
        return UniQuoteClass(ch, ln, col)
    elif ch == '"':
        return DblQuoteClass(ch, ln, col)
    elif ch == "\\":
        return BackslashClass(ch, ln, col)
    elif is_non_break_sym(ch):
        return OperatorClass(ch, ln, col)
    elif is_breaking_sym(ch):
        return BreakSymClass(ch, ln, col)
    else:
        raise SyntaxError(
            "Unrecognized character: %r at Line:Col = %u:%u" % (ch, ln, col)
        )


class DotClass(Token):
    type_id = TokenType.DOT

    def can_prev_take(self, prev_cls):
        Rtn = super(DotClass, self).can_prev_take(prev_cls)
        if Rtn is not None:
            return Rtn
        if prev_cls.type_id in {TokenType.DEC_INT}:
            return DecimalClass
        return None


class WSClass(Token):
    type_id = TokenType.WS

    def can_prev_take(self, prev_cls):
        Rtn = super(WSClass, self).can_prev_take(prev_cls)
        if Rtn is not None:
            return Rtn
        if prev_cls.type_id == self.type_id:
            return WSClass
        else:
            return None


class DecimalClass(Token):
    type_id = TokenType.FLOAT

    def can_prev_take(self, prev_cls):
        Rtn = super(DecimalClass, self).can_prev_take(prev_cls)
        if Rtn is not None:
            return Rtn
        return None


class HexIntClass(Token):
    type_id = TokenType.HEX_INT


class BinIntClass(Token):
    type_id = TokenType.BIN_INT


class OctIntClass(Token):
    type_id = TokenType.OCT_INT


class DecIntClass(Token):
    type_id = TokenType.DEC_INT

    def can_prev_take(self, prev_cls):
        Rtn = super(DecIntClass, self).can_prev_take(prev_cls)
        if Rtn is not None:
            return Rtn
        if prev_cls.type_id == TokenType.DEC_INT and prev_cls.str == "0":
            return OctIntClass
        elif prev_cls.type_id in {
            TokenType.NAME,
            TokenType.OCT_INT,
            TokenType.BIN_INT,
            TokenType.DEC_INT,
            TokenType.FLOAT,
            TokenType.HEX_INT,
        }:
            return prev_cls.__class__
        elif prev_cls.type_id == TokenType.DOT:
            return DecimalClass


class NameClass(Token):
    type_id = TokenType.NAME

    def can_prev_take(self, prev_cls):
        rtn = super(NameClass, self).can_prev_take(prev_cls)
        if rtn is not None:
            return rtn
        if prev_cls.type_id in {
            TokenType.DEC_INT,
            TokenType.FLOAT,
        } and self.str.lower() in {"e", "j"}:
            return DecimalClass
        elif prev_cls.type_id == TokenType.DEC_INT and prev_cls.str == "0":
            cmp = self.str.lower()
            if cmp == "x":
                return HexIntClass
            elif cmp == "o":
                return OctIntClass
            elif cmp == "b":
                return BinIntClass
        elif prev_cls.type_id in {
            TokenType.NAME,
            TokenType.FLOAT,
            TokenType.HEX_INT,
            TokenType.DEC_INT,
            TokenType.OCT_INT,
            TokenType.BIN_INT,
        }:
            return prev_cls.__class__
        return None


class OperatorClass(Token):
    type_id = TokenType.OPERATOR

    def can_prev_take(self, prev_cls):
        rtn = super(OperatorClass, self).can_prev_take(prev_cls)
        if rtn is not None:
            return rtn
        if prev_cls.type_id in {TokenType.PLUS_MINUS, TokenType.OPERATOR}:
            test = prev_cls.str + self.str
            if test == "//":
                return LnCommentClass
            elif test == "/*":
                return BlkCommentClass
            if any(map(lambda x: x.startswith(test), LST_OPS)):
                return OperatorClass
            # else return None (fall through)
        return None


class PlusMinusClass(Token):
    type_id = TokenType.PLUS_MINUS

    def can_prev_take(self, prev_cls):
        rtn = super(PlusMinusClass, self).can_prev_take(prev_cls)
        if rtn is not None:
            return rtn
        if (prev_cls.type_id in {TokenType.DEC_INT, TokenType.FLOAT}) and prev_cls.str[
            -1
        ].lower() == "e":
            return DecimalClass
        elif prev_cls.type_id in {TokenType.OPERATOR, TokenType.PLUS_MINUS}:
            test = prev_cls.str + self.str
            if any(map(lambda x: x.startswith(test), LST_OPS)):
                return OperatorClass
            # else return None (fall through)
        return None


class BreakSymClass(Token):
    type_id = TokenType.BRK_OP

    def can_prev_take(self, prev_cls):
        rtn = super(BreakSymClass, self).can_prev_take(prev_cls)
        if rtn is not None:
            return rtn
        return None


def cls_brk_lexer(str_data):
    c = 0
    ln = 0
    col = 0
    lst_cls_tokens = []
    try:
        lst_cls_tokens.append(classify(str_data[c], ln, col))
        if str_data[c] == "\n":
            ln += 1
            col = 0
        elif str_data[c] == "\t":
            col += 4
        else:
            col += 1
        c += 1
        next_cls = classify(str_data[c], ln, col)
        my_end = len(str_data) - 1
        cur_cls = lst_cls_tokens[-1]
        while c < my_end:
            prev_cls = cur_cls
            cur_cls = next_cls
            next_cls = classify(str_data[c + 1], ln, col)
            test = prev_cls.take(cur_cls)
            if test is None:
                cur_cls = prev_cls
            elif test is cur_cls:
                lst_cls_tokens.append(cur_cls)
            else:
                lst_cls_tokens[-1] = test
                cur_cls = test
            if str_data[c] == "\n":
                ln += 1
                col = 0
            elif str_data[c] == "\t":
                col += 4
            else:
                col += 1
            c += 1
        prev_cls = cur_cls
        cur_cls = next_cls
        next_cls = BlankClass(ln, col)
        test = prev_cls.take(cur_cls)
        if test is None:
            pass
        elif test is cur_cls:
            lst_cls_tokens.append(cur_cls)
        else:
            lst_cls_tokens[-1] = test
    except SyntaxError as exc:
        raise exc.__class__(exc.text + " at (Line: Column) %u: %u" % (ln, col))
    return list(map(promote_type, lst_cls_tokens))


class BaseSource(object):
    def read(self, n_chars: int) -> str:
        raise NotImplementedError("Not Implemented")

    def get_line_and_col(self) -> Tuple[int, int]:
        raise NotImplementedError("Not Implemented")


class StringSource(BaseSource):
    __slots__ = ["data", "index", "line", "col"]

    def __init__(self, data: str):
        self.data = data
        self.index = 0
        self.line = 1
        self.col = 0

    def read(self, n_chars: int) -> str:
        index = self.index
        data = self.data
        new_index = min(index + n_chars, len(data))
        self.index = new_index
        out = data[index:new_index]
        n = out.count("\n")
        if n:
            self.line += n
            pos = out.rfind("\n") + 1
            self.col = len(out) - pos + out.count("\t", pos) * 3
        else:
            self.col += len(out) + out.count("\t") * 3
        return out

    def get_line_and_col(self) -> Tuple[int, int]:
        return self.line, self.col


class FileSource(BaseSource):
    __slots__ = ["fl", "line", "col"]

    def __init__(self, fl: TextIOBase):
        self.fl = fl
        self.line = 1
        self.col = 0

    def read(self, n_chars: int) -> str:
        out = self.fl.read(n_chars)
        n = out.count("\n")
        if n:
            self.line += n
            pos = out.rfind("\n") + 1
            self.col = len(out) - pos + out.count("\t", pos) * 3
        else:
            self.col += len(out) + out.count("\t") * 3
        return out

    def get_line_and_col(self) -> Tuple[int, int]:
        return self.line, self.col


class ClassBreakLexer(object):
    def __init__(self, default_src: Optional[BaseSource] = None):
        self.cur_tok = None
        self.default_src = default_src

    def get_token(self, src: Optional[BaseSource] = None) -> Optional[Token]:
        if src is None:
            src = self.default_src
        if src is None:
            raise ValueError("No data source to tokenize")
        assert isinstance(src, BaseSource)
        res_tok = None
        while res_tok is None:
            line, col = src.get_line_and_col()
            ch = src.read(1)
            if len(ch) == 0:
                if self.cur_tok is None:
                    break
                res_tok = self.cur_tok
                self.cur_tok = None
                continue
            tok = classify(ch, line, col)
            if self.cur_tok is None:
                self.cur_tok = tok
                continue
            else:
                new_tok = self.cur_tok.take(tok)
            if new_tok is None:  # cur_tok was merged with tok in place
                pass
            elif new_tok is tok:  # cur_tok rejected tok and as such should break
                res_tok = self.cur_tok
                self.cur_tok = new_tok
            else:  # cur_tok merged with tok to make new_tok
                self.cur_tok = new_tok
        return res_tok


def is_not_ign_tok(tok: Token) -> bool:
    """
    returns True if `tok` is not supposed to be ignored by the parser
    it returns False only for comments and whitespace
    """
    return (
        tok.type_id != TokenType.WS
        and tok.type_id != TokenType.BLK_COMMENT
        and tok.type_id != TokenType.LN_COMMENT
    )


def is_ign_tok(tok: Token) -> bool:
    """
    returns True if `tok` is supposed to be ignored by the parser
    it returns True only for comments and whitespace
    """
    return (
        tok.type_id == TokenType.WS
        or tok.type_id == TokenType.BLK_COMMENT
        or tok.type_id == TokenType.LN_COMMENT
    )


def get_list_tokens(data: str) -> List[Token]:
    n = 64
    lst_tokens = [None] * 64
    src = StringSource(data) if isinstance(data, str) else FileSource(data)
    lexer = ClassBreakLexer(src)
    token = lexer.get_token()
    tok_c = 0
    while token is not None:
        if is_ign_tok(token):
            token = lexer.get_token()
            continue
        if tok_c >= n:
            lst_tokens.extend([None] * n)
            n <<= 1
        lst_tokens[tok_c] = token
        tok_c += 1
        token = lexer.get_token()
    return lst_tokens[:tok_c]


def tok_to_str(tok: Token) -> str:
    return tok.str
