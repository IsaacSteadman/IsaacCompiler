from typing import Union, List, Dict, Optional, Tuple, Callable
from ...StackVM.PyStackVM import *

# Sub-op name tables for extended groups
_INT128_OPS = [
    "ADD128U",
    "ADD128S",
    "SUB128U",
    "SUB128S",
    "MUL128U",
    "MUL128S",
    "DIV128U",
    "DIV128S",
    "MOD128U",
    "MOD128S",
    "AND128",
    "OR128",
    "XOR128",
    "NOT128",
    "LSHIFT128",
    "RSHIFT128U",
    "RSHIFT128S",
    "CMP128U",
    "CMP128S",
    "POPCNT1",
    "POPCNT2",
    "POPCNT4",
    "POPCNT8",
    "BSWAP2",
    "BSWAP4",
    "BSWAP8",
]
_INVTLB_OPS = ["INVTLB_BEGIN", "INVTLB_COMMIT"]
# Atomic BCR codes that consume an extra ordering byte in the instruction stream
_ATOMIC_ORDERING = ("RELAXED", "ACQUIRE", "RELEASE", "SEQ_CST")
_LOAD_ATOMIC_BCR = {
    BCR_ATOMIC_LOAD: "ATOMIC_LOAD",
    BCR_ATOMIC_XCHG: "ATOMIC_XCHG",
    BCR_ATOMIC_CAS: "ATOMIC_CAS",
    BCR_ATOMIC_FADD: "ATOMIC_FADD",
    BCR_ATOMIC_FSUB: "ATOMIC_FSUB",
    BCR_ATOMIC_FAND: "ATOMIC_FAND",
    BCR_ATOMIC_FOR: "ATOMIC_FOR",
    BCR_ATOMIC_FXOR: "ATOMIC_FXOR",
}


def disassembly_lst_lines(
    memory: Union[bytearray, bytes, memoryview],
    start: Optional[int],
    end: Optional[int],
    named_indices: Dict[int, Tuple[str, bool]],
) -> List[Tuple[int, str]]:
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
            if typ1 == BCR_ABS_C and byt == BC_STOR:
                # 0x08 on STOR = ATOMIC_STORE (needs ordering byte)
                c += 1
                ordering = memory[c]
                s = "STOR-ATOMIC_STORE|SZ_%u|%s" % (sz, _ATOMIC_ORDERING[ordering & 3])
            elif typ1 == BCR_ABS_C:  # LOAD only
                data = memory[c + 1 : c + 1 + sz]
                num = 0
                for c1 in range(sz):
                    num |= data[c1] << (c1 * 8)
                name = named_indices.get(c + 1, None)
                if name is None:
                    s = "%ud%u ; hex = %X" % (sz, num, num)
                else:
                    scope = "g" if name[1] else "l"
                    s = scope + "Aa*%s ; size = %u num = %u hex = %X" % (
                        name[0],
                        sz,
                        num,
                        num,
                    )
                if data[-1] >= 0x80:
                    s += " signed = %i" % (num - (1 << (sz * 8)))
                c += sz
            elif typ1 == BCR_SYSREG:
                data = memory[c + 1]
                c += 1
                reg_name = (
                    LstStackVM_sysregs[data]
                    if data < len(LstStackVM_sysregs)
                    else "0x%02X" % data
                )
                s = "%s-SYSREG-%s" % (
                    "LOAD" if byt == BC_LOAD else "STOR",
                    reg_name,
                )
            elif byt == BC_STOR and typ1 in (
                BCR_FENCE_ALL,
                BCR_FENCE_LOAD,
                BCR_FENCE_STORE,
            ):
                names = {
                    BCR_FENCE_ALL: "FENCE_ALL",
                    BCR_FENCE_LOAD: "FENCE_LOAD",
                    BCR_FENCE_STORE: "FENCE_STORE",
                }
                s = "STOR-%s" % names[typ1]
            elif byt == BC_LOAD and typ1 in _LOAD_ATOMIC_BCR:
                # consume ordering byte
                c += 1
                ordering = memory[c]
                s = "LOAD-%s|SZ_%u|%s" % (
                    _LOAD_ATOMIC_BCR[typ1],
                    sz,
                    _ATOMIC_ORDERING[ordering & 3],
                )
            else:
                typ_name = (
                    LstStackVM_BCR_Types[typ1]
                    if typ1 < len(LstStackVM_BCR_Types)
                    else "0x%02X" % typ1
                )
                s = "%s-%s|SZ_%u" % (
                    LstStackVM_Codes[byt],
                    typ_name,
                    sz,
                )
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
                    data = memory[c + 1 : c + 1 + off_sz]
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
            s = "SWAP-%sA|%sB" % (
                LstStackVM_BCS_Types[sz_a],
                LstStackVM_BCS_Types[sz_b],
            )
        elif byt == BC_CONV:
            c += 1
            typ0 = memory[c]
            typ_i = typ0 & BCC_I_MASK
            typ_o = (typ0 & BCC_O_MASK) >> 4
            name_i = (
                LstStackVM_BCC_Types[typ_i]
                if typ_i < len(LstStackVM_BCC_Types)
                else "0x%X" % typ_i
            )
            name_o = (
                LstStackVM_BCC_Types[typ_o]
                if typ_o < len(LstStackVM_BCC_Types)
                else "0x%X" % typ_o
            )
            s = "CONV-%sI|%sO" % (name_i, name_o)
        elif byt == BC_INT128:
            c += 1
            op = memory[c]
            op_name = _INT128_OPS[op] if op < len(_INT128_OPS) else "0x%02X" % op
            s = "INT128-%s" % op_name
        elif byt == BC_INVTLB:
            c += 1
            op = memory[c]
            op_name = _INVTLB_OPS[op] if op < len(_INVTLB_OPS) else "0x%02X" % op
            s = "INVTLB-%s" % op_name
        elif byt == BC_RET_E:
            c += 1
            typ0 = memory[c]
            if typ0 & BCRE_SYS:
                if typ0 & BCRE_IS_INT:
                    s = "RET_E-IRET"
                else:
                    s = "RET_E-SYSRET"
            else:
                sz_cls_res = (typ0 & BCRE_RES_SZ_MASK) >> 3
                sz_cls_rst_sp = (typ0 & BCRE_RST_SP_SZ_MASK) >> 5
                s = "RET_E-RES_SZ%u|RST_SP_SZ%u" % (1 << sz_cls_res, 1 << sz_cls_rst_sp)
        elif byt == BC_CALL_E:
            c += 1
            typ0 = memory[c]
            if typ0 & BCCE_SYSCALL:
                sysn_sz_cls = (typ0 >> 5) & 3
                s = "CALL_E-SYSCALL|S_SYSN_%u" % (1 << sysn_sz_cls)
            elif typ0 & BCCE_IS_INT:
                c += 1
                int_n = memory[c]
                s = "CALL_E-INT(%02X)" % int_n
            elif typ0 & BCCE_IS_REL:
                s = "CALL_E-REL"
            else:
                s = "CALL_E-ABS"
        else:
            raise ValueError(
                "Unrecognized Implementation defined instruction (c = %u): %u"
                % (c, byt)
            )
        lst.append((start_mem_pos, s))
        c += 1
    return lst
