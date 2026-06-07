"""Tests for the A5 "preprocessor hardening" work.

Covers the constructs Linux headers rely on that were added to
``Preprocessing.py``:

  * full ``#if`` integer constant expressions — ternary ``?:``, character
    constants, integer suffixes, and the C11 identifier-to-0 rule;
  * ``__has_attribute`` / ``__has_builtin`` / ``__has_feature`` /
    ``__has_include`` inside ``#if``;
  * a hard error (instead of a silent "treat as 0") for genuinely
    unevaluable ``#if`` expressions;
  * the ``_Pragma`` operator;
  * the ``#line`` directive.
"""

import io
import os
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import Preprocessor, PreprocessorError, preprocess


def _write(path, text):
    with open(path, "w", encoding="utf-8") as file_obj:
        file_obj.write(text)


def _run_if(condition_lines):
    """Preprocess a tiny ``#if`` program and return the surviving tokens."""
    source = condition_lines + "\nTAKEN\n#else\nNOT_TAKEN\n#endif\n"
    return preprocess(source, []).split()


# ---------------------------------------------------------------------------
# _eval_int_expr — direct unit coverage
# ---------------------------------------------------------------------------


class EvalIntExprTests(unittest.TestCase):
    def setUp(self):
        self.eval = Preprocessor([])._eval_int_expr

    def test_integer_suffixes(self):
        self.assertEqual(self.eval("100"), 100)
        self.assertEqual(self.eval("100u"), 100)
        self.assertEqual(self.eval("100L"), 100)
        self.assertEqual(self.eval("100UL"), 100)
        self.assertEqual(self.eval("100ull"), 100)
        self.assertEqual(self.eval("0x10UL"), 16)
        self.assertEqual(self.eval("0xffULL"), 255)
        self.assertEqual(self.eval("0b1010"), 10)

    def test_c_style_octal(self):
        # Linux headers use octal permission constants (0644, 0777, ...).
        self.assertEqual(self.eval("0777"), 0o777)
        self.assertEqual(self.eval("0644"), 0o644)
        self.assertEqual(self.eval("0"), 0)
        self.assertEqual(self.eval("0644 | 0022"), 0o644 | 0o22)
        self.assertEqual(_run_if("#if 0644 == 420"), ["TAKEN"])

    def test_ternary_basic(self):
        self.assertEqual(self.eval("1 ? 2 : 3"), 2)
        self.assertEqual(self.eval("0 ? 2 : 3"), 3)
        self.assertEqual(self.eval("(5 > 3) ? 10 : 20"), 10)

    def test_ternary_nested_right_associative(self):
        # 1 ? (0 ? 5 : 6) : 7  ->  6
        self.assertEqual(self.eval("1 ? 0 ? 5 : 6 : 7"), 6)
        # 0 ? 1 : 2 ? 3 : 4  ->  0 ? 1 : (2 ? 3 : 4)  ->  3
        self.assertEqual(self.eval("0 ? 1 : 2 ? 3 : 4"), 3)

    def test_ternary_lower_precedence_than_binary(self):
        # 1 + 1 == 2 ? 100 : 200  ->  ((1+1)==2) ? 100 : 200 -> 100
        self.assertEqual(self.eval("1 + 1 == 2 ? 100 : 200"), 100)

    def test_character_constants(self):
        self.assertEqual(self.eval("'A'"), 65)
        self.assertEqual(self.eval("'0'"), 48)
        self.assertEqual(self.eval("' '"), 32)

    def test_character_escapes(self):
        self.assertEqual(self.eval(r"'\n'"), 10)
        self.assertEqual(self.eval(r"'\t'"), 9)
        self.assertEqual(self.eval(r"'\r'"), 13)
        self.assertEqual(self.eval(r"'\0'"), 0)
        self.assertEqual(self.eval(r"'\\'"), 92)
        self.assertEqual(self.eval(r"'\''"), 39)
        self.assertEqual(self.eval(r"'\x41'"), 0x41)
        self.assertEqual(self.eval(r"'\101'"), 0o101)  # octal == 'A'

    def test_multi_character_constant(self):
        self.assertEqual(self.eval("'AB'"), (0x41 << 8) | 0x42)

    def test_high_bit_narrow_char_is_signed(self):
        # Narrow char carries the value of a (signed) char, matching GCC.
        self.assertEqual(self.eval(r"'\xff'"), -1)
        self.assertEqual(self.eval(r"'\x80'"), -128)

    def test_operator_character_constants_not_split(self):
        # The quoted operator characters must not be mistaken for operators.
        self.assertEqual(self.eval("'<'"), 60)
        self.assertEqual(self.eval("'>'"), 62)
        self.assertEqual(self.eval("'|'"), 124)
        self.assertEqual(self.eval("'&'"), 38)
        self.assertEqual(self.eval("'+'"), 43)
        self.assertEqual(self.eval("'?'"), 63)
        self.assertEqual(self.eval("':'"), 58)

    def test_char_constants_in_expression(self):
        self.assertEqual(self.eval("'A' == 65"), 1)
        self.assertEqual(self.eval("'a' - 'A'"), 32)
        self.assertEqual(self.eval("'<' < 61"), 1)
        # rightmost '<' is inside the literal; the real operator is to the left
        self.assertEqual(self.eval("60 < '<'"), 0)
        self.assertEqual(self.eval("'9' - '0'"), 9)

    def test_malformed_ternary_raises(self):
        with self.assertRaises(ValueError):
            self.eval("1 ? 2")


# ---------------------------------------------------------------------------
# #if expression evaluation through the directive machinery
# ---------------------------------------------------------------------------


class IfExpressionTests(unittest.TestCase):
    def test_ternary_in_if(self):
        self.assertEqual(_run_if("#if 1 ? 1 : 0"), ["TAKEN"])
        self.assertEqual(_run_if("#if 0 ? 1 : 0"), ["NOT_TAKEN"])
        self.assertEqual(_run_if("#if (2 > 1) ? 0 : 1"), ["NOT_TAKEN"])

    def test_character_constant_in_if(self):
        self.assertEqual(_run_if(r"#if '\n' == 10"), ["TAKEN"])
        self.assertEqual(_run_if("#if 'A' == 0x41"), ["TAKEN"])
        self.assertEqual(_run_if("#if 'A' == 66"), ["NOT_TAKEN"])

    def test_integer_suffix_in_if(self):
        self.assertEqual(_run_if("#if 100L == 100"), ["TAKEN"])
        self.assertEqual(_run_if("#if 0xFFUL == 255"), ["TAKEN"])
        self.assertEqual(_run_if("#if (1U << 31) == 2147483648"), ["TAKEN"])

    def test_stdc_version_comparison(self):
        # __STDC_VERSION__ expands to 201112L; exercises suffixed comparison.
        self.assertEqual(_run_if("#if __STDC_VERSION__ >= 201112L"), ["TAKEN"])
        self.assertEqual(_run_if("#if __STDC_VERSION__ < 199901L"), ["NOT_TAKEN"])

    def test_undefined_identifier_is_zero(self):
        # Per C11 6.10.1, undefined identifiers become 0 (not an error).
        self.assertEqual(_run_if("#if SOME_UNDEFINED_CONFIG"), ["NOT_TAKEN"])
        self.assertEqual(_run_if("#if !SOME_UNDEFINED_CONFIG"), ["TAKEN"])
        self.assertEqual(
            _run_if("#if defined(NOPE) && NOPE > 3"), ["NOT_TAKEN"]
        )

    def test_defined_macro_used_in_arithmetic(self):
        src = (
            "#define LEVEL 5\n"
            "#if defined(LEVEL) && LEVEL > 3\nTAKEN\n#else\nNOT_TAKEN\n#endif\n"
        )
        self.assertEqual(preprocess(src, []).split(), ["TAKEN"])


# ---------------------------------------------------------------------------
# __has_attribute / __has_builtin / __has_feature in #if
# ---------------------------------------------------------------------------


class HasFeatureQueryTests(unittest.TestCase):
    def test_has_attribute(self):
        self.assertEqual(_run_if("#if __has_attribute(packed)"), ["TAKEN"])
        self.assertEqual(
            _run_if("#if __has_attribute(no_such_attribute)"), ["NOT_TAKEN"]
        )

    def test_has_builtin(self):
        self.assertEqual(
            _run_if("#if __has_builtin(__builtin_popcount)"), ["TAKEN"]
        )
        self.assertEqual(
            _run_if("#if __has_builtin(__builtin_does_not_exist)"),
            ["NOT_TAKEN"],
        )

    def test_has_feature_unknown_is_zero(self):
        self.assertEqual(
            _run_if("#if __has_feature(some_feature)"), ["NOT_TAKEN"]
        )

    def test_has_attribute_combined_with_logic(self):
        cond = "#if __has_attribute(packed) && __has_builtin(__builtin_clz)"
        self.assertEqual(_run_if(cond), ["TAKEN"])

    def test_has_include_in_if(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "present.h"), "int present;\n")
            src = (
                "#if __has_include(<present.h>)\nTAKEN\n#else\nNOT_TAKEN\n#endif\n"
            )
            out = Preprocessor([tmpdir]).preprocess(src, os.path.join(tmpdir, "m.c"))
            self.assertEqual(out.split(), ["TAKEN"])


# ---------------------------------------------------------------------------
# Hard error replaces the silent "treat as 0" fallback
# ---------------------------------------------------------------------------


class HardErrorTests(unittest.TestCase):
    def test_garbage_expression_raises(self):
        with self.assertRaises(PreprocessorError):
            preprocess("#if 1 +* 2\nx\n#endif\n", [])

    def test_adjacent_numbers_raise(self):
        with self.assertRaises(PreprocessorError):
            preprocess("#if 1 2 3\nx\n#endif\n", [])

    def test_unmatched_ternary_raises(self):
        with self.assertRaises(PreprocessorError):
            preprocess("#if 1 ? 2\nx\n#endif\n", [])

    def test_error_reports_location(self):
        try:
            preprocess("\n\n#if @bogus@\nx\n#endif\n", [])
        except PreprocessorError as exc:
            self.assertEqual(exc.pp_line, 3)
        else:
            self.fail("expected PreprocessorError")

    def test_garbage_inside_inactive_branch_is_not_evaluated(self):
        # An unevaluable expression guarded by a false #if must not error.
        src = "#if 0\n#if 1 +* 2\nx\n#endif\n#endif\nDONE\n"
        self.assertEqual(preprocess(src, []).split(), ["DONE"])


# ---------------------------------------------------------------------------
# _Pragma operator
# ---------------------------------------------------------------------------


class PragmaOperatorTests(unittest.TestCase):
    def test_pragma_operator_is_removed(self):
        out = preprocess('before _Pragma("GCC diagnostic push") after\n', [])
        self.assertNotIn("_Pragma", out)
        self.assertIn("before", out)
        self.assertIn("after", out)

    def test_pragma_operator_via_macro(self):
        src = (
            "#define DO_PRAGMA(x) _Pragma(#x)\n"
            "DO_PRAGMA(message here) tail\n"
        )
        out = preprocess(src, [])
        self.assertNotIn("_Pragma", out)
        self.assertNotIn("message here", out)
        self.assertIn("tail", out)

    def test_pragma_argument_with_comma_and_parens(self):
        # The single string argument may contain commas / parentheses.
        out = preprocess('x _Pragma("a, b (c)") y\n', [])
        self.assertNotIn("_Pragma", out)
        self.assertIn("x", out)
        self.assertIn("y", out)

    def test_pragma_once_operator_skips_second_include(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(
                os.path.join(tmpdir, "guard.h"),
                '_Pragma("once")\nint guarded_symbol;\n',
            )
            _write(
                os.path.join(tmpdir, "main.c"),
                '#include "guard.h"\n#include "guard.h"\n',
            )
            out = Preprocessor([]).preprocess_file(os.path.join(tmpdir, "main.c"))
            self.assertEqual(out.count("int guarded_symbol;"), 1)


# ---------------------------------------------------------------------------
# #line directive
# ---------------------------------------------------------------------------


class LineDirectiveTests(unittest.TestCase):
    def test_line_remaps_line_number(self):
        src = "#line 100\n__LINE__\n__LINE__\n"
        self.assertEqual(preprocess(src, []).split(), ["100", "101"])

    def test_line_remaps_file_and_line(self):
        src = '#line 50 "virtual.c"\n__FILE__ __LINE__\n'
        self.assertEqual(preprocess(src, []).split(), ['"virtual.c"', "50"])

    def test_line_filename_persists_without_new_filename(self):
        src = '#line 10 "a.c"\n__FILE__\n#line 20\n__FILE__ __LINE__\n'
        self.assertEqual(
            preprocess(src, []).split(), ['"a.c"', '"a.c"', "20"]
        )

    def test_line_affects_warning_location(self):
        src = "#line 777\n#warning boom\n"
        try:
            preprocess(src, [], warnings_as_errors=True)
        except PreprocessorError as exc:
            self.assertEqual(exc.pp_line, 777)
        else:
            self.fail("expected PreprocessorError from #warning")

    def test_line_affects_error_location(self):
        src = "#line 500\n#error nope\n"
        try:
            preprocess(src, [])
        except PreprocessorError as exc:
            self.assertEqual(exc.pp_line, 500)
        else:
            self.fail("expected PreprocessorError from #error")

    def test_line_macro_expanded_operands(self):
        src = "#define START 250\n#line START\n__LINE__\n"
        self.assertEqual(preprocess(src, []).split(), ["250"])

    def test_invalid_line_directive_raises(self):
        with self.assertRaises(PreprocessorError):
            preprocess("#line notanumber\n", [])

    def test_line_does_not_leak_across_includes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(
                os.path.join(tmpdir, "inner.h"),
                "#line 9000\nINNER __LINE__\n",
            )
            _write(
                os.path.join(tmpdir, "main.c"),
                '#include "inner.h"\nOUTER __LINE__\n',
            )
            out = Preprocessor([]).preprocess_file(os.path.join(tmpdir, "main.c"))
            tokens = out.split()
            # Inner file's #line applies within the include...
            self.assertIn("INNER", tokens)
            self.assertIn("9000", tokens)
            # ...but the outer file's __LINE__ is its own physical line (2),
            # unaffected by the include's #line directive.
            outer_idx = tokens.index("OUTER")
            self.assertEqual(tokens[outer_idx + 1], "2")


# ---------------------------------------------------------------------------
# Regression: ordinary behaviour still intact
# ---------------------------------------------------------------------------


class RegressionTests(unittest.TestCase):
    def test_plain_file_line_macros(self):
        out = preprocess("__LINE__\n__LINE__\n", [], )
        self.assertEqual(out.split(), ["1", "2"])

    def test_existing_boolean_if_logic(self):
        self.assertEqual(_run_if("#if 1 && (2 || 0)"), ["TAKEN"])
        self.assertEqual(_run_if("#if !0 && ~0"), ["TAKEN"])

    def test_unsupported_if_no_longer_silently_warns(self):
        # The old behaviour printed a warning to stderr and treated as 0.
        # The new behaviour raises; make sure nothing is printed to stderr
        # for a *valid* expression.
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.assertEqual(_run_if("#if 2 + 2 == 4"), ["TAKEN"])
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
