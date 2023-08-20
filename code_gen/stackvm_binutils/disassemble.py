from typing import Union, List, Dict, Optional, Tuple, Callable
from .disassembly_lst_lines import disassembly_lst_lines


def disassemble(
    memory: Union[bytearray, bytes, memoryview],
    start: Optional[int],
    end: Optional[int],
    named_indices: Dict[int, Tuple[str, bool]],
    address_fmt: Optional[Union[str, Callable[[str, int], str]]] = None,
    src_pos: Optional[Dict[int, str]] = None,
) -> str:
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
