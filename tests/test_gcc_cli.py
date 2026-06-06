"""Tests for the GCC-compatible command-line front end (COMPAT-H1).

These exercise the driver end-to-end through ``python -m IsaacCompiler`` so the
implicit/explicit dispatch, argument parsing and the mapping onto the
compile/link machinery are all covered the way a build system would hit them.
"""

import os
import struct
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))  # .../IsaacCompiler
REPO_PARENT = os.path.dirname(REPO_ROOT)  # parent that holds the package
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.code_gen.stackvm_binutils.object_file import load_sbo

_SVC_MAGIC = b"\xf7SVE\0\0\0\0"

# A trivial, runtime-free translation unit with a definition of main.
_MAIN_RET0 = "int main(int argc, char **argv) { return 0; }\n"


def _run(args, cwd=None):
    """Invoke ``python -m IsaacCompiler <args>`` and capture the result."""
    proc = subprocess.run(
        [sys.executable, "-m", "IsaacCompiler"] + list(args),
        cwd=REPO_PARENT if cwd is None else cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": REPO_PARENT},
    )
    return proc


def _msg(proc):
    return proc.stderr or proc.stdout


def _read_sbc_header(path):
    with open(path, "rb") as fl:
        magic = fl.read(8)
        code_end, data_start, total = struct.unpack("<QQQ", fl.read(24))
    return magic, code_end, data_start, total


class GccCliCompileTests(unittest.TestCase):
    def test_compile_only_implicit_mode_produces_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "unit.c")
            obj = os.path.join(tmp, "unit.sbo")
            with open(src, "w") as fl:
                fl.write(
                    "int counter = 5;\n"
                    "int helper(int x) { return x + counter; }\n"
                    "int main(int argc, char **argv) { return helper(argc); }\n"
                )
            # No subcommand: first token is a flag -> implicit gcc mode.
            proc = _run(["-c", src, "-o", obj])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertTrue(os.path.isfile(obj))
            names = {sym.name for sym in load_sbo(obj).symbols}
            self.assertIn("main", names)
            self.assertIn("helper", names)
            self.assertIn("counter", names)

    def test_compile_only_defaults_output_name_in_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "thing.c"), "w") as fl:
                fl.write(_MAIN_RET0)
            proc = _run(["-c", "thing.c"], cwd=tmp)
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "thing.sbo")))

    def test_explicit_gcc_and_cc_subcommands(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            with open(src, "w") as fl:
                fl.write(_MAIN_RET0)
            for front in ("gcc", "cc"):
                obj = os.path.join(tmp, front + ".sbo")
                proc = _run([front, "-c", src, "-o", obj])
                self.assertEqual(proc.returncode, 0, msg=_msg(proc))
                self.assertTrue(os.path.isfile(obj))

    def test_native_compile_subcommand_is_not_hijacked(self):
        # A leading native subcommand must still reach the original CLI.
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            out = os.path.join(tmp, "u.sbc")
            with open(src, "w") as fl:
                fl.write(_MAIN_RET0)
            proc = _run(["compile", "-o", out, src])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertTrue(os.path.isfile(out))

    def test_attached_and_separated_flag_forms_are_equivalent(self):
        src_text = (
            "_Static_assert(SCALE == 4, \"SCALE must be 4\");\n" + _MAIN_RET0
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            with open(src, "w") as fl:
                fl.write(src_text)
            attached = _run(["-c", "-DSCALE=4", "-o", os.path.join(tmp, "a.sbo"), src])
            separated = _run(["-c", "-D", "SCALE=4", "-o", os.path.join(tmp, "b.sbo"), src])
            self.assertEqual(attached.returncode, 0, msg=_msg(attached))
            self.assertEqual(separated.returncode, 0, msg=_msg(separated))


class GccCliPreprocessorTests(unittest.TestCase):
    def _compile_guarded(self, body, extra_args, tmp):
        src = os.path.join(tmp, "g.c")
        obj = os.path.join(tmp, "g.sbo")
        with open(src, "w") as fl:
            fl.write(body + _MAIN_RET0)
        return _run(["-c"] + list(extra_args) + ["-o", obj, src])

    def test_define_value_reaches_preprocessor(self):
        body = "_Static_assert(WIDGETS == 3, \"bad WIDGETS\");\n"
        with tempfile.TemporaryDirectory() as tmp:
            ok = self._compile_guarded(body, ["-DWIDGETS=3"], tmp)
            self.assertEqual(ok.returncode, 0, msg=_msg(ok))
            bad = self._compile_guarded(body, ["-DWIDGETS=4"], tmp)
            self.assertNotEqual(bad.returncode, 0)

    def test_define_without_value_defaults_to_one(self):
        body = (
            "#ifndef FLAG\n#error FLAG missing\n#endif\n"
            "#if FLAG != 1\n#error FLAG should be 1\n#endif\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._compile_guarded(body, ["-DFLAG"], tmp)
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))

    def test_undefine_removes_user_macro(self):
        body = "#ifdef FLAG\n#error FLAG still defined\n#endif\n"
        with tempfile.TemporaryDirectory() as tmp:
            # -D then -U in order -> finally undefined.
            proc = self._compile_guarded(body, ["-DFLAG=1", "-UFLAG"], tmp)
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))

    def test_undefine_suppresses_predefined_macro(self):
        body = "#ifdef __STDC_HOSTED__\n#error hosted still defined\n#endif\n"
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._compile_guarded(body, ["-U__STDC_HOSTED__"], tmp)
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))

    def test_include_dir_search_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            incdir = os.path.join(tmp, "inc")
            os.mkdir(incdir)
            with open(os.path.join(incdir, "widget.h"), "w") as fl:
                fl.write("#define WIDGET_OK 1\n")
            body = (
                "#include <widget.h>\n"
                "#if WIDGET_OK != 1\n#error widget header not used\n#endif\n"
            )
            with_inc = self._compile_guarded(body, ["-I", incdir], tmp)
            self.assertEqual(with_inc.returncode, 0, msg=_msg(with_inc))
            without_inc = self._compile_guarded(body, [], tmp)
            self.assertNotEqual(without_inc.returncode, 0)

    def test_nostdinc_drops_bundled_headers(self):
        body = "#include <stdbool.h>\n"
        with tempfile.TemporaryDirectory() as tmp:
            with_std = self._compile_guarded(body, [], tmp)
            self.assertEqual(with_std.returncode, 0, msg=_msg(with_std))
            without_std = self._compile_guarded(body, ["-nostdinc"], tmp)
            self.assertNotEqual(without_std.returncode, 0)

    def test_std_sets_stdc_version_macro(self):
        with tempfile.TemporaryDirectory() as tmp:
            c99 = self._compile_guarded(
                "#if __STDC_VERSION__ != 199901L\n#error not c99\n#endif\n",
                ["-std=c99"],
                tmp,
            )
            self.assertEqual(c99.returncode, 0, msg=_msg(c99))
            c11 = self._compile_guarded(
                "#if __STDC_VERSION__ != 201112L\n#error not c11\n#endif\n",
                ["-std=c11"],
                tmp,
            )
            self.assertEqual(c11.returncode, 0, msg=_msg(c11))

    def test_werror_promotes_preprocessor_warning(self):
        body = "#warning this is deprecated\n"
        with tempfile.TemporaryDirectory() as tmp:
            tolerated = self._compile_guarded(body, [], tmp)
            self.assertEqual(tolerated.returncode, 0, msg=_msg(tolerated))
            fatal = self._compile_guarded(body, ["-Werror"], tmp)
            self.assertNotEqual(fatal.returncode, 0)


class GccCliFlagAcceptanceTests(unittest.TestCase):
    def test_optimisation_and_warning_and_misc_flags_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            obj = os.path.join(tmp, "u.sbo")
            with open(src, "w") as fl:
                fl.write(_MAIN_RET0)
            proc = _run(
                [
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-g",
                    "-std=c11",
                    "-fno-stack-protector",
                    "-fomit-frame-pointer",
                    "-static",
                    "-c",
                    src,
                    "-o",
                    obj,
                ]
            )
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertTrue(os.path.isfile(obj))

    def test_fno_builtin_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            obj = os.path.join(tmp, "u.sbo")
            with open(src, "w") as fl:
                fl.write(_MAIN_RET0)
            proc = _run(["-fno-builtin", "-c", src, "-o", obj])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))

    def test_unrecognised_option_warns_but_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            obj = os.path.join(tmp, "u.sbo")
            with open(src, "w") as fl:
                fl.write(_MAIN_RET0)
            proc = _run(["-fparticularly-novel-flag", "-mcmodel=kernel", "-c", src, "-o", obj])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))

    def test_march_stackvm_accepted_other_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            obj = os.path.join(tmp, "u.sbo")
            with open(src, "w") as fl:
                fl.write(_MAIN_RET0)
            ok = _run(["-march=stackvm", "-c", src, "-o", obj])
            self.assertEqual(ok.returncode, 0, msg=_msg(ok))
            bad = _run(["-march=x86_64", "-c", src, "-o", obj])
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("stackvm", bad.stderr)

    def test_no_input_files_is_an_error(self):
        proc = _run(["-c"])  # gcc mode, but nothing to compile
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no input files", proc.stderr)

    def test_dash_o_with_c_and_multiple_sources_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.c")
            b = os.path.join(tmp, "b.c")
            for path in (a, b):
                with open(path, "w") as fl:
                    fl.write(_MAIN_RET0)
            proc = _run(["-c", a, b, "-o", os.path.join(tmp, "out.sbo")])
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("multiple source", proc.stderr)


class GccCliLinkTests(unittest.TestCase):
    def test_single_source_links_and_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "prog.c")
            out = os.path.join(tmp, "prog.sbc")
            with open(src, "w") as fl:
                fl.write(
                    "int total = 0;\n"
                    "int main(int argc, char **argv) {\n"
                    "    for (int i = 0; i < 5; i = i + 1) { total = total + i; }\n"
                    "    return 0;\n"
                    "}\n"
                )
            proc = _run([src, "-o", out])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            magic, code_end, data_start, total = _read_sbc_header(out)
            self.assertEqual(magic, _SVC_MAGIC)
            self.assertLessEqual(code_end, data_start)
            self.assertLessEqual(data_start, total)
            # The produced image should actually run to completion.
            run_proc = _run(["run", out])
            self.assertEqual(run_proc.returncode, 0, msg=_msg(run_proc))

    def test_single_source_without_main_reports_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "nomain.c")
            with open(src, "w") as fl:
                fl.write("int helper(int x) { return x + 1; }\n")
            proc = _run([src, "-o", os.path.join(tmp, "out.sbc")])
            self.assertNotEqual(proc.returncode, 0)
            # No raw Python traceback should leak to the user.
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("main", proc.stderr)

    def _compile_object(self, tmp, name, source):
        src = os.path.join(tmp, name + ".c")
        obj = os.path.join(tmp, name + ".sbo")
        with open(src, "w") as fl:
            fl.write(source)
        proc = _run(["-c", src, "-o", obj])
        self.assertEqual(proc.returncode, 0, msg=_msg(proc))
        return obj

    def test_multiple_objects_resolve_cross_unit_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib_obj = self._compile_object(
                tmp, "lib", "int square(int x) { return x * x; }\n"
            )
            main_obj = self._compile_object(
                tmp,
                "main",
                "extern int square(int);\n"
                "int main(int argc, char **argv) { return square(argc); }\n",
            )
            out = os.path.join(tmp, "out.sbc")
            # main alone leaves 'square' unresolved -> link error.
            alone = _run([main_obj, "-o", out])
            self.assertNotEqual(alone.returncode, 0)
            # together they link cleanly.
            both = _run([main_obj, lib_obj, "-o", out])
            self.assertEqual(both.returncode, 0, msg=_msg(both))
            magic, _, _, _ = _read_sbc_header(out)
            self.assertEqual(magic, _SVC_MAGIC)

    def test_library_resolution_via_l_and_L(self):
        with tempfile.TemporaryDirectory() as tmp:
            sq_obj = self._compile_object(
                tmp, "square", "int square(int x) { return x * x; }\n"
            )
            libdir = os.path.join(tmp, "libs")
            os.mkdir(libdir)
            os.rename(sq_obj, os.path.join(libdir, "libsquare.sbo"))
            main_obj = self._compile_object(
                tmp,
                "main",
                "extern int square(int);\n"
                "int main(int argc, char **argv) { return square(argc); }\n",
            )
            out = os.path.join(tmp, "out.sbc")
            ok = _run([main_obj, "-lsquare", "-L", libdir, "-o", out])
            self.assertEqual(ok.returncode, 0, msg=_msg(ok))
            self.assertTrue(os.path.isfile(out))
            missing = _run([main_obj, "-lsquare", "-o", out])
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("lsquare", missing.stderr)

    def test_linker_script_via_T(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj = self._compile_object(
                tmp,
                "kern",
                "int value = 7;\n"
                "int main(int argc, char **argv) { return value; }\n",
            )
            script = os.path.join(tmp, "link.ld")
            with open(script, "w") as fl:
                fl.write(
                    "SECTIONS { "
                    ".text : { *(.text) } "
                    ".init.text : { *(.init.text) } "
                    ".init_array : { *(.init_array) } "
                    ".fini_array : { *(.fini_array) } "
                    ".rodata : { *(.rodata) } "
                    ".data : { *(.data) } "
                    ".bss : { *(.bss) } "
                    "}\n"
                )
            out = os.path.join(tmp, "out.sbc")
            proc = _run([obj, "-T", script, "-o", out])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            magic, _, _, _ = _read_sbc_header(out)
            self.assertEqual(magic, _SVC_MAGIC)

    def test_shared_allows_undefined_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj = self._compile_object(
                tmp,
                "ref",
                "extern int helper(void);\n"
                "int wrapper(void) { return helper(); }\n",
            )
            out = os.path.join(tmp, "out.sbc")
            # Executable link cannot leave 'helper' unresolved.
            exe = _run([obj, "-o", out])
            self.assertNotEqual(exe.returncode, 0)
            # -shared permits the dangling reference.
            shared = _run(["-shared", obj, "-o", out])
            self.assertEqual(shared.returncode, 0, msg=_msg(shared))
            self.assertTrue(os.path.isfile(out))


class GccCliPreprocessOnlyTests(unittest.TestCase):
    def test_preprocess_to_stdout_expands_macros(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            with open(src, "w") as fl:
                fl.write(
                    "#define DOUBLE(x) ((x) + (x))\n"
                    "#ifdef ENABLE\nint enabled = 1;\n#endif\n"
                    "int v = DOUBLE(VAL);\n"
                )
            proc = _run(["-E", "-DVAL=21", "-DENABLE", src])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertIn("int v = ((21) + (21));", proc.stdout)
            self.assertIn("int enabled = 1;", proc.stdout)

    def test_preprocess_only_is_quiet_on_stderr(self):
        # -E must not compile the runtime; a build system capturing stderr for
        # dependency scanning should see nothing.
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            with open(src, "w") as fl:
                fl.write("int v = 1;\n")
            proc = _run(["-E", src])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertEqual(proc.stderr, "")

    def test_preprocess_to_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            out = os.path.join(tmp, "u.i")
            with open(src, "w") as fl:
                fl.write("#define N 7\nint v = N;\n")
            proc = _run(["-E", src, "-o", out])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            with open(out) as fl:
                self.assertIn("int v = 7;", fl.read())

    def test_preprocess_honours_werror(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.c")
            with open(src, "w") as fl:
                fl.write("#warning nope\nint v = 1;\n")
            tolerated = _run(["-E", src])
            self.assertEqual(tolerated.returncode, 0, msg=_msg(tolerated))
            fatal = _run(["-E", "-Werror", src])
            self.assertNotEqual(fatal.returncode, 0)

    def test_preprocess_o_with_multiple_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.c")
            b = os.path.join(tmp, "b.c")
            for path in (a, b):
                with open(path, "w") as fl:
                    fl.write("int v = 1;\n")
            proc = _run(["-E", a, b, "-o", os.path.join(tmp, "out.i")])
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("multiple input", proc.stderr)


class GccDriverUnitTests(unittest.TestCase):
    """Fast, in-process checks of the driver's pure argument helpers."""

    def setUp(self):
        from IsaacCompiler import gcc_driver

        self.gd = gcc_driver

    def test_normalize_rewrites_bare_O_to_O1(self):
        self.assertEqual(
            self.gd.normalize_gcc_args(["-O", "-O2", "foo.c"]),
            ["-O1", "-O2", "foo.c"],
        )

    def test_classify_inputs_splits_sources_and_link_inputs(self):
        sources, asm_sources, link_inputs = self.gd.classify_inputs(
            ["a.c", "b.cpp", "boot.S", "ctx.s", "c.sbo", "d.sba", "weird.xyz"]
        )
        self.assertEqual(sources, ["a.c", "b.cpp"])
        self.assertEqual(asm_sources, ["boot.S", "ctx.s"])
        self.assertEqual(link_inputs, ["c.sbo", "d.sba", "weird.xyz"])

    def test_resolve_macros_respects_command_order(self):
        # -D then -U -> undefined; the reverse -> defined.
        defines, undef = self.gd.resolve_macros([("D", "FOO=1"), ("U", "FOO")], None)
        self.assertNotIn("FOO", defines)
        self.assertIn("FOO", undef)

        defines, undef = self.gd.resolve_macros([("U", "FOO"), ("D", "FOO=2")], None)
        self.assertIn("FOO", defines)
        self.assertEqual(defines["FOO"].replacement, "2")
        self.assertNotIn("FOO", undef)

    def test_resolve_macros_default_value_is_one(self):
        defines, _ = self.gd.resolve_macros([("D", "BARE")], None)
        self.assertEqual(defines["BARE"].replacement, "1")

    def test_resolve_macros_function_like_define(self):
        defines, _ = self.gd.resolve_macros([("D", "MAX(a,b)=((a)>(b)?(a):(b))")], None)
        macro = defines["MAX"]
        self.assertEqual(macro.params, ["a", "b"])
        self.assertEqual(macro.replacement, "((a)>(b)?(a):(b))")

    def test_resolve_macros_std_controls_stdc_version(self):
        defines, undef = self.gd.resolve_macros([], "c99")
        self.assertEqual(defines["__STDC_VERSION__"].replacement, "199901L")
        defines, undef = self.gd.resolve_macros([], "c89")
        self.assertIn("__STDC_VERSION__", undef)
        self.assertNotIn("__STDC_VERSION__", defines)

    def test_resolve_macros_rejects_unknown_std(self):
        with self.assertRaises(self.gd.GccDriverError):
            self.gd.resolve_macros([], "c42")

    def test_interpret_warnings(self):
        opts = self.gd.interpret_warnings(["all", "extra", "error"])
        self.assertTrue(opts.warnings_as_errors)
        opts = self.gd.interpret_warnings(["all"])
        self.assertFalse(opts.warnings_as_errors)
        # -Wl,/-Wp,/-Wa, are pass-through and never imply -Werror semantics.
        opts = self.gd.interpret_warnings(["l,-z,now", "p,-MD"])
        self.assertFalse(opts.warnings_as_errors)

    def test_interpret_fflags(self):
        flags = self.gd.interpret_fflags(["no-builtin", "no-stack-protector", "PIC"])
        self.assertFalse(flags["builtin"])
        self.assertFalse(flags["stack_protector"])

    def test_resolve_library_missing_raises(self):
        with self.assertRaises(self.gd.GccDriverError):
            self.gd.resolve_library("definitely_absent_lib", [], prefer_static=False)


class GccCliPrintFileNameTests(unittest.TestCase):
    def test_print_file_name_unknown_echoes_name(self):
        proc = _run(["-print-file-name=libc.a"])
        self.assertEqual(proc.returncode, 0, msg=_msg(proc))
        self.assertIn("libc.a", proc.stdout)

    def test_print_file_name_resolves_in_L_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "libfoo.sbo")
            with open(lib, "wb") as fl:
                fl.write(b"\0\0\0\0")
            proc = _run(["-L", tmp, "-print-file-name=libfoo.sbo"])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertIn(os.path.abspath(lib), proc.stdout)


if __name__ == "__main__":
    unittest.main()
