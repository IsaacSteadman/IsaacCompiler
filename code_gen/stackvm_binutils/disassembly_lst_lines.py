from ...StackVM.PyStackVM import *


def disassembly_lst_lines(memory, start, end, named_indices):
    """
    :param bytearray memory:
    :param int|None start:
    :param int|None end:
    :param dict[int, (str, bool)] named_indices:
    :rtype: list[(int, str)]
    """
    if start is None:
        start = 0
    if end is None:
        end = len(memory)
    c = start
    lst = []
    while c < end:
        byt = memory[c]
        start_mem_pos = c
        if byt == BC_LOAD or byt == BC_STOR:
            c += 1
            typ0 = memory[c]
            sz = typ0 & BCR_SZ_MASK
            sz = 1 << (sz >> 5)
            typ1 = typ0 & BCR_TYP_MASK
            if byt == BC_STOR and typ1 in [BCR_ABS_C, BCR_RES, BCR_EA_R_IP]:
                raise ValueError("Cannot use STOR with BCR_%s (c = %u)" % (LstStackVM_BCR_Types[c], c))
            if typ1 == BCR_ABS_C:
                data = memory[c + 1: c + 1 + sz]
                num = 0
                for c1 in range(sz):
                    num |= data[c1] << (c1 * 8)
                name = named_indices.get(c + 1, None)
                if name is None:
                    s = "%ud%u ; hex = %X" % (sz, num, num)
                else:
                    scope = "g" if name[1] else "l"
                    s = scope + "Aa*%s ; size = %u num = %u hex = %X" % (name[0], sz, num, num)
                if data[-1] >= 0x80:
                    s += " signed = %i" % (num - (1 << (sz * 8)))
                c += sz
            elif typ1 == BCR_SYSREG:
                data = memory[c + 1]
                c += 1
                s = "%s-SYSREG-%s" % ("LOAD" if byt == BC_LOAD else "STOR", LstStackVM_sysregs[data])
            else:
                s = "%s-%s|SZ_%u" % (LstStackVM_Codes[byt], LstStackVM_BCR_Types[typ1], sz)
                if typ1 == BCR_REG_BP:
                    sz = 8
                a = 0
                if typ1 & BCR_R_BP_MASK == BCR_R_BP_VAL:
                    a = 1
                elif typ1 == BCR_ABS_A4:
                    a = 2
                elif typ1 == BCR_ABS_A8:
                    a = 3
                elif typ1 == BCR_EA_R_IP:
                    a = 4
                if a:
                    off_sz = sz
                    if a == 1:
                        off_sz = 1 << (typ1 - BCR_R_BP1)
                    elif a == 2:
                        off_sz = 4
                    elif a == 3:
                        off_sz = 8
                    data = memory[c + 1: c + 1 + off_sz]
                    off = 0
                    for c1 in range(off_sz):
                        off |= data[c1] << (c1 * 8)
                    if (a == 1 or a == 4) and data[-1] >= 0x80:
                        off -= 1 << (off_sz * 8)
                    name = named_indices.get(c + 1, None)
                    if name is None:
                        s += "-%ud(%i)" % (off_sz, off)
                    else:
                        lbl = "g" if name[1] else "l"
                        if a == 1:
                            lbl += "R@"
                        elif a == 2 or a == 3:
                            lbl += "A@"
                        else:
                            lbl += "Ra*"
                        lbl += name[0]
                        s += "-(%s) ; size = %u num = %i" % (lbl, off_sz, off)
                    c += off_sz
        elif BC_NOP <= byt <= BC_GE0 or BC_LSHIFT1 <= byt <= BC_RET_N2:
            s = LstStackVM_Codes[byt]
        elif byt == BC_SWAP:
            c += 1
            typ0 = memory[c]
            sz_a = typ0 & BCS_SZ_A_MASK
            sz_b = (typ0 & BCS_SZ_B_MASK) >> 3
            s = "SWAP-%sA|%sB" % (LstStackVM_BCS_Types[sz_a], LstStackVM_BCS_Types[sz_b])
        elif byt == BC_CONV:
            c += 1
            typ0 = memory[c]
            typ_i = typ0 & BCC_I_MASK
            typ_o = (typ0 & BCC_O_MASK) >> 4
            s = "CONV-%sI|%sO" % (LstStackVM_BCC_Types[typ_i], LstStackVM_BCC_Types[typ_o])
        elif byt == BC_INT:
            c += 1
            typ0 = memory[c]
            s = "INT-1x(%02X)" % typ0
            # raise ValueError("Unrecognized ByteCode at c = %u: BC_INT" % c)
        elif byt == BC_RET_E:
            c += 1
            typ0 = memory[c]
            if typ0 & BCRE_SYS:
                raise ValueError("Unrecognized ByteCode at c = %u: BC_RET_E-BCRE_SYS (SYSRET is not allowed)" % c)
            sz_cls_res = (typ0 & BCRE_RES_SZ_MASK) >> 3
            sz_cls_rst_sp = (typ0 & BCRE_RST_SP_SZ_MASK) >> 5
            s = "RET_E-RES_SZ%u|RST_SP_SZ%u" % (1 << sz_cls_res, 1 << sz_cls_rst_sp)
        elif byt == BC_CALL_E:
            c += 1
            typ0 = memory[c]
            if typ0 & BCCE_SYSCALL:
                sysn_sz_cls = typ0 >> 5
                s = "CALL_E-SYSCALL|S_SYSN_%u" % (1 << sysn_sz_cls)
            elif typ0 & BCCE_N_REL:
                s = "CALL_E-N_REL"
            else:
                s = "CALL_E-1x0"
        elif byt == BC_SYSRET:
            raise ValueError("Unrecognized ByteCode at c = %u: BC_SYSRET" % c)
        else:
            raise ValueError("Unrecognized Implementation defined instruction (c = %u): %u" % (c, byt))
        lst.append((start_mem_pos, s))
        c += 1
    return lst
