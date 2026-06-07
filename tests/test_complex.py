import os
import struct
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

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


def _read_double(vm, global_ctx, cmpl_obj, name):
    addr = _get_global_addr(global_ctx, cmpl_obj, name)
    return struct.unpack("<d", vm.memory[addr : addr + 8])[0]


def _read_int(vm, global_ctx, cmpl_obj, name):
    addr = _get_global_addr(global_ctx, cmpl_obj, name)
    return int.from_bytes(vm.memory[addr : addr + 4], "little", signed=True)


class ComplexTypeTests(unittest.TestCase):
    def test_complex_types_parse_and_have_expected_layout(self):
        _compile_source(
            '#include <complex.h>\n'
            '_Static_assert(sizeof(float _Complex) == 8, "complex float size");\n'
            '_Static_assert(sizeof(double complex) == 16, "complex double size");\n'
            '_Static_assert(sizeof(_Complex) == 16, "default complex double size");\n'
            "double _Complex static_pair = {3.0, 4.0};\n"
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )

    def test_complex_arithmetic_real_imag_and_complex_h_macros(self):
        global_ctx, cmpl_obj = _compile_source(
            '#include <complex.h>\n'
            "double out_sum_r = 0.0, out_sum_i = 0.0;\n"
            "double out_prod_r = 0.0, out_prod_i = 0.0;\n"
            "double out_div_r = 0.0, out_div_i = 0.0;\n"
            "int out_cmp = 0, out_bool = 0;\n"
            "int main(int argc, char **argv) {\n"
            "    double complex a = CMPLX(3.0, 4.0);\n"
            "    double complex b = 1.0 + 2.0 * I;\n"
            "    double complex sum = a + b;\n"
            "    double complex prod = a * b;\n"
            "    double complex quot = prod / b;\n"
            "    sum += 1.0;\n"
            "    __imag__ sum = __imag__ sum - 3.0;\n"
            "    out_sum_r = creal(sum);\n"
            "    out_sum_i = cimag(sum);\n"
            "    out_prod_r = creal(prod);\n"
            "    out_prod_i = cimag(prod);\n"
            "    out_div_r = creal(quot);\n"
            "    out_div_i = cimag(quot);\n"
            "    out_cmp = (int)(quot == a) + 2 * (int)(a != b);\n"
            "    out_bool = (int)!CMPLX(0.0, 0.0) + 2 * (int)!!CMPLX(0.0, 5.0);\n"
            "    return 0;\n"
            "}\n",
            remove_unused_deps=False,
        )

        vm = _run_program(cmpl_obj)
        self.assertAlmostEqual(_read_double(vm, global_ctx, cmpl_obj, "out_sum_r"), 5.0)
        self.assertAlmostEqual(_read_double(vm, global_ctx, cmpl_obj, "out_sum_i"), 3.0)
        self.assertAlmostEqual(_read_double(vm, global_ctx, cmpl_obj, "out_prod_r"), -5.0)
        self.assertAlmostEqual(_read_double(vm, global_ctx, cmpl_obj, "out_prod_i"), 10.0)
        self.assertAlmostEqual(_read_double(vm, global_ctx, cmpl_obj, "out_div_r"), 3.0)
        self.assertAlmostEqual(_read_double(vm, global_ctx, cmpl_obj, "out_div_i"), 4.0)
        self.assertEqual(_read_int(vm, global_ctx, cmpl_obj, "out_cmp"), 3)
        self.assertEqual(_read_int(vm, global_ctx, cmpl_obj, "out_bool"), 3)


if __name__ == "__main__":
    unittest.main()
