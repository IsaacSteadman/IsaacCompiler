def get_name_from_tokens(tokens, c):
    name = ""
    if tokens[c].type_id == TokenType.NAME:
        name += tokens[c].str
        c += 1
    while tokens[c].str == "::":
        name += "::"
        c += 1
        if tokens[c].type_id == TokenType.NAME:
            name += tokens[c].str
            if tokens[c].str == "operator":
                c += 1
                if tokens[c].type_id == TokenType.OPERATOR:
                    name += tokens[c].str
                elif tokens[c].type_id == TokenType.BRK_OP and tokens[c].str in ["[", "("]:
                    name += tokens[c].str
                    c += 1
                    if tokens[c].str not in ["[", "("]:
                        raise ParsingError(
                            tokens, c, "expected closing ')' or ']' after '%s'" % name.rsplit("::", 1)[-1]
                        )
                    name += tokens[c].str
        else:
            raise ParsingError(tokens, c, "Expected identifier after '::'")
        c += 1
    return name, c


from .ParsingError import ParsingError
from ..lexer.lexer import TokenType