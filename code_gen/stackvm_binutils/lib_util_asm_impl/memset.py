from ...Compilation import CompileObjectType
from .lib_utils import lib_utils_abi
from ..assemble import assemble


# declared as `void *memset(void * ptr, unsigned char value, unsigned long long num)`
mem_set = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "?FPvcyzmemset")
assemble(mem_set, {"ptr": (0x10, 8), "value": (0x18, 1), "num": (0x19, 8), "res": (0x21, 8)}, """
@ptr
lRa*res
STOR-ABS_S8|SZ_8
~+end,8d0
@ptr
@num
ADD8
lRa*end
STOR-ABS_S8|SZ_8
:beginLoop
@ptr
@end
CMP8
GE0
lRa*:endLoop
JMPIF


@value
@ptr
STOR-ABS_S8|SZ_1

@ptr
8d1
ADD8
lRa*ptr
STOR-ABS_S8|SZ_8
lRa*:beginLoop
JMP
:endLoop
~-end
RET
""")