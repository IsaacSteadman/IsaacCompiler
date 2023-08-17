from typing import Tuple, Union


# returns (number, sign boolean, sz_cls 0 | 1 | 2 | 3, base is None, end idx of number in string)
def parse_number(part: str, parens: bool = False) -> Tuple[Union[float, int], bool, int, bool, int]:
    if not part[0].isdigit():
        raise SyntaxError("expected number, got '%s'" % part)
    c = 1
    while part[c].isdigit() and c < len(part):
        c += 1
    if c >= len(part):
        raise SyntaxError("Expected character to terminate size specifier for number")
    sign = part[c].isupper()
    typ = part[c].lower()
    map_int_base = {"d": 10, "o": 8, "x": 16, "b": 2}
    n_bytes = int(part[0:c])
    sz_cls = n_bytes.bit_length() - 1
    if 1 << sz_cls != n_bytes or sz_cls > 7:
        raise SyntaxError("Expected a power of 2 byte size specifier that satisfies size <= 128")
    c += 1
    base = map_int_base.get(typ, None)
    end = len(part)
    if typ in map_int_base:
        if sz_cls > 3:
            raise SyntaxError("integer literal must be 1, 2, 4 or 8 bytes. got %u" % n_bytes)
        if parens:
            if part[c] != '(':
                raise SyntaxError("Expected '(' to begin number literal")
            c += 1
            end = part.find(")", c)
            if end == -1:
                raise SyntaxError("Expected ')' to terminate number literal")
        num = int(part[c:end], base)
    elif typ == "f":
        if sz_cls != 2 and sz_cls != 3:
            raise SyntaxError("float literal must be 4 or 8 bytes. got %u" % n_bytes)
        if parens:
            if part[c] != '(':
                raise SyntaxError("Expected '(' to begin number literal")
            c += 1
            end = part.find(")", c)
            if end == -1:
                raise SyntaxError("Expected ')' to terminate number literal")
        num = float(part[c:end])
    else:
        raise SyntaxError("Unrecognized literal type: '%s'" % typ)
    if parens:
        end += 1
    return num, sign, sz_cls, base is None, end