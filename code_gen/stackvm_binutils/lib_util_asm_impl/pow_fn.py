from ...Compilation import CompileObjectType
from .lib_utils import lib_utils_abi
from ..assemble import assemble

# declared as `double pow(double base, int exponent);`
# Frame layout (non-variadic):
#   bp+0x10 (16): base     — 8-byte double
#   bp+0x18 (24): exponent — 4-byte signed int
#   bp+0x1C (28): res      — 8-byte double (return slot)
pow_fn = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "?Fdizpow")
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
lRa*:done
JMPIF

@n
8d0
CMP8S
GE0
lRa*:abs_done
JMPIF

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
lRa*:end_loop
JMPIF

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

lRa*:loop
JMP

:end_loop

@exponent
CONV-BCC(SI_4_I|SI_8_O)
8d0
CMP8S
GE0
lRa*:done
JMPIF

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
