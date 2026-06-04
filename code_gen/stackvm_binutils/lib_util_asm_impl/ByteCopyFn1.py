from ...Compilation import CompileObjectType
from ..assemble import assemble


def add_byte_copy_fn1(compilation):
    byte_copy_fn1 = compilation.spawn_compile_object(
        CompileObjectType.FUNCTION, "@@ByteCopyFn1"
    )
    # The destination is the return slot at BP + 16.
    assemble(byte_copy_fn1, {"Sz": (0x10, 8), "src": (0x18, 8)}, """\
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

LOAD-REG_BP|SZ_8
8x20
ADD8
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
    return byte_copy_fn1
