from typing import List


def get_user_str_parse_pos(tokens: List["Token"], c: int, off: int = 5) -> str:
    a = max(0, c - off)
    b = min(len(tokens), c + off)
    return "c = %u, tokens around c: {%s}" % (
        c,
        ", ".join(["%u: %r" % (c1, tokens[c1]) for c1 in range(a, b)]),
    )


from ..lexer.lexer import Token
