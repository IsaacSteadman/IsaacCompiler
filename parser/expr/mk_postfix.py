
def take_prev(op_tuple):
    return op_tuple[0] > 0 and bool(op_tuple[3] & 0x02)


def take_next(op_tuple):
    return op_tuple[0] > 0 and bool(op_tuple[3] & 0x01)


def take_both(op_tuple):
    return op_tuple[0] >= 2 and (op_tuple[3] & 0x03) == 0x03
# Ternary/special operator format:
#   k, v = begin token, tuple of stuff
#   v[0] = operator precedence
#   v[1] = end token
#   v[2] = tuple of possible fixes: <bitwise or> of
#     0x01 is prefix<meaning ()b>, 0x02 is postfix<meaning a()>


def mk_postfix(tokens, c, end, context, get_expr_part, delim=None, l_t_r=None):
    """
    :param list[Token] tokens:
    :param int c:
    :param int end:
    :param CompileContext context:
    :param (list[Token],int,int,CompileContext) -> (BaseOpPart, int) get_expr_part:
    :param str|None delim:
    :param dict[int,bool]|list[bool]|None l_t_r:
    """
    if l_t_r is None:
        l_t_r = LST_LTR_OPS
    op_stack = list()
    rtn = list()
    prev_op = None
    tok = None
    if delim is not None and tokens[c].str == delim:
        return [], c
    next_item, c = get_expr_part(tokens, c, end, context)
    while next_item is not None:
        prev = tok
        tok = next_item
        if c >= end or (delim is not None and tokens[c].str == delim):
            next_item = None
        else:
            # TODO temporary
            next_item, c = get_expr_part(tokens, c, end, context)
        # format = tuple of:
        #   Number of operands,
        #   token,
        #   precedence,
        #   a key in {1:prefix operator, 3: infix operator, 2: postfix operator}
        next_op = None
        is_prefix, is_infix, is_postfix = tok.can_prefix, tok.can_infix, tok.can_postfix
        the_sum = is_prefix + is_infix + is_postfix
        if tok.can_nofix:
            assert not is_prefix, "prefix operators cannot nofix (disambiguation requires backtracking)"
        if tok.is_expr:
            next_op = (0, tok)
        elif the_sum == 1:
            if tok.can_nofix and (prev_op is None or take_next(prev_op)):
                next_op = (0, tok)
            elif is_prefix:
                next_op = (1, tok, tok.prefix_lvl, 1)
            elif is_infix:
                next_op = (2, tok, tok.infix_lvl, 3)
            elif is_postfix:
                next_op = (1, tok, tok.postfix_lvl, 2)
            else:
                raise ValueError("Unknown error occurred: c = %u" % c)
        elif the_sum == 2:
            end_type = 0
            if tok.can_nofix and (prev_op is None or take_next(prev_op)):
                end_type = 0
            elif is_prefix and is_postfix:
                if prev_op is None or take_next(prev_op):
                    end_type = 1
                else:
                    end_type = 2
            elif is_infix and is_postfix:
                if prev_op is None:
                    raise ParsingError(tokens, c, "postfix/infix operator must appear after an expression")
                elif take_next(prev_op):
                    raise ParsingError(tokens, c, "Previous operator cannot directly capture infix or postfix")
                if next_item.is_expr:  # its prefix
                    end_type = 1  # TODO: verify changed 2 -> 1 is it correct? (also postfix->prefix)
                else:
                    t_take_prev = [next_item.postfix_lvl, next_item.infix_lvl]
                    if None in t_take_prev:
                        t_take_prev.remove(None)
                    if len(t_take_prev) == 2:
                        t_take_prev = min(t_take_prev)
                    else:
                        t_take_prev = t_take_prev[0]
                    t_not_take_prev = next_item.prefix_lvl
                    if t_take_prev is not None and t_not_take_prev is None:
                        end_type = 3  # tok is infix
                    elif t_take_prev is not None:
                        if t_take_prev > t_not_take_prev:
                            end_type = 3
                        else:
                            end_type = 2
                    elif t_not_take_prev is not None:
                        end_type = 3
                    else:  # tok is postfix
                        end_type = 2
            elif is_infix and is_prefix:
                if prev is None or take_next(prev_op):
                    end_type = 1
                else:
                    end_type = 3
            if end_type == 1:  # Prefix
                next_op = (1, tok, tok.prefix_lvl, 1)
            elif end_type == 2:  # Postfix
                next_op = (1, tok, tok.postfix_lvl, 2)
            elif end_type == 3:  # Infix
                next_op = (2, tok, tok.infix_lvl, 3)
            else:  # Nofix
                next_op = (0, tok)
        elif the_sum == 3:
            raise ParsingError(tokens, c, "Operators must only be able to be one of prefix, infix, or postfix")
        elif prev_op is not None:
            fix = 0
            if not take_next(prev_op):  # REMEMBER: tok is in Syms ^^^^
                fix |= 2
            lst_lvls = list(filter(lambda x: x[1] is not None, (
                next_item.prefix_lvl,
                next_item.infix_lvl,
                next_item.postfix_lvl)))
            if len(lst_lvls) == 0:
                fix |= 1  # cur is definitely going to capture next_item
            elif len(lst_lvls) == 1:
                if lst_lvls[0][0] == 0:
                    fix |= 1
                # otherwise it is not prefix
            else:
                pick = min(lst_lvls, key=lambda x: x[1])
                if pick[0] == 0:
                    fix |= 1
        elif prev.can_infix:  # but it could be multi -- edit: ignore multi
            # print c, tok
            if take_next(prev_op):  # tok: prefix unary operator,.
                next_op = (1, tok, tok.prefix_lvl, 1)
            elif take_prev(prev_op):  # tok: binary operator
                next_op = (2, tok, tok.infix_lvl, 3)
            else:
                raise ParsingError(tokens, c, "Invalid operator fixness or usage")
                # print("Unknown: rtn=%r, c=%r, prev=%r, tok=%r, next_item=%r" % (rtn, c, prev, tok, next_item))
        elif next_item.can_infix:
            if tok.can_infix and next_item.can_prefix:  # tok: binary operator
                next_op = (2, tok, tok.infix_lvl, 3)
            elif next_item.can_infix and tok.can_postfix:  # tok: Postfix unary operator
                next_op = (1, tok, tok.postfix_lvl, 2)
            else:
                raise ParsingError(tokens, c, "two operators cannot be the same type (binary, post-unary, pre-unary")
        else:
            if prev is None:
                if not tok.can_prefix:
                    raise ParsingError(tokens, c, "operator misused as postfix at BOL (it cannot be postfix)")
                next_op = (1, tok, tok.prefix_lvl, 1)
            elif next_item is None:
                if not tok.can_postfix:
                    raise ParsingError(tokens, c, "operator misused as prefix at EOL (it cannot be prefix)")
                next_op = (1, tok, tok.prefix_lvl, 2)
            elif tok.can_infix and not prev.can_infix and not next_item.can_infix:
                next_op = (2, tok, tok.infix_lvl, 2)
            else:
                raise ParsingError(
                    tokens, c, "could not resolve prev = %r, tok = %r, next_item = %r" % (prev, tok, next_item)
                )
        if next_op is None:
            pass
        elif next_op[0] > 0:
            if len(op_stack) > 0:
                lvl0 = op_stack[-1][2]
                lvl1 = next_op[2]
                if lvl1 > lvl0 or (lvl1 == lvl0 and l_t_r[lvl0]):
                    rtn.append(op_stack.pop())
            op_stack.append(next_op)
        else:
            rtn.append(next_op)
        prev_op = next_op
    rtn.extend(op_stack[::-1])
    # time.sleep(.2)
    # print "All the Postfix:\n  ", "\n  ".join(map(repr, rtn))
    # print "  prev_op=%r" % list(prev_op)
    # print "  next_op=%r" % list(next_op)
    # time.sleep(.2)
    return rtn, c


from ..ParsingError import ParsingError