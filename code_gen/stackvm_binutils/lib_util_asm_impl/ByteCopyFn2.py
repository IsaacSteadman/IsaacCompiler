from ...Compilation import CompileObjectType
from .lib_utils import lib_utils_abi
from ..assemble import assemble


byte_copy_fn2 = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "@@ByteCopyFn2")
# reference to value at src is replaced with a load from register BP offset by 16
#   (since bp represents the previous stack pointer)
assemble(byte_copy_fn2, {"Sz": (0x10, 8), "dest": (0x18, 8)}, """\
~+c,8d0
:checkFor
@c
@Sz
CMP8
LT0
EQ0
lRa*:endFor
JMPIF


LOAD-REG_BP|SZ_8
8x20
ADD8
@c
ADD8
LOAD-ABS_S8|SZ_1

@dest
@c
ADD8

STOR-ABS_S8|SZ_1

@c
8d1
ADD8
lRa*c
STOR-ABS_S8|SZ_8

lRa*:checkFor
JMP

:endFor
~-c
RET
""")