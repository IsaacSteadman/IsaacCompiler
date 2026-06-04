from ...Compilation import CompileObjectType
from ..assemble import assemble


# declared as `void *memcpy(void *dest, const void *src, unsigned long long size)`
def add_memcpy(compilation, link_name, memmove_link_name):
    mem_cpy = compilation.spawn_compile_object(CompileObjectType.FUNCTION, link_name)
    assemble(mem_cpy, {"dest": (0x10, 8), "src": (0x18, 8), "size": (0x20, 8), "res": (0x28, 8)}, f"""
1d8
ADD_SP1
@size
@src
@dest
gRa*{memmove_link_name}
CALL
1d32
RST_SP1
@dest
lRa*res
STOR-ABS_S8|SZ_8
RET
""")
    return mem_cpy
