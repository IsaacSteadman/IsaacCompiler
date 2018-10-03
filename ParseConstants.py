CLS_BLANK = 0
CLS_WS = 1
CLS_NAME = 2
CLS_DEC_INT = 3
CLS_FLOAT = 4
CLS_HEX_INT = 5
CLS_OCT_INT = 6
CLS_BIN_INT = 7
CLS_OPERATOR = 8
CLS_BRK_OP = 9
CLS_UNI_QUOTE = 10
CLS_DBL_QUOTE = 11
CLS_BACK_SLASH = 12
CLS_LN_COMMENT = 13  # TODO: add Corresponding comment classes
CLS_BLK_COMMENT = 14
# intermediate token types (pre-parse)
CLS_PLUS_MINUS = 15
CLS_DOT = 16
# post-parse token types
CLS_ARRAY_LEN = 15


LITERAL_TYPES = {CLS_DBL_QUOTE, CLS_UNI_QUOTE, CLS_FLOAT, CLS_DEC_INT, CLS_OCT_INT, CLS_HEX_INT, CLS_BIN_INT}


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
    "implicit", "explicit", "template", "typename"
    } | MODIFIERS | BASE_TYPE_MODS | INT_TYPES | SINGLE_TYPES
STMNT_CURLY_STMNT = 0
STMNT_IF = 1
STMNT_WHILE = 2
STMNT_FOR = 3
STMNT_RTN = 4
STMNT_BRK = 5
STMNT_CONTINUE = 6
STMNT_NAMESPACE = 7
STMNT_DECL = 8
STMNT_SEMI_COLON = 9  # always at end ('expr;' expression)
EXPR_LITERAL = 0
EXPR_NAME = 1
EXPR_BIN_OP = 2
EXPR_UNI_OP = 3
EXPR_CURLY = 4
EXPR_CAST = 5
EXPR_DOT = 6
EXPR_PTR_MEMBER = 7
EXPR_FN_CALL = 8
EXPR_SPARENTH = 9
EXPR_PARENTH = 10
EXPR_INLINE_IF = 11
EXPR_DECL_VAR = 12
LST_EXPR_ID_STR = [
    "EXPR_LITERAL",
    "EXPR_NAME",
    "EXPR_BIN_OP",
    "EXPR_UNI_OP",
    "EXPR_CURLY",
    "EXPR_CAST",
    "EXPR_DOT",
    "EXPR_PTR_MEMBER",
    "EXPR_FN_CALL",
    "EXPR_SPARENTH",
    "EXPR_PARENTH",
    "EXPR_INLINE_IF",
    "EXPR_DECL_VAR"
]

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

UNARY_BOOL_NOT = 0
UNARY_PRE_DEC = 1
UNARY_POST_DEC = 2
UNARY_PRE_INC = 3
UNARY_POST_INC = 4
UNARY_BIT_NOT = 5
UNARY_STAR = 6
UNARY_REFERENCE = 7
UNARY_MINUS = 8
UNARY_PLUS = 9

LST_UNI_OP_ID_MAP = [
    "UNARY_BOOL_NOT",
    "UNARY_PRE_DEC",
    "UNARY_POST_DEC",
    "UNARY_PRE_INC",
    "UNARY_POST_INC",
    "UNARY_BIT_NOT",
    "UNARY_STAR",
    "UNARY_REFERENCE",
    "UNARY_MINUS",
    "UNARY_PLUS"]

BINARY_ASSGN = 0
BINARY_ASSGN_MOD = 1
BINARY_ASSGN_DIV = 2
BINARY_ASSGN_MUL = 3
BINARY_ASSGN_MINUS = 4
BINARY_ASSGN_PLUS = 5
BINARY_ASSGN_AND = 6
BINARY_ASSGN_OR = 7
BINARY_ASSGN_XOR = 8
BINARY_ASSGN_RSHIFT = 9
BINARY_ASSGN_LSHIFT = 10
BINARY_MUL = 11
BINARY_DIV = 12
BINARY_MOD = 13
BINARY_MINUS = 14
BINARY_PLUS = 15
BINARY_LT = 16
BINARY_GT = 17
BINARY_LE = 18
BINARY_GE = 19
BINARY_NE = 20
BINARY_EQ = 21
BINARY_AND = 22
BINARY_OR = 23
BINARY_XOR = 24
BINARY_RSHIFT = 25
BINARY_LSHIFT = 26
BINARY_SS_AND = 27
BINARY_SS_OR = 28

ASSIGNMENT_OPS = {
    BINARY_ASSGN,
    BINARY_ASSGN_MOD,
    BINARY_ASSGN_DIV,
    BINARY_ASSGN_MUL,
    BINARY_ASSGN_MINUS,
    BINARY_ASSGN_PLUS,
    BINARY_ASSGN_AND,
    BINARY_ASSGN_OR,
    BINARY_ASSGN_XOR,
    BINARY_ASSGN_RSHIFT,
    BINARY_ASSGN_LSHIFT}
CMP_OPS = {
    BINARY_LT,
    BINARY_GT,
    BINARY_LE,
    BINARY_GE,
    BINARY_NE,
    BINARY_EQ}

LST_BIN_OP_ID_MAP = [
    "BINARY_ASSGN",
    "BINARY_ASSGN_MOD",
    "BINARY_ASSGN_DIV",
    "BINARY_ASSGN_MUL",
    "BINARY_ASSGN_MINUS",
    "BINARY_ASSGN_PLUS",
    "BINARY_ASSGN_AND",
    "BINARY_ASSGN_OR",
    "BINARY_ASSGN_XOR",
    "BINARY_ASSGN_RSHIFT",
    "BINARY_ASSGN_LSHIFT",
    "BINARY_MUL",
    "BINARY_DIV",
    "BINARY_MOD",
    "BINARY_MINUS",
    "BINARY_PLUS",
    "BINARY_LT",
    "BINARY_GT",
    "BINARY_LE",
    "BINARY_GE",
    "BINARY_NE",
    "BINARY_EQ",
    "BINARY_AND",
    "BINARY_OR",
    "BINARY_XOR",
    "BINARY_RSHIFT",
    "BINARY_LSHIFT",
    "BINARY_SS_AND",
    "BINARY_SS_OR"]

DCT_PREFIX_OP_NAME = {
    "!": UNARY_BOOL_NOT,
    "--": UNARY_PRE_DEC,
    "++": UNARY_PRE_INC,
    "~": UNARY_BIT_NOT,
    "*": UNARY_STAR,
    "&": UNARY_REFERENCE,
    "-": UNARY_MINUS,
    "+": UNARY_PLUS,
}

DCT_POSTFIX_OP_NAME = {
    "--": UNARY_POST_DEC,
    "++": UNARY_POST_INC,
}

DCT_INFIX_OP_NAME = {
    "=": BINARY_ASSGN,
    "%=": BINARY_ASSGN_MOD,
    "/=": BINARY_ASSGN_DIV,
    "*=": BINARY_ASSGN_MUL,
    "-=": BINARY_ASSGN_MINUS,
    "+=": BINARY_ASSGN_PLUS,
    "&=": BINARY_ASSGN_AND,
    "|=": BINARY_ASSGN_OR,
    "^=": BINARY_ASSGN_XOR,
    ">>=": BINARY_ASSGN_RSHIFT,
    "<<=": BINARY_ASSGN_LSHIFT,
    "*": BINARY_MUL,
    "/": BINARY_DIV,
    "%": BINARY_MOD,
    "-": BINARY_MINUS,
    "+": BINARY_PLUS,
    "<": BINARY_LT,
    ">": BINARY_GT,
    "<=": BINARY_LE,
    ">=": BINARY_GE,
    "!=": BINARY_NE,
    "==": BINARY_EQ,
    "&": BINARY_AND,
    "|": BINARY_OR,
    "^": BINARY_XOR,
    ">>": BINARY_RSHIFT,
    "<<": BINARY_LSHIFT,
    "&&": BINARY_SS_AND,
    "||": BINARY_SS_OR}

OPEN_GROUPS = ["{", "[", "(", "?"]
CLOSE_GROUPS = ["}", "]", ")", ":"]
META_TYPE_LST = ["enum", "class", "struct", "union"]
INT_TYPES1 = INT_TYPES.difference({"int"})
assert "int" not in INT_TYPES1
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
INT_TYPE_CODES = [INT_I, INT_L, INT_LL, INT_S, INT_C, INT_C16, INT_C32, INT_WC, TYP_BOOL]
FLT_TYPE_CODES = [FLT_F, FLT_D, FLT_LD]
# TODO: TYP_FN = ?
SIZE_SIGN_MAP = {
    # k: (Size, Sign)
    INT_I: (4, True),
    INT_L: (4, True),
    INT_LL: (8, True),
    INT_S: (2, True),
    INT_C: (1, False),
    INT_C16: (2, False),
    INT_C32: (4, False),
    INT_WC: (2, False),
    FLT_F: (4, True),
    FLT_D: (8, True),
    FLT_LD: (16, True),
    TYP_BOOL: (1, False),
    TYP_VOID: (0, False),
    TYP_AUTO: (0, False)
}
TYP_CLS_PRIM = 0
TYP_CLS_QUAL = 1
TYP_CLS_ENUM = 2
TYP_CLS_UNION = 3
TYP_CLS_CLASS = 4
TYP_CLS_STRUCT = 5
TYP_CLS_MULTI = 6

SINGLE_TYPES1 = SINGLE_TYPES.union({"int"})
PRIM_TYPE_WORDS = SINGLE_TYPES1 | INT_TYPES1 | BASE_TYPE_MODS
LST_STMNT_NAMES = ["{", "if", "while", "for", "return", "break", "continue", "namespace", "<DECL_STMNT>"]

TYPE_SPECS = {"const", "volatile", "register", "auto"}

BINARY_CMP_max = max([BINARY_LT, BINARY_GT, BINARY_LE, BINARY_GE, BINARY_NE, BINARY_EQ])
BINARY_CMP_min = min([BINARY_LT, BINARY_GT, BINARY_LE, BINARY_GE, BINARY_NE, BINARY_EQ])

assert (BINARY_CMP_max - BINARY_CMP_min) == 5, "CMP operator Ids must be consecutive numbers"
