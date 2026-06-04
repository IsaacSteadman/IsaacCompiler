from functools import lru_cache

from ...Compilation import Compilation
from ...NameMangling import NameManglingMode, normalize_name_mangling_mode
from .ByteCopyFn import add_byte_copy_fn
from .ByteCopyFn1 import add_byte_copy_fn1
from .ByteCopyFn2 import add_byte_copy_fn2
from .memcpy import add_memcpy
from .memmove import add_memmove
from .memset import add_memset
from .names import get_runtime_link_name
from .pow_fn import add_pow
from .print_fn import add_print
from .syscall import add_syscall


@lru_cache(maxsize=None)
def get_lib_utils_abi(
    mode: NameManglingMode = NameManglingMode.NONE,
) -> Compilation:
    mode = normalize_name_mangling_mode(mode)
    compilation = Compilation(False, mode)
    names = {
        name: get_runtime_link_name(name, mode)
        for name in ("memcpy", "memmove", "memset", "print", "syscall", "pow")
    }
    add_memmove(compilation, names["memmove"])
    add_memcpy(compilation, names["memcpy"], names["memmove"])
    add_memset(compilation, names["memset"])
    add_syscall(compilation, names["syscall"])
    add_print(compilation, names["print"], names["syscall"])
    add_pow(compilation, names["pow"])
    add_byte_copy_fn(compilation)
    add_byte_copy_fn1(compilation)
    add_byte_copy_fn2(compilation)
    return compilation


lib_utils_abi = get_lib_utils_abi()
