from ...Compilation import CompileObjectType
from .lib_utils import lib_utils_abi
from ..assemble import assemble


# declared as `void *memcpy(void *dest, const void *src, unsigned long long size)`
mem_cpy = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "?FPvPCvyzmemcpy")
assemble(mem_cpy, {"dest": (0x10, 8), "src": (0x18, 8), "size": (0x20, 8), "res": (0x28, 8)}, """
1d8
ADD_SP1
@size
@src
@dest
gRa*?FPvPvyzmemmove
CALL
1d32
RST_SP1
@dest
lRa*res
STOR-ABS_S8|SZ_8
RET
""")
