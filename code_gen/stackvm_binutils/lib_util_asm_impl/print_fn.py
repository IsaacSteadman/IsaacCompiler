from ...Compilation import CompileObjectType
from ..assemble import assemble


# declared as `int print(const char *str);`
def add_print(compilation, link_name, syscall_link_name):
    print_fn = compilation.spawn_compile_object(CompileObjectType.FUNCTION, link_name)
    assemble(print_fn, {"res": (0x18, 4), "str": (0x10, 8)}, f"""
8d0

8d0
8d0
8d0
@str
8x21
gRa*{syscall_link_name}
CALL
1d40
RST_SP1

lRa*res
STOR-ABS_S8|SZ_4

RET
""")
    return print_fn


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
