from ...Compilation import CompileObjectType
from ..assemble import assemble

# declared as `double pow(double base, int exponent);`
# Frame layout (non-variadic):
#   bp+0x10 (16): base     — 8-byte double
#   bp+0x18 (24): exponent — 4-byte signed int
#   bp+0x1C (28): res      — 8-byte double (return slot)
def add_pow(compilation, link_name):
    pow_fn = compilation.spawn_compile_object(CompileObjectType.FUNCTION, link_name)
    assemble(
        pow_fn,
        {"base": (0x10, 8), "exponent": (0x18, 4), "res": (0x1C, 8)},
        """
~+result,8f1.0
~+n,8d0

@exponent
CONV-BCC(SI_4_I|SI_8_O)
lRa*n
STOR-ABS_S8|SZ_8

@n
8d0
CMP8
EQ0
lRr[1]*:done
RJMPIF

@n
8d0
CMP8S
GE0
lRr[1]*:abs_done
RJMPIF

8d0
@n
SUB8
lRa*n
STOR-ABS_S8|SZ_8

:abs_done

:loop
@n
8d0
CMP8
EQ0
lRr[1]*:end_loop
RJMPIF

@result
@base
FMUL_8
lRa*result
STOR-ABS_S8|SZ_8

@n
8d1
SUB8
lRa*n
STOR-ABS_S8|SZ_8

lRr[1]*:loop
RJMP

:end_loop

@exponent
CONV-BCC(SI_4_I|SI_8_O)
8d0
CMP8S
GE0
lRr[1]*:done
RJMPIF

8f1.0
@result
FDIV_8
lRa*result
STOR-ABS_S8|SZ_8

:done
@result
lRa*res
STOR-ABS_S8|SZ_8

~-n
~-result
RET
""",
    )
    return pow_fn
