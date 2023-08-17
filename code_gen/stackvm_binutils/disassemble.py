from .disassembly_lst_lines import disassembly_lst_lines


def disassemble(memory, start, end, named_indices, address_fmt=None, src_pos=None):
    """
    :param bytearray memory:
    :param int|None start:
    :param int|None end:
    :param dict[int, (str, bool)] named_indices:
    :param str|None|((str, int) -> str) address_fmt:
    :param dict[int, str]|None src_pos:
    :rtype: str
    """
    lst = disassembly_lst_lines(memory, start, end, named_indices)
    lst_lines = [""] * len(lst)
    if address_fmt is None:
        for c in range(len(lst)):
            lst_lines[c] = lst[c][1]
    elif isinstance(address_fmt, str):
        for c in range(len(lst)):
            lst_lines[c] = address_fmt % (lst[c][0], lst[c][1])
    else:
        for c in range(len(lst)):
            lst_lines[c] = address_fmt(lst[c][1], lst[c][0])
    if src_pos is not None:
        lst_insert = []
        for c in range(len(lst)):
            addr = lst[c][0]
            name = src_pos.get(addr, None)
            if name is not None:
                lst_insert.append((c, name))
        for index, name in lst_insert[::-1]:
            lst_lines.insert(index, name)
    return "\n".join(lst_lines)