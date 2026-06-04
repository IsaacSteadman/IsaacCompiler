from functools import lru_cache
import os

from ..Preprocessing import preprocess
from ..code_gen.Compilation import Compilation
from ..code_gen.NameMangling import NameManglingMode, normalize_name_mangling_mode
from ..code_gen.compile_stmnt import compile_stmnt
from ..code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import get_lib_utils_abi
from ..lexer.lexer import get_list_tokens
from ..parser.stmnt.get_stmnt import get_stmnt
from ..parser.type.types import CompileContext


def _compile_support_file(path: str, mode: NameManglingMode) -> Compilation:
    with open(path, "r") as fl:
        source = fl.read()
    package_root = os.path.dirname(os.path.dirname(__file__))
    include_dirs = [
        os.path.dirname(path),
        os.path.join(package_root, "StackVM", "include"),
    ]
    source = preprocess(source, include_dirs)
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None, name_mangling_mode=mode)
    cmpl_obj = Compilation(False, mode)
    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)
    return cmpl_obj


@lru_cache(maxsize=None)
def get_builtins_abi(
    mode: NameManglingMode = NameManglingMode.NONE,
) -> Compilation:
    mode = normalize_name_mangling_mode(mode)
    return _compile_support_file(
        os.path.join(os.path.dirname(__file__), "builtins.c"),
        mode,
    )


@lru_cache(maxsize=None)
def get_runtime_extern_deps(
    mode: NameManglingMode = NameManglingMode.NONE,
):
    mode = normalize_name_mangling_mode(mode)
    deps = dict(get_lib_utils_abi(mode).objects)
    deps.update(get_builtins_abi(mode).objects)
    return deps


builtins_abi = get_builtins_abi()
runtime_extern_deps = get_runtime_extern_deps()
