import os
import struct
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)

_SVC_MAGIC = b"\xf7SVE\0\0\0\0"


def _run_compile(source: str, extra_args=None):
    extra_args = [] if extra_args is None else list(extra_args)
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "main.c")
        out_path = os.path.join(tmpdir, "out.sbc")
        with open(src_path, "w") as src_file:
            src_file.write(source)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "IsaacCompiler",
                "compile",
                "-o",
                out_path,
            ]
            + extra_args
            + [src_path],
            cwd=REPO_PARENT,
            capture_output=True,
            text=True,
        )
        header = None
        if proc.returncode == 0:
            with open(out_path, "rb") as out_file:
                magic = out_file.read(8)
                header = (magic, struct.unpack("<QQQ", out_file.read(24)))
        return proc, header


class CliAlignmentTests(unittest.TestCase):
    def test_default_alignment_flag_enables_c11_style_member_padding(self):
        proc, _header = _run_compile(
            "struct S { unsigned char a; unsigned int b; }; "
            "_Static_assert(sizeof(struct S) == 8, \"expected padded layout\"); "
            "int main(int argc, char **argv) { return 0; }\n",
            ["--default-alignment", "8"],
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

    def test_omitting_default_alignment_keeps_struct_fields_adjacent(self):
        proc, _header = _run_compile(
            "struct S { unsigned char a; unsigned int b; }; "
            "_Static_assert(sizeof(struct S) == 5, \"expected flat layout\"); "
            "int main(int argc, char **argv) { return 0; }\n",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

    def test_data_seg_align_still_controls_only_data_segment_start(self):
        proc, header = _run_compile(
            "int g = 1; int main(int argc, char **argv) { return g; }\n",
            ["--data-seg-align", "4096"],
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        assert header is not None
        magic, (code_end, data_start, total_len) = header
        self.assertEqual(magic, _SVC_MAGIC)
        self.assertEqual(data_start % 4096, 0)
        self.assertGreaterEqual(data_start, code_end)
        self.assertGreater(total_len, data_start)


if __name__ == "__main__":
    unittest.main()
