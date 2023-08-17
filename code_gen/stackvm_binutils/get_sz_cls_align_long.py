from typing import Literal


def get_sz_cls_align_long(long: int, signed: bool, max_sz_cls: Literal[0, 1, 2, 3] = 3):
    if long < 0:
        if signed:
            long = abs(long) - 1
        else:
            raise ValueError("long < 0 when bool(signed) == True ")
    else:
        signed = False
    res = bytearray(1)
    c = 0
    sz_cls = 0
    while long > 0:
        if c >= len(res):
            res.extend([0] * len(res))
            sz_cls += 1
            if sz_cls > max_sz_cls:
                raise ValueError("long is too big")
        res[c] = long & 0xFF
        long >>= 8
    if signed:
        if 0x80 & res[-1]:
            res.extend([0] * len(res))
            sz_cls += 1
            if sz_cls > max_sz_cls:
                raise ValueError("long is too big")
        for c in range(len(res)):
            res[c] ^= 0xFF
    return res, sz_cls
