from ...Compilation import CompileObjectType
from .lib_utils import lib_utils_abi
from ..assemble import assemble


# declared as `void *memmove(void *dest, void *src, unsigned long long num)`
mem_move = lib_utils_abi.spawn_compile_object(CompileObjectType.FUNCTION, "?FPvPvyzmemmove")
assemble(mem_move, {"dest": (0x10, 8), "src": (0x18, 8), "num": (0x20, 8), "res": (0x28, 8)}, """
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