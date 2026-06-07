import os
import sys
import unittest
import warnings

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import preprocess
from IsaacCompiler.StackVM.PyStackVM import VM
from IsaacCompiler.StackVM.runner import add_cmd_argv_vm
from IsaacCompiler.code_gen.Compilation import Compilation
from IsaacCompiler.code_gen.CompilerOptions import CompilerOptions
from IsaacCompiler.code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from IsaacCompiler.code_gen.compile_stmnt import compile_stmnt
from IsaacCompiler.code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import (
    lib_utils_abi,
)
from IsaacCompiler.code_gen.stackvm_binutils.object_file import SymbolType
from IsaacCompiler.lexer.lexer import get_list_tokens
from IsaacCompiler.parser.stmnt.get_stmnt import get_stmnt
from IsaacCompiler.parser.type.align_size_of import size_of
from IsaacCompiler.parser.type.CompileContext import CompileContext


def _parse_source(source, default_alignment=None):
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, default_alignment)
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


def _compile_source(
    source, remove_unused_deps=True, default_alignment=None, standalone=False
):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, default_alignment)

    link_opts = LinkerOptions(
        remove_unused_deps,
        4096,
        lib_utils_abi.objects,
        LNK_RUN_STANDALONE,
        default_alignment,
    )
    cmpl_opts = CompilerOptions(link_opts, True, False)
    cmpl_obj = Compilation(cmpl_opts.keep_local_syms)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

    if standalone:
        cmpl_obj.emit_standalone_startup(global_ctx.vars["main"].get_link_name())

    dep_tree = [("", sorted(cmpl_obj.linkages))]
    for key, obj in cmpl_obj.objects.items():
        dep_tree.append((key, sorted(obj.linkages)))
    dep_tree.extend(cmpl_obj.alias_dependency_entries())
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


def _compile_object_source(source, default_alignment=None):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, default_alignment)

    link_opts = LinkerOptions(
        True,
        4096,
        lib_utils_abi.objects,
        0,
        default_alignment,
    )
    cmpl_obj = Compilation(False, default_alignment=default_alignment)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

    cmpl_obj.finalize_global_initializer()
    return global_ctx, cmpl_obj.to_stackvm_object(
        link_opts.extern_deps, default_alignment
    )


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


def _attr_names(node):
    return sorted(attr.name for attr in getattr(node, "attributes", []))


def _get_attr(node, name):
    for attr in getattr(node, "attributes", []):
        if attr.name == name:
            return attr
    return None


class AttributeParserTests(unittest.TestCase):
    def test_unknown_attribute_between_qualifiers_is_ignored(self):
        global_ctx, cmpl_obj = _compile_source(
            "const __attribute__((unknown_attr(1), unused)) int x = 7; "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )

        self.assertEqual(_attr_names(global_ctx.vars["x"]), ["unused"])
        addr = _get_global_addr(global_ctx, cmpl_obj, "x")
        self.assertEqual(cmpl_obj.memory[addr : addr + 4], bytes([7, 0, 0, 0]))

    def test_decl_attributes_are_stored_on_decl_and_context_variable(self):
        global_ctx, stmnts = _parse_source(
            '__attribute__((deprecated("use_y"), noinline)) '
            "int __attribute__((aligned(8), weak)) x;"
        )

        decl = stmnts[0].decl_lst[0]
        ctx_var = global_ctx.vars["x"]
        self.assertEqual(
            _attr_names(decl),
            ["aligned", "deprecated", "noinline", "weak"],
        )
        self.assertEqual(_attr_names(ctx_var), _attr_names(decl))
        self.assertEqual(ctx_var.align_override, 8)
        self.assertEqual(_get_attr(decl, "deprecated").args, ['"use_y"'])

    def test_struct_member_attributes_are_stored(self):
        global_ctx, _stmnts = _parse_source(
            "struct S { "
            "    __attribute__((unused, unknown_member(1))) "
            "    const __attribute__((aligned(8))) int member; "
            "};"
        )

        struct_type = global_ctx.types["S"]
        member = struct_type.var_order[0]
        self.assertEqual(_attr_names(member), ["aligned", "unused"])
        self.assertEqual(member.align_override, 8)

    def test_struct_type_attributes_are_stored_and_applied(self):
        global_ctx, _stmnts = _parse_source(
            "__attribute__((packed, mystery_attr(1), aligned(4))) "
            "struct Packet { unsigned char a; };"
        )

        struct_type = global_ctx.types["Packet"]
        self.assertEqual(_attr_names(struct_type), ["aligned", "packed"])
        self.assertTrue(struct_type.is_packed)
        self.assertEqual(struct_type.align_override, 4)

    def test_section_attribute_is_decoded_and_stored_on_declarations(self):
        global_ctx, stmnts = _parse_source(
            'void __attribute__((section(".init.text"))) init(void); '
            'int __attribute__((section(".data.cacheline_aligned"))) cache;'
        )

        self.assertEqual(global_ctx.vars["init"].section_name, ".init.text")
        self.assertEqual(
            global_ctx.vars["cache"].section_name,
            ".data.cacheline_aligned",
        )
        self.assertEqual(
            _get_attr(stmnts[0].decl_lst[0], "section").args, ['".init.text"']
        )

    def test_alias_attribute_emits_object_symbol_at_target(self):
        _global_ctx, obj = _compile_object_source(
            "int target(void) { return 41; } "
            'extern int alias_fn(void) __attribute__((alias("target"))); '
            "int call_alias(void) { return alias_fn(); }\n"
        )

        symbols = {symbol.name: symbol for symbol in obj.symbols}
        self.assertIn("target", symbols)
        self.assertIn("alias_fn", symbols)
        self.assertEqual(symbols["alias_fn"].typ, SymbolType.FUNCTION)
        self.assertEqual(symbols["alias_fn"].value, symbols["target"].value)
        self.assertEqual(
            symbols["alias_fn"].section_index,
            symbols["target"].section_index,
        )

    def test_cleanup_attribute_runs_on_scope_exit_break_and_return(self):
        global_ctx, cmpl_obj = _compile_source(
            "int trace = 0; "
            "void cleanup_int(int *value) { trace = trace * 10 + *value; } "
            "int main(int argc, char **argv) { "
            "    { int a __attribute__((cleanup(cleanup_int))) = 1; trace = 2; } "
            "    while (trace < 30) { "
            "        int b __attribute__((cleanup(cleanup_int))) = 3; "
            "        break; "
            "    } "
            "    { int c __attribute__((cleanup(cleanup_int))) = 4; return 0; } "
            "}\n",
            standalone=True,
        )

        vm = _run_program(cmpl_obj)
        trace_addr = _get_global_addr(global_ctx, cmpl_obj, "trace")
        self.assertEqual(
            int.from_bytes(vm.memory[trace_addr : trace_addr + 4], "little", signed=True),
            2134,
        )

    def test_used_attribute_retains_unreferenced_symbol(self):
        global_ctx, cmpl_obj = _compile_source(
            "static int retained __attribute__((used)) = 123; "
            "static int dropped = 456; "
            "int main(int argc, char **argv) { return 0; }\n",
            standalone=True,
        )

        retained_name = global_ctx.vars["retained"].get_link_name()
        dropped_name = global_ctx.vars["dropped"].get_link_name()
        self.assertIsNotNone(cmpl_obj.linkages[retained_name].src)
        self.assertNotIn(dropped_name, cmpl_obj.linkages)

    def test_error_and_warning_attributes_fire_on_call(self):
        with self.assertRaisesRegex(TypeError, "bad call"):
            _compile_source(
                'extern void bad(void) __attribute__((error("bad call"))); '
                "int main(int argc, char **argv) { bad(); return 0; }\n"
            )

        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            _compile_source(
                'extern void careful(void) __attribute__((warning("careful call"))); '
                "void careful(void) {} "
                "int main(int argc, char **argv) { careful(); return 0; }\n",
                remove_unused_deps=False,
            )
        self.assertTrue(any("careful call" in str(item.message) for item in seen))

    def test_mode_attribute_changes_integer_type_size(self):
        global_ctx, _stmnts = _parse_source(
            "typedef unsigned int u8 __attribute__((mode(QI))); "
            "typedef signed int s16 __attribute__((__mode__(__HI__))); "
            "u8 a; s16 b;"
        )

        self.assertEqual(size_of(global_ctx.types["u8"].get_underlying_type()), 1)
        self.assertEqual(size_of(global_ctx.types["s16"].get_underlying_type()), 2)
        self.assertEqual(size_of(global_ctx.vars["a"].typ), 1)
        self.assertEqual(size_of(global_ctx.vars["b"].typ), 2)

    def test_fallthrough_attribute_statement_is_noop(self):
        _compile_source(
            "int main(int argc, char **argv) { "
            "    int value = 0; "
            "    switch (value) { "
            "    case 0: value = 1; __attribute__((fallthrough)); "
            "    case 1: return value + 1; "
            "    default: return 0; "
            "    } "
            "}\n",
            standalone=True,
        )


if __name__ == "__main__":
    unittest.main()
