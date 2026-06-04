import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.PyStackVM import BC_RET
from IsaacCompiler.code_gen.stackvm_binutils.object_file import (
    ObjectSegment,
    RelocationType,
    SectionFlags,
    SymbolBinding,
    SymbolType,
    load_sbo,
)


def _compile_command(source_path, output_path=None, extra_args=None):
    extra_args = [] if extra_args is None else list(extra_args)
    cmd = [
        sys.executable,
        "-m",
        "IsaacCompiler",
        "compile",
        "-c",
    ]
    if output_path is not None:
        cmd.extend(["-o", output_path])
    cmd.extend(extra_args)
    cmd.append(source_path)
    return cmd


def _compile_object(source, extra_args=None, filename="unit.c"):
    with tempfile.TemporaryDirectory() as tmpdir:
        source_path = os.path.join(tmpdir, filename)
        output_path = os.path.join(tmpdir, "unit.sbo")
        with open(source_path, "w") as fl:
            fl.write(source)
        proc = subprocess.run(
            _compile_command(source_path, output_path, extra_args),
            cwd=REPO_PARENT,
            capture_output=True,
            text=True,
        )
        obj = load_sbo(output_path) if proc.returncode == 0 else None
        return proc, obj


def _symbols_by_name(obj):
    return {symbol.name: symbol for symbol in obj.symbols}


class SeparateCompilationTests(unittest.TestCase):
    def test_compile_only_defaults_output_path_and_allows_unresolved_symbols(self):
        source = "extern int external(void); int f(void) { return external(); }\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.c")
            with open(source_path, "w") as fl:
                fl.write(source)
            proc = subprocess.run(
                _compile_command("source.c"),
                cwd=tmpdir,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": REPO_PARENT},
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            output_path = os.path.join(tmpdir, "source.sbo")
            self.assertTrue(os.path.isfile(output_path))
            symbols = _symbols_by_name(load_sbo(output_path))
            self.assertTrue(symbols["external"].is_undefined)
            self.assertNotIn("main", symbols)

            override_path = os.path.join(tmpdir, "custom.sbo")
            override_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "IsaacCompiler",
                    "compile",
                    "-c",
                    "source.c",
                    "-o",
                    override_path,
                ],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": REPO_PARENT},
            )
            self.assertEqual(
                override_proc.returncode,
                0,
                msg=override_proc.stderr or override_proc.stdout,
            )
            self.assertTrue(os.path.isfile(override_path))

        proc, obj = _compile_object(source)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertIsNotNone(obj)
        self.assertEqual(obj.default_alignment, 0)

    def test_compile_only_rejects_run_and_disassembly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.c")
            with open(source_path, "w") as fl:
                fl.write("int f(void) { return 0; }\n")

            run_proc = subprocess.run(
                _compile_command(source_path, extra_args=["--run"]),
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(run_proc.returncode, 0)
            self.assertIn("cannot be combined with --run", run_proc.stderr)

            disasm_proc = subprocess.run(
                _compile_command(
                    source_path,
                    extra_args=["-d", os.path.join(tmpdir, "out.sasm"), "ia", "is"],
                ),
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(disasm_proc.returncode, 0)
            self.assertIn("cannot be combined with disassembly", disasm_proc.stderr)

    def test_external_names_are_raw_by_default_and_mangled_on_request(self):
        source = (
            "extern int ext; "
            "int global; "
            "int function(void) { return ext + global; }\n"
        )
        proc, raw_obj = _compile_object(source)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        raw_names = set(_symbols_by_name(raw_obj))
        self.assertTrue({"ext", "global", "function"} <= raw_names)

        proc, explicit_raw_obj = _compile_object(source, ["--no-mangle"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertEqual(
            set(_symbols_by_name(explicit_raw_obj)),
            raw_names,
        )

        proc, mangled_obj = _compile_object(source, ["--mangle"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        mangled_names = set(_symbols_by_name(mangled_obj))
        self.assertTrue({"?iext", "?iglobal", "?Fzfunction"} <= mangled_names)
        self.assertFalse({"ext", "global", "function"} & mangled_names)

    def test_bindings_definitions_and_unreferenced_externs(self):
        source = (
            "extern int unused; "
            "extern int unused_fn(void); "
            "extern int used; "
            "int global; "
            "static int hidden; "
            "int f(void) { static int local; return used + global + hidden + local; }\n"
        )
        proc, obj = _compile_object(source)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        symbols = _symbols_by_name(obj)

        self.assertNotIn("unused", symbols)
        self.assertNotIn("unused_fn", symbols)
        self.assertEqual(symbols["global"].binding, SymbolBinding.GLOBAL)
        self.assertEqual(symbols["f"].binding, SymbolBinding.GLOBAL)
        self.assertEqual(symbols["used"].binding, SymbolBinding.GLOBAL)
        self.assertTrue(symbols["used"].is_undefined)

        local_objects = [
            symbol
            for symbol in obj.symbols
            if symbol.binding == SymbolBinding.LOCAL
            and symbol.typ == SymbolType.OBJECT
        ]
        self.assertEqual(len(local_objects), 2)
        self.assertTrue(all(not symbol.is_undefined for symbol in local_objects))
        self.assertTrue(all(symbol.binding != SymbolBinding.WEAK for symbol in obj.symbols))

    def test_relocations_alignment_and_string_symbols(self):
        source = (
            "extern int ext; "
            "extern int ef(void); "
            "int __attribute__((aligned(16))) aligned; "
            "int g; "
            "int f(void) { return ef() + ext + g; } "
            "int *pg = &g; "
            "int (*pf)(void) = &ef; "
            'char *ps = "x";\n'
        )
        proc, obj = _compile_object(source, ["--default-alignment", "8"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        symbols = _symbols_by_name(obj)
        target_names = {
            index: symbol.name for index, symbol in enumerate(obj.symbols)
        }

        self.assertEqual(obj.default_alignment, 8)
        self.assertEqual(obj.data_alignment, 16)
        self.assertEqual(symbols["aligned"].value % 16, 0)
        for name in ("g", "pg", "pf", "ps"):
            self.assertEqual(symbols[name].value % symbols[name].size, 0)
        self.assertGreater(len(obj.code), 0)
        self.assertGreater(len(obj.data), 0)

        code_targets = {
            target_names[reloc.symbol_index]
            for reloc in obj.relocations
            if reloc.segment == ObjectSegment.CODE
        }
        data_targets = {
            target_names[reloc.symbol_index]
            for reloc in obj.relocations
            if reloc.segment == ObjectSegment.DATA
        }
        self.assertEqual(code_targets, {"ef", "ext", "g"})
        self.assertEqual(data_targets, {"ef", "g", ".L.str.0"})
        self.assertTrue(
            all(
                reloc.typ == RelocationType.PCREL8
                for reloc in obj.relocations
                if reloc.segment == ObjectSegment.CODE
            )
        )
        self.assertTrue(
            all(
                reloc.typ == RelocationType.ABS8
                for reloc in obj.relocations
                if reloc.segment == ObjectSegment.DATA
            )
        )
        for reloc in obj.relocations:
            segment = obj.code if reloc.segment == ObjectSegment.CODE else obj.data
            self.assertLessEqual(reloc.offset + 8, len(segment))
            self.assertEqual(
                int.from_bytes(
                    segment[reloc.offset : reloc.offset + 8],
                    "little",
                    signed=True,
                ),
                0,
            )

    def test_compiler_emits_named_rodata_and_nobits_sections(self):
        source = (
            'void __attribute__((section(".init.text"))) init(void) {} '
            'int __attribute__((section(".data.cacheline_aligned"), aligned(16))) '
            "cache = 7; "
            "const int read_only = 3; "
            "int zeroes[32];\n"
        )
        proc, obj = _compile_object(source)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        symbols = _symbols_by_name(obj)
        symbol_sections = {
            name: obj.sections[symbols[name].section_index].name
            for name in ("init", "cache", "read_only", "zeroes")
        }

        self.assertEqual(symbol_sections["init"], ".init.text")
        self.assertEqual(symbol_sections["cache"], ".data.cacheline_aligned")
        self.assertEqual(symbol_sections["read_only"], ".rodata")
        self.assertEqual(symbol_sections["zeroes"], ".bss")
        bss = next(section for section in obj.sections if section.name == ".bss")
        self.assertEqual(bss.flags & SectionFlags.NOBITS, SectionFlags.NOBITS)
        self.assertEqual(bss.size, symbols["zeroes"].size)
        self.assertGreaterEqual(bss.offset, len(obj.data))
        self.assertEqual(symbols["cache"].value % 16, 0)

    def test_runtime_helpers_remain_undefined(self):
        source = (
            "int f(void) { "
            "    char bytes[4]; "
            "    __builtin_memset(bytes, 3, 4); "
            "    return 0; "
            "}\n"
        )
        proc, obj = _compile_object(source)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        symbols = _symbols_by_name(obj)
        self.assertTrue(symbols["memset"].is_undefined)
        self.assertEqual(symbols["memset"].segment, ObjectSegment.CODE)
        self.assertFalse(
            any(symbol.name == "memset" and not symbol.is_undefined for symbol in obj.symbols)
        )

    def test_extern_then_definition_and_block_scope_extern_merge(self):
        source = (
            "extern int x; "
            "int f(void) { extern int x; return x; } "
            "int x;\n"
        )
        proc, obj = _compile_object(source)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        symbols = [symbol for symbol in obj.symbols if symbol.name == "x"]
        self.assertEqual(len(symbols), 1)
        self.assertFalse(symbols[0].is_undefined)
        self.assertEqual(symbols[0].binding, SymbolBinding.GLOBAL)

        conflict = "extern int x; int f(void) { extern char x; return 0; }\n"
        proc, _obj = _compile_object(conflict)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Conflicting declarations", proc.stderr)

        linkage_conflict = "extern int x; static int x;\n"
        proc, _obj = _compile_object(linkage_conflict)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Conflicting linkage", proc.stderr)

    def test_global_initializer_is_local_and_finalized_for_the_future_linker(self):
        source = "int make(void) { return 2; } int g = make();\n"
        proc, obj = _compile_object(source)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        symbols = _symbols_by_name(obj)
        init_symbol = symbols["?Fz__init_globals"]
        self.assertEqual(init_symbol.binding, SymbolBinding.LOCAL)
        self.assertEqual(init_symbol.segment, ObjectSegment.CODE)
        self.assertEqual(obj.code[init_symbol.value + init_symbol.size - 1], BC_RET)
        self.assertTrue(
            any(
                obj.symbols[reloc.symbol_index].name == "make"
                for reloc in obj.relocations
            )
        )

    def test_unmangled_overloads_and_namespaces_require_mangling(self):
        compatible = "int f(int); int f(int x) { return 0; }\n"
        proc, obj = _compile_object(compatible)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertEqual(
            [symbol.name for symbol in obj.symbols if symbol.name == "f"],
            ["f"],
        )

        overload = (
            "int f(int x) { return 0; } "
            "int f(char x) { return 0; }\n"
        )
        proc, _obj = _compile_object(overload, filename="overload.cpp")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--mangle", proc.stderr)

        proc, obj = _compile_object(
            overload,
            ["--mangle"],
            filename="overload.cpp",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertEqual(
            {symbol.name for symbol in obj.symbols},
            {"?Fczf", "?Fizf"},
        )

        namespace = "namespace n { int f(void) { return 0; } }\n"
        proc, _obj = _compile_object(namespace, filename="namespace.cpp")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--mangle", proc.stderr)

        proc, obj = _compile_object(
            namespace,
            ["--mangle"],
            filename="namespace.cpp",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertIn("@n?Fzf", _symbols_by_name(obj))


if __name__ == "__main__":
    unittest.main()
