from ...Compilation import CompileObjectType
from ..assemble import assemble


# declared as `void *memmove(void *dest, void *src, unsigned long long num)`
def add_memmove(compilation, link_name):
    mem_move = compilation.spawn_compile_object(CompileObjectType.FUNCTION, link_name)
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
lRr[1]*:end
RJMPIF
LT0
lRr[1]*:setupLoop1
RJMPIF
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
lRr[1]*:end
RJMPIF

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

lRr[1]*:beginLoop0
RJMP
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
lRr[1]*:end
RJMPIF

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

lRr[1]*:beginLoop1
RJMP

:end
~-srcEnd
RET
""")
    return mem_move


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
