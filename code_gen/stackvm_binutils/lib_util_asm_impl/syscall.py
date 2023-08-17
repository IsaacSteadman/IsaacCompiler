from ...Compilation import CompileObjectType
from .lib_utils import lib_utils_abi
from ..assemble import assemble


# declared as `unsigned long long syscall(unsigned long long sys_n, unsigned long long arg0, unsigned long long arg1, unsigned long long arg2, unsigned long long arg3)`
syscall_fn = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "?Fyyyyyzsyscall")
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