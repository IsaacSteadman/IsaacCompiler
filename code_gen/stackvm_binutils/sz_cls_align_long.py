def sz_cls_align_long(long, signed, sz_cls):
    if signed:
        if long < 0:
            long = abs(long) - 1
        else:
            signed = False
    rtn = bytearray(1 << sz_cls)
    for c in range(len(rtn)):
        rtn[c] = long & 0xFF
        if signed:
            rtn[c] ^= 0xFF
        long >>= 8
    return rtn