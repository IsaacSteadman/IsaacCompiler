def proc_typed_decl(tokens, c, end, context, base_type=None):
    # process the 'base' type before any parentheses, '*', '&', 'const', or 'volatile'
    if base_type is None:
        base_type, c = get_base_type(tokens, c, end, context)
        if base_type is None:
            return None, c
    rtn = base_type
    if not isinstance(rtn, IdentifiedQualType):
        rtn = IdentifiedQualType(None, rtn)
    s_start = c
    s_end = end
    i_type = 0  # inner type, 0: None, 1: '(' and ')', 2: name
    i_start = 0
    i_end = 0
    is_operator = False
    # collect tokens before the 'identifier' and place them in the pseudo-stack
    while c < end:
        if tokens[c].type_id == TokenType.BRK_OP:
            if tokens[c].str == "(":
                s_end = c
                c += 1
                lvl = 1
                i_start = c
                while c < end and lvl > 0:
                    if tokens[c].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c].str in CLOSE_GROUPS:
                        lvl -= 1
                    c += 1
                i_end = c - 1
                i_type = 1
                break
        elif (
                (tokens[c].type_id == TokenType.NAME and tokens[c].str not in {"const", "auto", "volatile", "register"}) or
                tokens[c].str == "::"):
            i_type = 2
            i_start = c
            s_end = c
            c += 1
            while c < end:
                if tokens[c - 1].type_id == TokenType.NAME:
                    if tokens[c - 1].str == "operator":
                        if tokens[c].type_id == TokenType.OPERATOR:
                            c += 1
                        elif tokens[c].type_id == TokenType.BRK_OP:
                            if tokens[c].str == ",":
                                c += 1
                            elif tokens[c].str == "(":
                                c += 1
                                if tokens[c].str != ")":
                                    raise ParsingError(tokens, c, "Expected ')' for 'operator('")
                                c += 1
                            elif tokens[c].str == "[":
                                c += 1
                                if tokens[c].str != "]":
                                    raise ParsingError(tokens, c, "Expected ']' for 'operator['")
                                c += 1
                            else:
                                raise ParsingError(tokens, c, "Unrecognized operator found after operator keyword")
                        is_operator = True
                        break
                    elif tokens[c].str != "::":
                        break
                elif tokens[c - 1].str == "::":
                    if tokens[c].type_id != TokenType.NAME:
                        raise ParsingError(tokens, c, "Expected name to follow '::'")
                    elif tokens[c].str in KEYWORDS:
                        raise ParsingError(tokens, c, "Unexpected keyword following '::'")
                c += 1
            i_end = c
            break
        c += 1
    # process items before the identifier starting from the higher index (like popping the pseudo-stack)
    c0 = s_end
    while c0 > s_start:
        c0 -= 1
        if tokens[c0].str in QualType.QUAL_Dct:
            rtn.add_qual_type(QualType.QUAL_Dct[tokens[c0].str])
        else:
            raise ParsingError(tokens, c0, "Unexpected token")
    # process items after the identifier by creating QualType instances
    while c < end:
        if tokens[c].type_id == TokenType.BRK_OP:
            if tokens[c].str == "(":
                cancel = False
                lvl = 1
                ext_inf = []
                c += 1
                n_start = c
                if tokens[c].str == ")":
                    lvl = 0
                    c += 1
                elif tokens[c].str == "void" and tokens[c + 1].str == ")":
                    lvl = 0
                    c += 2
                while c < end and lvl > 0:
                    if tokens[c].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c].str in CLOSE_GROUPS:
                        lvl -= 1
                    if (lvl == 1 and tokens[c].str == ",") or lvl == 0:
                        n_end = c
                        c = n_start
                        n_decl, c = proc_typed_decl(tokens, c, n_end, context)
                        if n_decl is None:
                            cancel = True
                            break
                        if c != n_end:
                            # raise SyntaxError("incomplete type at tokens[%u].str = %r and tokens[%u].str = %r" % (
                            #     c, tokens[c].str, n_end, tokens[n_end].str))
                            raise ParsingError(tokens, c, "Incomplete Type")
                        ext_inf.append(n_decl)
                        n_start = n_end + 1
                    c += 1
                if not cancel:
                    rtn.add_qual_type(QualType.QUAL_FN, ext_inf)
                else:
                    c = n_start - 1
                    break
            elif tokens[c].str == "[":
                c += 1
                ext_inf = None
                if tokens[c].str != "]":
                    expr, c = get_expr(tokens, c, "]", end, context)
                    if not isinstance(expr, LiteralExpr):
                        raise ParsingError(tokens, c, "Expected Literal Integer for bounds of array")
                    else:
                        assert isinstance(expr, LiteralExpr)
                        if expr.t_lit != LiteralExpr.LIT_INT:
                            raise ParsingError(tokens, c, "Expected Literal Integer for bounds of array")
                        else:
                            radix = 10
                            if len(expr.v_lit) > 1 and expr.v_lit.startswith("0"):
                                ch = expr.v_lit[1].lower()
                                if ch.isdigit() or ch == 'o':
                                    radix = 8
                                elif ch == 'x':
                                    radix = 16
                                elif ch == 'b':
                                    radix = 2
                            ext_inf = int(expr.v_lit, radix)
                c += 1
                rtn.add_qual_type(QualType.QUAL_ARR, ext_inf)
            elif tokens[c].str == "," or tokens[c].str == ";" or tokens[c].str == "{":
                break
            else:
                raise ParsingError(tokens, c, "Unsupported Breaking operator")
        elif tokens[c].type_id == TokenType.OPERATOR and tokens[c].str == "=":
            break
        else:
            raise ParsingError(tokens, c, "Unexpected token")
    if i_type == 1:
        c0 = c
        c = i_start
        rtn, c = proc_typed_decl(tokens, c, i_end, context, rtn)
        if c != i_end:
            # raise SyntaxError("incomplete type at tokens[%u].str = %r and tokens[%u].str = %r" % (
            #     c, tokens[c].str, i_end, tokens[i_end].str))
            raise ParsingError(tokens, c, "Incomplete Type")
        c = c0
    elif i_type == 2:
        rtn.name = "".join(map(tok_to_str, tokens[i_start:i_end]))
        rtn.is_op_fn = is_operator
    return rtn, c
# TODO: Things to think about
# TODO:   Typenames -> struct Pt {int x; int y;}; ...function {Pt a = {0, 12}; return 0;}
# TODO:     Figure out that 'Pt a = {0, 12};' is a declaration
