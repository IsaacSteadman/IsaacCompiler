from enum import Enum


class TokenClass(Enum):
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
    TokenClass.BLANK: "Bln",
    TokenClass.WS: "WSp",
    TokenClass.NAME: "Nam",
    TokenClass.DEC_INT: "Dec",
    TokenClass.FLOAT: "Flt",
    TokenClass.HEX_INT: "Hex",
    TokenClass.OCT_INT: "Oct",
    TokenClass.BIN_INT: "Bin",
    TokenClass.OPERATOR: "Opr",
    TokenClass.BRK_OP: "Brk",
    TokenClass.UNI_QUOTE: "SQu",
    TokenClass.DBL_QUOTE: "DQu",
    TokenClass.BACK_SLASH: "BSl",
    TokenClass.LN_COMMENT: "LnC",
    TokenClass.BLK_COMMENT: "BlC",
    TokenClass.PLUS_MINUS: "PMC",
    TokenClass.DOT: "Dot",
    TokenClass.ARRAY_LEN: "ArL"
}


LITERAL_TYPES = {
    TokenClass.DBL_QUOTE,
    TokenClass.UNI_QUOTE,
    TokenClass.FLOAT,
    TokenClass.DEC_INT,
    TokenClass.OCT_INT,
    TokenClass.HEX_INT,
    TokenClass.BIN_INT
}


LST_OPS = {
    "+",  "-",  "*",  "/",  "%",  "&",  "|",  "^",  "<<",  ">>",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=",
    "<",  ">",  "!",  "=", ":",
    "<=", ">=", "!=", "==", "::",
    "&&", "||", "~", "++", "--", "->"}


SINGLE_TYPES = {
    "float", "double", "bool",
    "void", "auto"
}
INT_TYPES = {
    "int", "long", "short", "char",
    "wchar_t", "char16_t", "char32_t"
}
BASE_TYPE_MODS = {
    "signed", "unsigned"
}
MODIFIERS = {
    "volatile", "register", "const", "auto"
}
TYPE_WORDS = MODIFIERS | BASE_TYPE_MODS | INT_TYPES | SINGLE_TYPES
META_TYPE_WORDS = {
    "struct", "union", "class", "enum", "typename"
}
KEYWORDS = {
    "while", "for", "do", "if", "else", "switch", "case", "default", "goto",
    "struct", "class", "union", "enum", "typedef",
    "private", "public", "protected", "static",
    "inline", "extern", "using", "namespace", "operator",
    "implicit", "explicit", "template", "typename", "asm"
    } | MODIFIERS | BASE_TYPE_MODS | INT_TYPES | SINGLE_TYPES

class StmntType(Enum):
    CURLY_STMNT = 0
    IF = 1
    WHILE = 2
    FOR = 3
    RTN = 4
    BRK = 5
    CONTINUE = 6
    NAMESPACE = 7
    TYPEDEF = 8
    DECL = 9
    ASM = 10
    SEMI_COLON = 11  # always at end ('expr;' expression)


STMNT_KEY_TO_ID = {
    "{": StmntType.CURLY_STMNT,
    "if": StmntType.IF,
    "while": StmntType.WHILE,
    "for": StmntType.FOR,
    "return": StmntType.RTN,
    "break": StmntType.BRK,
    "continue": StmntType.CONTINUE,
    "namespace": StmntType.NAMESPACE,
    "typedef": StmntType.TYPEDEF,
    "<DECL_STMNT>": StmntType.DECL,
    "asm": StmntType.ASM
}


class ExprType(Enum):
    LITERAL = 0
    NAME = 1
    BIN_OP = 2
    UNI_OP = 3
    CURLY = 4
    CAST = 5
    DOT = 6
    PTR_MEMBER = 7
    FN_CALL = 8
    SPARENTH = 9
    PARENTH = 10
    INLINE_IF = 11
    DECL_VAR = 12

INIT_NONE = 0
INIT_ASSIGN = 1
INIT_PARENTH = 2
INIT_CURLY = 3

LST_INIT_TYPES = [
    "INIT_NONE",
    "INIT_ASSIGN",
    "INIT_PARENTH",
    "INIT_CURLY"
]

INF_CPP_SYMS = (
    {"!": 3, "-": 3, "+": 3, "--": 3, "++": 3, "~": 3, "*": 3, "&": 3},
    {"::": 0,
     ".": 1, "->": 1,
     "*": 5, "/": 5, "%": 5,
     "-": 6, "+": 6,
     "<<": 7, ">>": 7, "<": 8, ">": 8, "<=": 8, ">=": 8,
     "!=": 9, "==": 9,
     "&": 10, "^": 11, "|": 12,
     "&&": 13, "||": 14,
     "=": 15,
     "<<=": 15, ">>=": 15, "^=": 15, "|=": 15, "&=": 15,
     "+=": 15, "-=": 15, "*=": 15, "/=": 15, "%=": 15,
     ",": 16},
    {"++": 1, "--": 1},
    {"(": (2, ")", (0, 2)), "[": (2, "]", (0, 2)), "{": (2, "}", (0, 2)), "?": (3, ":", (3,))},
    {0: 1, 1: 1, 2: 1, 3: 0, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1,
     10: 1, 11: 1, 12: 1, 13: 1, 14: 1, 15: 0, 16: 1})  # boolean: is the priority Left to Right

DCT_FIXES = {
    "!": (3, None, None),
    "--": (3, None, 1),
    "++": (3, None, 1),
    "~": (3, None, None),
    "::": (None, 0, None),
    ".": (None, 1, None), "->": (None, 1, None),
    "*": (3, 5, None), "/": (None, 5, None), "%": (None, 5, None),
    "-": (3, 6, None), "+": (3, 6, None),
    "<<": (None, 7, None), ">>": (None, 7, None),
    "<": (None, 8, None), ">": (None, 8, None), "<=": (None, 8, None), ">=": (None, 8, None),
    "!=": (None, 9, None), "==": (None, 9, None),
    "&": (3, 10, None), "^": (None, 11, None), "|": (None, 12, None),
    "&&": (None, 13, None), "||": (None, 14, None),
    "=": (None, 15, None), "<<=": (None, 15, None), ">>=": (None, 15, None),
    "^=": (None, 15, None), "|=": (None, 15, None), "&=": (None, 15, None),
    "+=": (None, 15, None), "-=": (None, 15, None),
    "*=": (None, 15, None), "/=": (None, 15, None), "%=": (None, 15, None),
    ",": (None, 16, None),
}
LST_LTR_OPS = [True] * 17
LST_LTR_OPS[15] = False


class UnaryExprSubType(Enum):
    BOOL_NOT = 0
    PRE_DEC = 1
    POST_DEC = 2
    PRE_INC = 3
    POST_INC = 4
    BIT_NOT = 5
    STAR = 6
    REFERENCE = 7
    MINUS = 8
    PLUS = 9


class BinaryExprSubType(Enum):
    ASSGN = 0
    ASSGN_MOD = 1
    ASSGN_DIV = 2
    ASSGN_MUL = 3
    ASSGN_MINUS = 4
    ASSGN_PLUS = 5
    ASSGN_AND = 6
    ASSGN_OR = 7
    ASSGN_XOR = 8
    ASSGN_RSHIFT = 9
    ASSGN_LSHIFT = 10
    MUL = 11
    DIV = 12
    MOD = 13
    MINUS = 14
    PLUS = 15
    LT = 16
    GT = 17
    LE = 18
    GE = 19
    NE = 20
    EQ = 21
    AND = 22
    OR = 23
    XOR = 24
    RSHIFT = 25
    LSHIFT = 26
    SS_AND = 27
    SS_OR = 28

ASSIGNMENT_OPS = {
    BinaryExprSubType.ASSGN,
    BinaryExprSubType.ASSGN_MOD,
    BinaryExprSubType.ASSGN_DIV,
    BinaryExprSubType.ASSGN_MUL,
    BinaryExprSubType.ASSGN_MINUS,
    BinaryExprSubType.ASSGN_PLUS,
    BinaryExprSubType.ASSGN_AND,
    BinaryExprSubType.ASSGN_OR,
    BinaryExprSubType.ASSGN_XOR,
    BinaryExprSubType.ASSGN_RSHIFT,
    BinaryExprSubType.ASSGN_LSHIFT
}

CMP_OPS = {
    BinaryExprSubType.LT,
    BinaryExprSubType.GT,
    BinaryExprSubType.LE,
    BinaryExprSubType.GE,
    BinaryExprSubType.NE,
    BinaryExprSubType.EQ
}

DCT_PREFIX_OP_NAME = {
    "!": UnaryExprSubType.BOOL_NOT,
    "--": UnaryExprSubType.PRE_DEC,
    "++": UnaryExprSubType.PRE_INC,
    "~": UnaryExprSubType.BIT_NOT,
    "*": UnaryExprSubType.STAR,
    "&": UnaryExprSubType.REFERENCE,
    "-": UnaryExprSubType.MINUS,
    "+": UnaryExprSubType.PLUS,
}

DCT_POSTFIX_OP_NAME = {
    "--": UnaryExprSubType.POST_DEC,
    "++": UnaryExprSubType.POST_INC,
}

DCT_INFIX_OP_NAME = {
    "=": BinaryExprSubType.ASSGN,
    "%=": BinaryExprSubType.ASSGN_MOD,
    "/=": BinaryExprSubType.ASSGN_DIV,
    "*=": BinaryExprSubType.ASSGN_MUL,
    "-=": BinaryExprSubType.ASSGN_MINUS,
    "+=": BinaryExprSubType.ASSGN_PLUS,
    "&=": BinaryExprSubType.ASSGN_AND,
    "|=": BinaryExprSubType.ASSGN_OR,
    "^=": BinaryExprSubType.ASSGN_XOR,
    ">>=": BinaryExprSubType.ASSGN_RSHIFT,
    "<<=": BinaryExprSubType.ASSGN_LSHIFT,
    "*": BinaryExprSubType.MUL,
    "/": BinaryExprSubType.DIV,
    "%": BinaryExprSubType.MOD,
    "-": BinaryExprSubType.MINUS,
    "+": BinaryExprSubType.PLUS,
    "<": BinaryExprSubType.LT,
    ">": BinaryExprSubType.GT,
    "<=": BinaryExprSubType.LE,
    ">=": BinaryExprSubType.GE,
    "!=": BinaryExprSubType.NE,
    "==": BinaryExprSubType.EQ,
    "&": BinaryExprSubType.AND,
    "|": BinaryExprSubType.OR,
    "^": BinaryExprSubType.XOR,
    ">>": BinaryExprSubType.RSHIFT,
    "<<": BinaryExprSubType.LSHIFT,
    "&&": BinaryExprSubType.SS_AND,
    "||": BinaryExprSubType.SS_OR
}

OPEN_GROUPS = ["{", "[", "(", "?"]
CLOSE_GROUPS = ["}", "]", ")", ":"]
META_TYPE_LST = ["enum", "class", "struct", "union"]
INT_TYPES1 = INT_TYPES.difference({"int"})
assert "int" not in INT_TYPES1
class PrimitiveTypeId(Enum):
    INT_I = 0
    INT_L = 1
    INT_LL = 2
    INT_S = 3
    INT_C = 4
    INT_C16 = 5
    INT_C32 = 6
    INT_WC = 7
    FLT_F = 8
    FLT_D = 9
    FLT_LD = 10
    TYP_BOOL = 11
    TYP_VOID = 12
    TYP_AUTO = 13

LST_TYPE_CODES = [
    "INT_I", "INT_L", "INT_LL", "INT_S", "INT_C", "INT_C16", "INT_C32", "INT_WC",
    "FLT_F", "FLT_D", "FLT_LD", "TYP_BOOL", "TYP_VOID", "TYP_AUTO"]
INT_TYPE_CODES = [
    PrimitiveTypeId.INT_I,
    PrimitiveTypeId.INT_L,
    PrimitiveTypeId.INT_LL,
    PrimitiveTypeId.INT_S,
    PrimitiveTypeId.INT_C,
    PrimitiveTypeId.INT_C16,
    PrimitiveTypeId.INT_C32,
    PrimitiveTypeId.INT_WC,
    PrimitiveTypeId.TYP_BOOL
]
FLT_TYPE_CODES = [
    PrimitiveTypeId.FLT_F,
    PrimitiveTypeId.FLT_D,
    PrimitiveTypeId.FLT_LD
]
# TODO: TYP_FN = ?
SIZE_SIGN_MAP = {
    # k: (Size, Sign)
    PrimitiveTypeId.INT_I: (4, True),
    PrimitiveTypeId.INT_L: (4, True),
    PrimitiveTypeId.INT_LL: (8, True),
    PrimitiveTypeId.INT_S: (2, True),
    PrimitiveTypeId.INT_C: (1, False),
    PrimitiveTypeId.INT_C16: (2, False),
    PrimitiveTypeId.INT_C32: (4, False),
    PrimitiveTypeId.INT_WC: (2, False),
    PrimitiveTypeId.FLT_F: (4, True),
    PrimitiveTypeId.FLT_D: (8, True),
    PrimitiveTypeId.FLT_LD: (16, True),
    PrimitiveTypeId.TYP_BOOL: (1, False),
    PrimitiveTypeId.TYP_VOID: (0, False),
    PrimitiveTypeId.TYP_AUTO: (0, False)
}

class TypeClass(Enum):
    PRIM = 0
    QUAL = 1
    ENUM = 2
    UNION = 3
    CLASS = 4
    STRUCT = 5
    MULTI = 6

SINGLE_TYPES1 = SINGLE_TYPES.union({"int"})
PRIM_TYPE_WORDS = SINGLE_TYPES1 | INT_TYPES1 | BASE_TYPE_MODS

TYPE_SPECS = {"const", "volatile", "register", "auto"}
