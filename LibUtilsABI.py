from Parsing import Compilation, CMPL_T_FUNCTION
from CompilingUtils import assemble


lib_utils_abi = Compilation(False)
# declared as `void *memcpy(void *dest, const void *src, unsigned long long size)`
mem_cpy = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "?FPvPCvyzmemcpy")
assemble(mem_cpy, {"dest": (0x10, 8), "src": (0x18, 8), "size": (0x20, 8), "res": (0x28, 8)}, """\
@dest
@src
@size
gRa*@@ByteCopyFn
CALL
1d24
RST_SP1
@dest
lRa*res
STOR-ABS_S8|SZ_8
""")
# declared as `void *memset(void * ptr, unsigned char value, unsigned long long num)`
mem_set = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "?FPvcyzmemset")
assemble(mem_set, {"ptr": (0x10, 8), "value": (0x18, 1), "num": (0x19, 8), "res": (0x21, 8)}, """\
@ptr
lRa*res
STOR-ABS_S8|SZ_8
~+end,8d0
@ptr
@num
ADD8
lRa*end
STOR-ABS_S8|SZ_8
:beginLoop
@ptr
@end
CMP8
GE0
lRa*:endLoop
JMPIF


@value
@ptr
STOR-ABS_S8|SZ_1

@ptr
8d1
ADD8
lRa*ptr
STOR-ABS_S8|SZ_8
lRa*:beginLoop
JMP
:endLoop
~-end
RET
""")
# declared as `void *memmove(void *dest, void *src, unsigned long long num)`
mem_move = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "?FPvPvyzmemmove")
assemble(mem_move, {"dest": (0x10, 8), "src": (0x18, 8), "num": (0x20, 8), "res": (0x28, 8)}, """\
~+srcEnd,8d0
@dest
lRa*res
STOR-ABS_S8|SZ_8
@dest
@src
CMP8
LOAD-TOS|SZ_1
EQ0
lRa*:end
JMPIF
LT0
lRa*:setupLoop1
JMPIF
@src
@num
ADD8
lRa*srcEnd
STOR-ABS_S8|SZ_8

:beginLoop0
@src
@srcEnd
CMP8
GE0
lRa*:end
JMPIF

@src
LOAD-ABS_S8|SZ_1
@dest
STOR-ABS_S8|SZ_1

@src
8d1
ADD8
lRa*src
STOR-ABS_S8|SZ_8

@dest
8d1
ADD8
lRa*dest
STOR-ABS_S8|SZ_8

lRa*:beginLoop0
JMP
:setupLoop1

@src
lRa*srcEnd
STOR-ABS_S8|SZ_8

@src
@num
ADD8
lRa*src
STOR-ABS_S8|SZ_8

@dest
@num
ADD8
lRa*dest
STOR-ABS_S8|SZ_8

:beginLoop1

@src
@srcEnd
CMP8
LE0
lRa*:end
JMPIF

@src
8d1
SUB8
lRa*src
STOR-ABS_S8|SZ_8

@dest
8d1
SUB8
lRa*dest
STOR-ABS_S8|SZ_8

@src
LOAD-ABS_S8|SZ_1
@dest
STOR-ABS_S8|SZ_1

lRa*:beginLoop1
JMP

:end
~-srcEnd
RET
""")
"""
void *memmove(void *dest, void *src, unsigned long long num) {
    if (dest == src) {
        return dest;
    }
    if (dest < src) {
        void *srcEnd = src + num;
        while (src < srcEnd) {
            *dest = *src;
            ++src;
            ++dest;
        }
    } else {
        dest += num;
        src += num;
        void *srcEnd = src;
        while (src > srcEnd) {
            --src;
            --dest;
            *dest = *src;
        }
    }
    // return the dest argument that was originally passed into this function
}"""
ByteCopyFn = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "@@ByteCopyFn")
assemble(ByteCopyFn, {"Sz": (0x10, 8), "src": (0x18, 8), "dest": (0x20, 8)}, """\
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

@dest
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
byte_copy_fn1 = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "@@ByteCopyFn1")
# reference to value at dest is replaced with a load from register BP offset by 16
#   (since bp represents the previous stack pointer)
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
byte_copy_fn2 = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "@@ByteCopyFn2")
# reference to value at src is replaced with a load from register BP offset by 16
#   (since bp represents the previous stack pointer)
assemble(byte_copy_fn2, {"Sz": (0x10, 8), "dest": (0x18, 8)}, """\
~+c,8d0
:checkFor
@c
@Sz
CMP8
LT0
EQ0
lRa*:endFor
JMPIF


LOAD-REG_BP|SZ_8
8x20
ADD8
@c
ADD8
LOAD-ABS_S8|SZ_1

@dest
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
# declared as `int print(const char *str);`
print_fn = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "?FPCczprint")
assemble(print_fn, {"res": (0x18, 4), "str": (0x10, 8)}, """\
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
# declared as `double pow(double base, int exponent);`
# pow_fn = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "?Fdizpow")
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
# draw_fn = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "")
# declared as `unsigned long long syscall(unsigned long long sys_n, unsigned long long arg0, unsigned long long arg1, unsigned long long arg2, unsigned long long arg3)`
syscall_fn = lib_utils_abi.spawn_compile_object(CMPL_T_FUNCTION, "?Fyyyyyzsyscall")
assemble(syscall_fn, {"sys_n": (0x10, 8), "arg0": (0x18, 8), "arg1": (0x20, 8), "arg2": (0x28, 8), "arg3": (0x30, 8), "res": (0x38, 8)}, """\
@arg3
@arg2
@arg1
@arg0
8d32
INT-1x(21)
@sys_n
CALL_E-SYSCALL|S_SYSN_SZ8
8d8
SUB8
RST_SP8
lRa*res
STOR-ABS_S8|SZ_8
RET
""")
