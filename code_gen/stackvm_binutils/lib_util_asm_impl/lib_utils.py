from ...Compilation import Compilation


lib_utils_abi = Compilation(False)


from . import memcpy
from . import memset
from . import memmove
from . import ByteCopyFn
from . import ByteCopyFn1
from . import ByteCopyFn2
from . import print_fn
from . import syscall


# declared as `double pow(double base, int exponent);`
# pow_fn = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "?Fdizpow")
# assemble(pow_fn, {"base": (0x10, 8), "exponent": (0x18, 4), "res": (0x1C, 8)}, """\
# 8d0
# @base
# @exponent
# 1x0
# INT-1x(29)
# 1d13
# RST_SP1
# lRa*res
# STOR-ABS_S8|SZ_8
# RET
# """)
# draw_fn = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "")