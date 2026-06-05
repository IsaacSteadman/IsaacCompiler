import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from tests.test_builtin_memory import (
    _compile_source,
    _get_global_addr,
    _read_global,
    _run_program,
)


def _read_global_bytes(vm, global_ctx, cmpl_obj, name, size):
    addr = _get_global_addr(global_ctx, cmpl_obj, name)
    return bytes(vm.memory[addr : addr + size])


def _read_c_string(vm, global_ctx, cmpl_obj, name, max_size):
    data = _read_global_bytes(vm, global_ctx, cmpl_obj, name, max_size)
    return data.split(b"\0", 1)[0].decode("ascii")


class FreestandingRuntimeTests(unittest.TestCase):
    def test_string_header_and_runtime_functions(self):
        global_ctx, cmpl_obj = _compile_source(
            "#include <string.h>\n"
            "char copy_buf[16]; "
            "char pad_buf[8]; "
            "int string_flags = 0; "
            "size_t copy_len = 0; "
            "int main(int argc, char **argv) { "
            "    char *ret1 = strcpy(copy_buf, \"abc\"); "
            "    char *ret2 = strncpy(pad_buf, \"xy\", 5); "
            "    copy_len = strlen(copy_buf); "
            "    if (ret1 == copy_buf) { string_flags = string_flags + 1; } "
            "    if (ret2 == pad_buf) { string_flags = string_flags + 2; } "
            "    if (strcmp(copy_buf, \"abc\") == 0) { string_flags = string_flags + 4; } "
            "    if (strcmp(\"abc\", \"abd\") < 0) { string_flags = string_flags + 8; } "
            "    if (strncmp(\"abc\", \"abd\", 2) == 0) { string_flags = string_flags + 16; } "
            "    if (strncmp(\"abc\", \"abd\", 3) < 0) { string_flags = string_flags + 32; } "
            "    if (memcmp((const void *)\"abc\", (const void *)\"abd\", 2) == 0) { string_flags = string_flags + 64; } "
            "    if (memcmp((const void *)\"abc\", (const void *)\"abd\", 3) < 0) { string_flags = string_flags + 128; } "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)

        self.assertEqual(_read_c_string(vm, global_ctx, cmpl_obj, "copy_buf", 16), "abc")
        self.assertEqual(
            _read_global_bytes(vm, global_ctx, cmpl_obj, "pad_buf", 6),
            b"xy\0\0\0\0",
        )
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "copy_len", 8), 3)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "string_flags", 4), 255)

    def test_stdio_formatting_functions(self):
        global_ctx, cmpl_obj = _compile_source(
            "#include <stdio.h>\n"
            "#include <stdarg.h>\n"
            "char fmt_buf[128]; "
            "char tiny_buf[6]; "
            "char via_va[80]; "
            "char sprintf_buf[80]; "
            "int n_main = 0; "
            "int n_tiny = 0; "
            "int n_va = 0; "
            "int n_sprintf = 0; "
            "int n_null = 0; "
            "int call_vfmt(char *out, size_t size, const char *fmt, ...) { "
            "    va_list ap; "
            "    int result; "
            "    va_start(ap, fmt); "
            "    result = vsnprintf(out, size, fmt, ap); "
            "    va_end(ap); "
            "    return result; "
            "} "
            "int main(int argc, char **argv) { "
            "    n_main = snprintf( "
            "        fmt_buf, 128, "
            "        \"msg:%s:%d:%u:%#x:%04d:%c:%%:%p\", "
            "        \"vm\", -42, 42U, 0x2aU, 7, 'Z', fmt_buf); "
            "    n_tiny = snprintf(tiny_buf, 6, \"abcdef%d\", 9); "
            "    n_va = call_vfmt( "
            "        via_va, 80, \"%-5s:%.*s:%lld:%08X\", "
            "        \"x\", 3, \"abcdef\", -1234567890123LL, 0xBEEFU); "
            "    n_sprintf = sprintf( "
            "        sprintf_buf, \"%ld:%lu:%zu\", "
            "        (long)-17, (unsigned long)123UL, (size_t)456ULL); "
            "    n_null = snprintf(fmt_buf, 0, \"count:%u\", 123U); "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)

        expected_main = (
            "msg:vm:-42:42:0x2a:0007:Z:%:"
            + hex(_get_global_addr(global_ctx, cmpl_obj, "fmt_buf"))
        )
        expected_va = "x    :abc:-1234567890123:0000BEEF"
        expected_sprintf = "-17:123:456"

        self.assertEqual(_read_c_string(vm, global_ctx, cmpl_obj, "fmt_buf", 128), expected_main)
        self.assertEqual(_read_c_string(vm, global_ctx, cmpl_obj, "tiny_buf", 6), "abcde")
        self.assertEqual(_read_c_string(vm, global_ctx, cmpl_obj, "via_va", 80), expected_va)
        self.assertEqual(
            _read_c_string(vm, global_ctx, cmpl_obj, "sprintf_buf", 80),
            expected_sprintf,
        )
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "n_main", 4), len(expected_main))
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "n_tiny", 4), 7)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "n_va", 4), len(expected_va))
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "n_sprintf", 4),
            len(expected_sprintf),
        )
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "n_null", 4), 9)

    def test_linux_math64_division_helpers(self):
        global_ctx, cmpl_obj = _compile_source(
            "#include <linux/math64.h>\n"
            "uint64_t q64 = 0; "
            "uint64_t q32 = 0; "
            "uint32_t rem32 = 0; "
            "int main(int argc, char **argv) { "
            "    q64 = div64_u64(1000000000000ULL, 97ULL); "
            "    q32 = div_u64_rem(1000000000000ULL, 97U, &rem32); "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)
        dividend = 1_000_000_000_000
        divisor = 97

        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "q64", 8),
            dividend // divisor,
        )
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "q32", 8),
            dividend // divisor,
        )
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "rem32", 4),
            dividend % divisor,
        )


if __name__ == "__main__":
    unittest.main()
