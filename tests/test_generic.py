import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from IsaacCompiler.code_gen.Compilation import INIT_GLOBALS_LINK_NAME
from IsaacCompiler.parser.ParsingError import ParsingError

try:
    from tests.test_builtin_types_compatible_p import (
        _compile_source,
        _get_global_addr,
        _run_program,
    )
except ModuleNotFoundError:
    from test_builtin_types_compatible_p import (
        _compile_source,
        _get_global_addr,
        _run_program,
    )


class GenericSelectionTests(unittest.TestCase):
    def test_generic_selects_function_for_controlling_expression_type(self):
        global_ctx, cmpl_obj = _compile_source(
            "#define classify(x) _Generic((x), "
            "    float: classify_f, "
            "    double: classify_d, "
            "    long double: classify_ld)(x)\n"
            "int result = 0; "
            "int classify_f(float x) { return 10; } "
            "int classify_d(double x) { return 20; } "
            "int classify_ld(long double x) { return 30; } "
            "int main(int argc, char **argv) { "
            "    float f = 0.0f; "
            "    double d = 0.0; "
            "    long double ld; "
            "    result = classify(f) + classify(d) + classify(ld); "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )

        vm = _run_program(cmpl_obj)
        result_addr = _get_global_addr(global_ctx, cmpl_obj, "result")
        self.assertEqual(
            int.from_bytes(vm.memory[result_addr : result_addr + 4], "little", signed=True),
            60,
        )

    def test_generic_uses_default_and_folds_global_initializer(self):
        global_ctx, cmpl_obj = _compile_source(
            "const int ci = 0; "
            "int arr[2]; "
            '_Static_assert(_Generic((ci), int: 1, default: 0), "const match"); '
            '_Static_assert(_Generic((arr), int *: 1, default: 0), "array decay"); '
            "int const_match = _Generic((ci), int: 7, default: 9); "
            "int default_match = _Generic(1.0, float: 1, default: 2); "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )

        const_match_addr = _get_global_addr(global_ctx, cmpl_obj, "const_match")
        default_match_addr = _get_global_addr(global_ctx, cmpl_obj, "default_match")
        self.assertEqual(
            cmpl_obj.memory[const_match_addr : const_match_addr + 4],
            bytes([7, 0, 0, 0]),
        )
        self.assertEqual(
            cmpl_obj.memory[default_match_addr : default_match_addr + 4],
            bytes([2, 0, 0, 0]),
        )
        self.assertNotIn(INIT_GLOBALS_LINK_NAME, cmpl_obj.objects)

    def test_generic_static_assert_evaluates_selected_branch(self):
        with self.assertRaisesRegex(ParsingError, "static assertion failed"):
            _compile_source(
                '_Static_assert(_Generic(1.0, int: missing_name, default: 0), '
                '"default selected"); '
                "int main(int argc, char **argv) { return 0; }\n",
                remove_unused_deps=False,
            )

    def test_generic_does_not_typecheck_or_evaluate_unselected_branches(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result = 0; "
            "int hits = 0; "
            "int side_effect(void) { hits = 99; return hits; } "
            "int id(int x) { return x; } "
            "int main(int argc, char **argv) { "
            "    int i = 0; "
            "    result = id(_Generic((i), "
            "        double: missing_identifier + 1, "
            "        int: 42, "
            "        default: side_effect())); "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )

        vm = _run_program(cmpl_obj)
        result_addr = _get_global_addr(global_ctx, cmpl_obj, "result")
        hits_addr = _get_global_addr(global_ctx, cmpl_obj, "hits")
        self.assertEqual(
            int.from_bytes(vm.memory[result_addr : result_addr + 4], "little", signed=True),
            42,
        )
        self.assertEqual(
            int.from_bytes(vm.memory[hits_addr : hits_addr + 4], "little", signed=True),
            0,
        )


if __name__ == "__main__":
    unittest.main()
