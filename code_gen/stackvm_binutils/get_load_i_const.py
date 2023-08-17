
from typing import Optional, Tuple


def get_load_i_const(num: int, sign: Optional[bool]=None, sz_cls: Optional[int]=None) -> Tuple[bytearray, int]:
    if sign is None:
        sign = num < 0
    if sz_cls is None:
        byts, sz_cls = get_sz_cls_align_long(num, sign)
    else:
        byts = sz_cls_align_long(num, sign, sz_cls)
    rtn = bytearray([
        BC_LOAD, BCR_ABS_C | (sz_cls << 5)])
    rtn.extend(byts)
    return rtn, sz_cls


from .get_sz_cls_align_long import get_sz_cls_align_long
from .sz_cls_align_long import sz_cls_align_long
from ...StackVM.PyStackVM import BC_LOAD, BCR_ABS_C