import os

from ..Preprocessing import preprocess
from ..code_gen.Compilation import Compilation
from ..code_gen.compile_stmnt import compile_stmnt
from ..code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import lib_utils_abi
from ..lexer.lexer import get_list_tokens
from ..parser.stmnt.get_stmnt import get_stmnt
from ..parser.type.types import CompileContext


def _compile_support_file(path: str) -> Compilation:
    with open(path, "r") as fl:
        source = fl.read()
    package_root = os.path.dirname(os.path.dirname(__file__))
    include_dirs = [
        os.path.dirname(path),
        os.path.join(package_root, "StackVM", "include"),
    ]
    source = preprocess(source, include_dirs)
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)
    cmpl_obj = Compilation(False)
    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)
    return cmpl_obj


builtins_abi = _compile_support_file(os.path.join(os.path.dirname(__file__), "builtins.c"))
runtime_extern_deps = dict(lib_utils_abi.objects)
runtime_extern_deps.update(builtins_abi.objects)
