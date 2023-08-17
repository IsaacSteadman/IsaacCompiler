from typing import Optional


def emit_load_i_const(
    memory: bytearray,
    num: int,
    sign: Optional[bool] = None,
    sz_cls: Optional[int] = None,
) -> int:
    byts, sz_cls = get_load_i_const(num, sign, sz_cls)
    memory.extend(byts)
    return sz_cls


from .get_load_i_const import get_load_i_const
