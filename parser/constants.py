
SINGLE_TYPES = {
    "float", "double", "bool",
    "void", "auto"
}
INT_TYPES = {
    "int", "long", "short", "char",
    "wchar_t", "char16_t", "char32_t"
}
INT_TYPES1 = INT_TYPES.difference({"int"})
SINGLE_TYPES1 = SINGLE_TYPES.union({"int"})

BASE_TYPE_MODS = {
    "signed", "unsigned"
}
PRIM_TYPE_WORDS = SINGLE_TYPES1 | INT_TYPES1 | BASE_TYPE_MODS

assert "int" not in INT_TYPES1

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