import os
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import Preprocessor


def _write(path, text):
    with open(path, "w", encoding="utf-8") as file_obj:
        file_obj.write(text)


class HasIncludeTests(unittest.TestCase):
    def test_quoted_has_include_searches_relative_to_source_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "src")
            include_dir = os.path.join(tmpdir, "include")
            os.makedirs(src_dir)
            os.makedirs(include_dir)

            _write(os.path.join(src_dir, "local_header.h"), "int local_value;\n")
            _write(
                os.path.join(src_dir, "main.c"),
                textwrap.dedent(
                    """\
                    #if __has_include("local_header.h")
                    #include "local_header.h"
                    #else
                    int missing_local_header;
                    #endif
                    """
                ),
            )

            source_path = os.path.join(src_dir, "main.c")
            output = Preprocessor([include_dir]).preprocess_file(source_path)

            self.assertIn("int local_value;", output)
            self.assertNotIn("int missing_local_header;", output)

    def test_angled_has_include_searches_configured_include_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "src")
            include_dir = os.path.join(tmpdir, "include")
            os.makedirs(src_dir)
            os.makedirs(include_dir)

            _write(os.path.join(include_dir, "system_header.h"), "int system_value;\n")
            _write(
                os.path.join(src_dir, "main.c"),
                textwrap.dedent(
                    """\
                    #if __has_include(<system_header.h>)
                    #include <system_header.h>
                    #else
                    int missing_system_header;
                    #endif
                    """
                ),
            )

            source_path = os.path.join(src_dir, "main.c")
            output = Preprocessor([include_dir]).preprocess_file(source_path)

            self.assertIn("int system_value;", output)
            self.assertNotIn("int missing_system_header;", output)

    def test_missing_has_include_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "src")
            os.makedirs(src_dir)

            _write(
                os.path.join(src_dir, "main.c"),
                textwrap.dedent(
                    """\
                    #if __has_include("missing_header.h")
                    int unexpected_branch;
                    #else
                    int expected_branch;
                    #endif
                    """
                ),
            )

            source_path = os.path.join(src_dir, "main.c")
            output = Preprocessor([]).preprocess_file(source_path)

            self.assertIn("int expected_branch;", output)
            self.assertNotIn("int unexpected_branch;", output)

    def test_macro_expanding_to_has_include_is_evaluated_in_if(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "src")
            os.makedirs(src_dir)

            _write(os.path.join(src_dir, "local_header.h"), "int local_value;\n")
            _write(
                os.path.join(src_dir, "main.c"),
                textwrap.dedent(
                    """\
                    #define CHECK_LOCAL __has_include("local_header.h")
                    #if CHECK_LOCAL
                    int has_local_header;
                    #else
                    int missing_local_header;
                    #endif
                    """
                ),
            )

            source_path = os.path.join(src_dir, "main.c")
            output = Preprocessor([]).preprocess_file(source_path)

            self.assertIn("int has_local_header;", output)
            self.assertNotIn("int missing_local_header;", output)


if __name__ == "__main__":
    unittest.main()
