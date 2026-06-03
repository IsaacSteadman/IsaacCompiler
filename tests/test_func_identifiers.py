import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import preprocess
from IsaacCompiler.StackVM.PyStackVM import BC_CALL, BC_HLT, BC_RET, VM
from IsaacCompiler.StackVM.runner import add_cmd_argv_vm
from IsaacCompiler.code_gen.Compilation import Compilation, INIT_GLOBALS_LINK_NAME
from IsaacCompiler.code_gen.CompilerOptions import CompilerOptions
from IsaacCompiler.code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from IsaacCompiler.code_gen.compile_stmnt import compile_stmnt
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from IsaacCompiler.code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import lib_utils_abi
from IsaacCompiler.lexer.lexer import get_list_tokens
from IsaacCompiler.parser.expr.LiteralExpr import LiteralExpr
from IsaacCompiler.parser.stmnt.get_stmnt import get_stmnt
from IsaacCompiler.parser.type.types import (
    CompileContext,
    ContextVariable,
    PrimitiveType,
    PrimitiveTypeId,
    QualType,
    TypeDefCtxMember,
    VarDeclMods,
)


def _parse_source(source):
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)
    stmnts = []
    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        stmnts.append(stmnt)
    return global_ctx, stmnts


def _flatify_dep_desc(dep_dct, start_key):
    result = set()
    pending = {start_key}
    while pending:
        current = pending
        result |= current
        pending = set()
        for key in current:
            pending.update(dep_dct[key])
        pending -= result
    return result


def _compile_source(source, remove_unused_deps=True):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)
    va_base = PrimitiveType.from_str_name(["unsigned", "char"])
    va_type = QualType(QualType.QUAL_PTR, va_base)
    global_ctx.new_type("va_list", TypeDefCtxMember("va_list", global_ctx, va_type))

    link_opts = LinkerOptions(
        remove_unused_deps,
        4096,
        lib_utils_abi.objects,
        LNK_RUN_STANDALONE,
        None,
    )
    cmpl_opts = CompilerOptions(link_opts, True, False)
    cmpl_obj = Compilation(cmpl_opts.keep_local_syms)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

    init_obj = cmpl_obj.objects.get(INIT_GLOBALS_LINK_NAME)
    if init_obj is not None:
        init_obj.memory.append(BC_RET)
        cmpl_obj.get_link(INIT_GLOBALS_LINK_NAME).emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_CALL])

    main_fn = cmpl_obj.get_link("?FiPPczmain")
    emit_load_i_const(cmpl_obj.memory, 1, True, 2)
    main_fn.emit_lea(cmpl_obj.memory)
    cmpl_obj.memory.extend([BC_CALL, BC_HLT])

    dep_tree = [("", sorted(cmpl_obj.linkages))]
    for key, obj in cmpl_obj.objects.items():
        dep_tree.append((key, sorted(obj.linkages)))
    if link_opts.extern_deps is not None:
        for key, obj in link_opts.extern_deps.items():
            dep_tree.append((key, sorted(obj.linkages)))
    dep_dct = dict(dep_tree)
    used_deps = _flatify_dep_desc(dep_dct, "")
    defined_deps = {key for key, _deps in dep_tree if key}
    unused_deps = defined_deps - used_deps
    excl = unused_deps if link_opts.remove_unused_deps else None

    cmpl_obj.merge_all(link_opts, link_opts.extern_deps, excl)
    assert cmpl_obj.link_all()
    return global_ctx, cmpl_obj


def _run_program(cmpl_obj):
    vm = VM(65536)
    vm.load_program(cmpl_obj.memory, 0)
    vm.push(4, 0)
    add_cmd_argv_vm(vm, len(cmpl_obj.memory), ["prog"])
    vm.execute()
    return vm


def _get_global_addr(global_ctx, cmpl_obj, name):
    ctx_var = global_ctx.vars[name]
    return cmpl_obj.get_link(ctx_var.get_link_name()).src


def _read_global(vm, global_ctx, cmpl_obj, name, size, signed=False):
    addr = _get_global_addr(global_ctx, cmpl_obj, name)
    return int.from_bytes(vm.memory[addr : addr + size], "little", signed=signed)


class FunctionIdentifierTests(unittest.TestCase):
    def test_function_body_injects___func___and___FUNCTION___alias(self):
        _global_ctx, stmnts = _parse_source(
            "int helper(void) { return __func__[0] + __FUNCTION__[1]; }"
        )

        fn_body = stmnts[0].decl_lst[0].init_args[0]
        func_var = fn_body.context.var_name_strict("__func__")
        alias_var = fn_body.context.var_name_strict("__FUNCTION__")
        self.assertIsInstance(func_var, ContextVariable)
        self.assertIs(alias_var, func_var)
        self.assertEqual(func_var.name, "__func__")
        self.assertEqual(func_var.mods, VarDeclMods.STATIC)
        self.assertIsInstance(func_var.typ, QualType)
        self.assertEqual(func_var.typ.qual_id, QualType.QUAL_ARR)
        self.assertEqual(func_var.typ.ext_inf, len("helper") + 1)
        self.assertIsInstance(func_var.typ.tgt_type, QualType)
        self.assertEqual(func_var.typ.tgt_type.qual_id, QualType.QUAL_CONST)
        self.assertEqual(func_var.typ.tgt_type.tgt_type.typ, PrimitiveTypeId.INT_C)
        self.assertIsInstance(func_var.init_expr, LiteralExpr)
        self.assertEqual(func_var.init_expr.t_lit, LiteralExpr.LIT_STR)
        self.assertEqual("".join(map(chr, func_var.init_expr.l_val)), "helper")

    def test_runtime___func___storage_uses_function_name_and_aliases___FUNCTION__(self):
        global_ctx, cmpl_obj = _compile_source(
            "const char *fn_ptr; "
            "unsigned long long same_addr; "
            "int helper(void) { "
            "    fn_ptr = __func__; "
            "    same_addr = (__func__ == __FUNCTION__); "
            "    return 0; "
            "} "
            "int main(int argc, char **argv) { return helper(); }\n",
            remove_unused_deps=False,
        )

        vm = _run_program(cmpl_obj)
        fn_ptr = _read_global(vm, global_ctx, cmpl_obj, "fn_ptr", 8)
        self.assertEqual(bytes(vm.memory[fn_ptr : fn_ptr + 7]), b"helper\0")
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "same_addr", 8), 1)


if __name__ == "__main__":
    unittest.main()
