from ...Compilation import CompileObjectType
from ..assemble import assemble


# declared as `unsigned long long syscall(unsigned long long sys_n, unsigned long long arg0, unsigned long long arg1, unsigned long long arg2, unsigned long long arg3)`
def add_syscall(compilation, link_name):
    syscall_fn = compilation.spawn_compile_object(CompileObjectType.FUNCTION, link_name)
    assemble(syscall_fn, {"sys_n": (0x10, 8), "arg0": (0x18, 8), "arg1": (0x20, 8), "arg2": (0x28, 8), "arg3": (0x30, 8), "res": (0x38, 8)}, """\
@arg3
@arg2
@arg1
@arg0
8d32
@sys_n
CALL_E-SYSCALL|S_SYSN_SZ8
8d8
SUB8
RST_SP8
lRa*res
STOR-ABS_S8|SZ_8
RET
""")
    return syscall_fn
