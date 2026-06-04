from ...Compilation import CompileObjectType
from ..assemble import assemble


def add_byte_copy_fn(compilation):
    byte_copy_fn = compilation.spawn_compile_object(
        CompileObjectType.FUNCTION, "@@ByteCopyFn"
    )
    assemble(byte_copy_fn, {"Sz": (0x10, 8), "src": (0x18, 8), "dest": (0x20, 8)}, """
~+c,8d0
:checkFor
@c
@Sz
CMP8
LT0
EQ0
lRa*:endFor
JMPIF


@src
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
    return byte_copy_fn
