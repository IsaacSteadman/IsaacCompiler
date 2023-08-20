from typing import Any, Callable, Dict, Literal, Optional, Tuple, TypeVar, Union

"""from PyIsaacUtils.AlgoUtils import bisect_search_base
from StackVM.PyStackVM import BC_ADD8, BC_ADD_SP1, BC_CALL_E, BC_CONV, BC_GE0, BC_INT, BC_LOAD, BC_LSHIFT1, BC_NOP,\
    BC_RET_E, BC_RET_N2, BC_RST_SP1, BC_STOR, BC_SWAP, BC_SYSRET, BCC_I_MASK, BCC_O_MASK, BCCE_N_REL, BCCE_SYSCALL,\
    BCR_ABS_A4, BCR_ABS_A8, BCR_ABS_C, BCR_ABS_S8, BCR_EA_R_IP, BCR_R_BP1, BCR_R_BP_MASK, BCR_R_BP_VAL, BCR_REG_BP,\
    BCR_RES, BCR_SYSREG, BCR_SZ_8, BCR_SZ_MASK, BCR_TYP_MASK, BCRE_RES_SZ_MASK, BCRE_RST_SP_SZ_MASK, BCRE_SYS,\
    BCS_SZ8_B, BCS_SZ_A_MASK, BCS_SZ_B_MASK, MRQ_DONT_CHECK, VM_4_LVL_9_BIT, VM_DISABLED, LstStackVM_BCC_Types,\
    LstStackVM_BCR_Types, LstStackVM_BCS_Types, LstStackVM_Codes, LstStackVM_sysregs, StackVM_BCC_Codes,\
    StackVM_BCCE_Codes, StackVM_BCR_Codes, StackVM_BCRE_Codes, StackVM_BCS_Codes, StackVM_Codes, StackVM_SVSR_Codes,\
    float_t, double_t"""

from PyIsaacUtils.AlgoUtils import *

from StackVM.PyStackVM import *


T = TypeVar("T")


# @@ByteCopyFn is (SizeL sz, void *src, void *dest) -> None
#   push order [dest] [src] [sz]

# @@ByteCopyFn1 is (SizeL sz, void *src) -> None
#   push order [src] [sz]
#    dest is implicit as (bp + 16 + 16 for arguments)

# @@ByteCopyFn2 is (SizeL sz, void *dest) -> None
#   push order [dest] [sz]
#    src is implicit as (bp + 16 + 16 for arguments)


'''MyMalloc = Compilation()
Assemble(
    MyMalloc.SpawnCompileObject(CompileObjectType.FUNCTION, "_@IdAllocator@@FPB04Rangeyyy@IdAllocator"),
    {"this": (0x10, 8), "ArrRanges": (0x18, 8), "LenArr": (0x20, 8), "Min": (0x28, 8), "Max": (0x30, 8)}, """\
8d1
@this
8d8
ADD8
STOR-ABS_S8|SZ_8
@LenArr
@this
8d16
ADD8
STOR-ABS_S8|SZ_8
@ArrRanges
@this
STOR-ABS_S8|SZ_8
@Min
@this
8d24
ADD8
STOR-ABS_S8|SZ_8
@Max
@this
8d32
ADD8
STOR-ABS_S8|SZ_8
@Min
@this
LOAD-ABS_S8|SZ_8
STOR-ABS_S8|SZ_8
@Max
@this
LOAD-ABS_S8|SZ_8
8d8
ADD8
STOR-ABS_S8|SZ_8
""")
Assemble(
    # TODO: compile IdAllocator::ReduceRanges
    MyMalloc.SpawnCompileObject(CompileObjectType.FUNCTION, "_@IdAllocator@@ReduceRanges@V"),
    {"this": (0x10, 8)}, """\
~+i,8d1
~+c,8d1
:checkFor
@c
@this
8d8
ADD8
LOAD-ABS_S8|SZ_8
CMP8
LT0
EQ0
lRa*:endFor
JMPIF

@i
@c
CMP8
NE0
EQ0
lRa*:endIf1
JMPIF

@this
LOAD-ABS_S8|SZ_8
@c
8d16
MUL8
ADD8
LOAD-ABS_S8|SZ_8
@this
LOAD-ABS_S8|SZ_8
@i
8d16
MUL8
ADD8
STOR-ABS_S8|SZ_8

@this
LOAD-ABS_S8|SZ_8
@c
8d16
MUL8
ADD8
LOAD-ABS_S8|SZ_8
@this
LOAD-ABS_S8|SZ_8
@i
8d16
MUL8
ADD8
STOR-ABS_S8|SZ_8
:endIf1

@i
@c
CMP8
NE0
EQ0
lRa*:elseIf2
JMPIF

:elseIf2

lRa*:endIf2

:endIf2

:endFor
""")
'''
