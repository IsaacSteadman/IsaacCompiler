from ...Compilation import CompileObjectType
from .lib_utils import lib_utils_abi
from ..assemble import assemble


# declared as `int print(const char *str);`
print_fn = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "?FPCczprint")
assemble(print_fn, {"res": (0x18, 4), "str": (0x10, 8)}, """
8d0

8d0
8d0
8d0
@str
8x21
gRa*?Fyyyyyzsyscall
CALL
1d40
RST_SP1

lRa*res
STOR-ABS_S8|SZ_4

RET
""")


# assemble(print_fn, {"res": (0x18, 4), "str": (0x10, 8)}, """\
# @str
# 1x09
# INT-1x(21)
# 1d9
# RST_SP1
# 4d0
# lRa*res
# STOR-ABS_S8|SZ_4
# RET
# """)