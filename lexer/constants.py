from enum import Enum


class TokenType(Enum):
    BLANK = 0
    WS = 1
    NAME = 2
    DEC_INT = 3
    FLOAT = 4
    HEX_INT = 5
    OCT_INT = 6
    BIN_INT = 7
    OPERATOR = 8
    BRK_OP = 9
    UNI_QUOTE = 10
    DBL_QUOTE = 11
    BACK_SLASH = 12
    LN_COMMENT = 13  # TODO: add Corresponding comment classes
    BLK_COMMENT = 14
    # intermediate token types (pre-parse)
    PLUS_MINUS = 15
    DOT = 16
    # post-parse token types
    ARRAY_LEN = 15

token_class_abreviation = {
    TokenType.BLANK: "Bln",
    TokenType.WS: "WSp",
    TokenType.NAME: "Nam",
    TokenType.DEC_INT: "Dec",
    TokenType.FLOAT: "Flt",
    TokenType.HEX_INT: "Hex",
    TokenType.OCT_INT: "Oct",
    TokenType.BIN_INT: "Bin",
    TokenType.OPERATOR: "Opr",
    TokenType.BRK_OP: "Brk",
    TokenType.UNI_QUOTE: "SQu",
    TokenType.DBL_QUOTE: "DQu",
    TokenType.BACK_SLASH: "BSl",
    TokenType.LN_COMMENT: "LnC",
    TokenType.BLK_COMMENT: "BlC",
    TokenType.PLUS_MINUS: "PMC",
    TokenType.DOT: "Dot",
    TokenType.ARRAY_LEN: "ArL"
}


LST_OPS = {
    "+",  "-",  "*",  "/",  "%",  "&",  "|",  "^",  "<<",  ">>",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=",
    "<",  ">",  "!",  "=", ":",
    "<=", ">=", "!=", "==", "::",
    "&&", "||", "~", "++", "--", "->"}