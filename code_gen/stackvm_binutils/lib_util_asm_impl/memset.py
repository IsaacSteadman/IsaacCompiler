from ...Compilation import CompileObjectType
from ..assemble import assemble


# declared as `void *memset(void * ptr, unsigned char value, unsigned long long num)`
def add_memset(compilation, link_name):
    mem_set = compilation.spawn_compile_object(CompileObjectType.FUNCTION, link_name)
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
lRr[1]*:endLoop
RJMPIF


@value
@ptr
STOR-ABS_S8|SZ_1

@ptr
8d1
ADD8
lRa*ptr
STOR-ABS_S8|SZ_8
lRr[1]*:beginLoop
RJMP
:endLoop
~-end
RET
""")
    return mem_set
