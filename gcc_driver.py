"""GCC-compatible command-line front end for IsaacCompiler (COMPAT-H1).

Build systems (Kconfig, CMake, Meson, autoconf) drive a compiler as if it were
GCC: ``cc -c -o foo.o foo.c -I/inc -DNAME=1``.  This module accepts that flag
vocabulary and maps it onto the existing StackVM compile/link machinery so the
package can act as a drop-in ``gcc`` replacement.

It is reached either explicitly::

    python -m IsaacCompiler gcc -c foo.c -o foo.sbo

or implicitly, whenever the first argument is not one of the native
subcommands (``compile`` / ``link`` / ``addr2line`` / ``run``)::

    python -m IsaacCompiler -c foo.c -o foo.sbo

The single entry point is :func:`run_gcc_driver`, which returns a process exit
code.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

from .Preprocessing import MacroDef, PreprocessorError, preprocess
from .code_gen.NameMangling import NameManglingMode
from .code_gen.stackvm_binutils.linker import (
    LinkerError,
    link_files,
    load_linker_script,
)
from .code_gen.stackvm_binutils.elf_file import write_elf_object
from .code_gen.stackvm_binutils.object_file import write_sbo

# NOTE: ``compile_api`` (and through it the bundled runtime support) is imported
# lazily inside the functions that actually compile, so the preprocess-only
# (``-E``) and ``-print-file-name`` paths stay lightweight and do not trigger
# compilation of the runtime library.

# ---------------------------------------------------------------------------
# Package locations
# ---------------------------------------------------------------------------
_PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
_PKG_INCLUDE = os.path.join(_PKG_ROOT, "StackVM", "include")
_PKG_LIB = os.path.join(_PKG_ROOT, "lib")

# .sbc executable magic for an image with the whole memory present in the file.
_SVC_MAGIC = b"\xf7SVE\0\0\0\0"

# Recognised input file classifications (by extension).
_SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".c++", ".cp", ".i", ".ii"}
_OBJECT_EXTS = {".sbo", ".sba", ".o", ".a", ".obj", ".lib"}
# Assembly sources (case-sensitive: ``.S`` is preprocessed, ``.s`` is not).
_ASM_EXTS = {".s", ".S"}

# -std=<name> -> __STDC_VERSION__ value (None means "leave the macro undefined").
_STD_VERSIONS = {
    "c89": None,
    "c90": None,
    "gnu89": None,
    "gnu90": None,
    "iso9899:1990": None,
    "c99": "199901L",
    "gnu99": "199901L",
    "c9x": "199901L",
    "c11": "201112L",
    "gnu11": "201112L",
    "c1x": "201112L",
    "c17": "201710L",
    "gnu17": "201710L",
    "c18": "201710L",
    "c2x": "202000L",
    "gnu2x": "202000L",
    "c23": "202311L",
    "gnu23": "202311L",
}


class GccDriverError(Exception):
    """A user-facing command-line / driver error (maps to a non-zero exit)."""


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
class _MacroAction(argparse.Action):
    """Collect ``-D`` / ``-U`` into one ordered list to preserve command order.

    Each occurrence appends ``("D", value)`` or ``("U", value)`` to the shared
    ``macro_ops`` destination so that ``-DFOO -UFOO`` and ``-UFOO -DFOO`` are
    resolved in the order the user wrote them (matching GCC semantics).
    """

    def __call__(self, parser, namespace, values, option_string=None):
        ops = getattr(namespace, "macro_ops", None)
        if ops is None:
            ops = []
            setattr(namespace, "macro_ops", ops)
        ops.append((self.const, values))


def build_gcc_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="IsaacCompiler (gcc-compatible)",
        description="GCC-compatible front end producing StackVM objects/binaries",
        add_help=True,
        allow_abbrev=False,
    )
    parser.add_argument("-c", action="store_true", dest="compile_only")
    parser.add_argument("-o", dest="output", default=None, metavar="file")
    parser.add_argument("-I", action="append", default=[], dest="include_dirs")
    parser.add_argument(
        "-D", action=_MacroAction, const="D", dest="macro_ops", metavar="name[=val]"
    )
    parser.add_argument(
        "-U", action=_MacroAction, const="U", dest="macro_ops", metavar="name"
    )
    parser.add_argument("-L", action="append", default=[], dest="lib_dirs")
    parser.add_argument("-l", action="append", default=[], dest="libs")
    parser.add_argument("-T", action="append", default=[], dest="linker_scripts")
    parser.add_argument("-W", action="append", default=[], dest="warnings")
    parser.add_argument("-f", action="append", default=[], dest="fflags")
    parser.add_argument("-m", action="append", default=[], dest="mflags")
    parser.add_argument("-O", default=None, dest="opt_level", metavar="level")
    parser.add_argument("-g", action="store_true", dest="debug")
    parser.add_argument("-std", default=None, dest="std", metavar="standard")
    parser.add_argument("-nostdlib", action="store_true", dest="nostdlib")
    parser.add_argument("-nostdinc", action="store_true", dest="nostdinc")
    parser.add_argument("-nodefaultlibs", action="store_true", dest="nodefaultlibs")
    parser.add_argument("-shared", action="store_true", dest="shared")
    parser.add_argument("-static", action="store_true", dest="static")
    parser.add_argument("-march", default=None, dest="march", metavar="arch")
    parser.add_argument("-print-file-name", default=None, dest="print_file_name")
    parser.add_argument("-E", action="store_true", dest="preprocess_only")
    parser.add_argument("inputs", nargs="*")
    return parser


def normalize_gcc_args(argv: List[str]) -> List[str]:
    """Canonicalise GCC argument quirks that ``argparse`` cannot express.

    Currently this only rewrites a bare ``-O`` (meaning ``-O1`` in GCC) into
    ``-O1`` so the option does not greedily consume the following token.
    """
    out: List[str] = []
    for arg in argv:
        if arg == "-O":
            out.append("-O1")
        else:
            out.append(arg)
    return out


# ---------------------------------------------------------------------------
# Macro (-D / -U / -std) resolution
# ---------------------------------------------------------------------------
_MACRO_SPEC_RE = re.compile(r"^(\w+)(?:\((.*)\))?$")


def _make_macro_def(spec: str) -> MacroDef:
    """Build a :class:`MacroDef` from a ``-D`` argument (``name``/``name=val``/
    ``name(args)=val``)."""
    name_spec, sep, replacement = spec.partition("=")
    if not sep:
        # ``-DNAME`` with no value defines it to 1 (GCC behaviour).
        replacement = "1"
    m = _MACRO_SPEC_RE.match(name_spec.strip())
    if not m:
        raise GccDriverError(f"invalid macro definition: {spec!r}")
    name = m.group(1)
    params_str = m.group(2)
    if params_str is None:
        return MacroDef(name, None, replacement.strip())
    variadic = False
    params_str = params_str.strip()
    if params_str:
        params = [p.strip() for p in params_str.split(",")]
        if params and params[-1] == "...":
            variadic = True
            params[-1] = "__VA_ARGS__"
    else:
        params = []
    return MacroDef(name, params, replacement.strip(), variadic)


def resolve_macros(
    macro_ops: List[Tuple[str, str]],
    std: Optional[str],
) -> Tuple[Dict[str, MacroDef], List[str]]:
    """Resolve ordered ``-D``/``-U`` ops (and ``-std``) into a defines map and a
    list of names to force undefined."""
    defines: Dict[str, MacroDef] = {}
    undefined: set = set()

    # -std influences __STDC_VERSION__ before user -D/-U so users can override.
    if std is not None:
        key = std.lower()
        if key not in _STD_VERSIONS:
            raise GccDriverError(f"unrecognised -std value: {std!r}")
        version = _STD_VERSIONS[key]
        if version is None:
            undefined.add("__STDC_VERSION__")
        else:
            defines["__STDC_VERSION__"] = MacroDef(
                "__STDC_VERSION__", None, version
            )

    for kind, value in macro_ops:
        if kind == "D":
            macro = _make_macro_def(value)
            defines[macro.name] = macro
            undefined.discard(macro.name)
        else:  # "U"
            defines.pop(value, None)
            undefined.add(value)
    return defines, sorted(undefined)


# ---------------------------------------------------------------------------
# Warning / -f flag interpretation
# ---------------------------------------------------------------------------
class _WarningOptions(object):
    __slots__ = ["warnings_as_errors", "enabled"]

    def __init__(self) -> None:
        self.warnings_as_errors = False
        self.enabled: set = set()


def interpret_warnings(warning_args: List[str]) -> _WarningOptions:
    opts = _WarningOptions()
    for value in warning_args:
        # -Wl,... / -Wp,... / -Wa,... are pass-through to ld/cpp/as, not warnings.
        if value[:2] in ("l,", "p,", "a,"):
            continue
        if value == "error":
            opts.warnings_as_errors = True
        elif value == "no-error" or value == "no-error=all":
            opts.warnings_as_errors = False
        elif value.startswith("error="):
            opts.warnings_as_errors = True
        elif value.startswith("no-"):
            opts.enabled.discard(value[3:])
        else:
            opts.enabled.add(value)
    return opts


def interpret_fflags(fflags: List[str]) -> Dict[str, bool]:
    """Reduce ``-f`` flags to the handful that change driver behaviour."""
    result = {"builtin": True, "stack_protector": True}
    for flag in fflags:
        if flag == "no-builtin":
            result["builtin"] = False
        elif flag == "builtin":
            result["builtin"] = True
        elif flag in ("no-stack-protector", "no-stack-protector-all"):
            result["stack_protector"] = False
        elif flag in ("stack-protector", "stack-protector-all", "stack-protector-strong"):
            result["stack_protector"] = True
        # All other -f flags are accepted and ignored (e.g. -fPIC, -fomit-...).
    return result


# ---------------------------------------------------------------------------
# Library resolution
# ---------------------------------------------------------------------------
def _library_search_dirs(lib_dirs: List[str]) -> List[str]:
    return list(lib_dirs) + [_PKG_LIB]


def resolve_library(name: str, lib_dirs: List[str], prefer_static: bool) -> str:
    """Resolve ``-lNAME`` to a concrete object/archive path."""
    if prefer_static:
        candidates = [f"lib{name}.sba", f"lib{name}.sbo", f"{name}.sba", f"{name}.sbo"]
    else:
        candidates = [f"lib{name}.sbo", f"lib{name}.sba", f"{name}.sbo", f"{name}.sba"]
    for directory in _library_search_dirs(lib_dirs):
        for candidate in candidates:
            full = os.path.join(directory, candidate)
            if os.path.isfile(full):
                return full
    raise GccDriverError(f"cannot find -l{name}")


def find_file_name(name: str, lib_dirs: List[str]) -> str:
    """Implement ``-print-file-name=NAME``: return the resolved path or NAME."""
    for directory in _library_search_dirs(lib_dirs):
        full = os.path.join(directory, name)
        if os.path.exists(full):
            return os.path.abspath(full)
    return name


# ---------------------------------------------------------------------------
# Input classification
# ---------------------------------------------------------------------------
def classify_inputs(
    inputs: List[str],
) -> Tuple[List[str], List[str], List[str]]:
    """Split inputs into (sources, asm_sources, link_inputs) by file extension.

    Assembly extensions are matched case-sensitively so the ``.S`` (preprocess)
    vs ``.s`` (verbatim) distinction survives; everything else compares
    case-insensitively.
    """
    sources: List[str] = []
    asm_sources: List[str] = []
    link_inputs: List[str] = []
    for path in inputs:
        ext = os.path.splitext(path)[1]
        if ext in _ASM_EXTS:
            asm_sources.append(path)
        elif ext.lower() in _SOURCE_EXTS:
            sources.append(path)
        else:
            # Objects, archives and anything unrecognised go to the linker.
            link_inputs.append(path)
    return sources, asm_sources, link_inputs


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def _check_output_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise GccDriverError(f"output directory does not exist: {parent}")


def _write_standalone_image(cmpl_obj, output_path: str) -> None:
    """Write an in-process merged/linked image as a flat ``.sbc`` executable
    (byte-for-byte identical to the native ``compile`` subcommand)."""
    import struct

    with open(output_path, "wb") as fl:
        fl.write(_SVC_MAGIC)
        fl.write(
            struct.pack(
                "<QQQ",
                cmpl_obj.code_segment_end,
                cmpl_obj.data_segment_start,
                len(cmpl_obj.memory),
            )
        )
        fl.write(cmpl_obj.memory)


def _include_dirs_for(source_path: str, user_dirs: List[str], nostdinc: bool) -> List[str]:
    src_dir = os.path.dirname(os.path.abspath(source_path))
    dirs = [src_dir] + list(user_dirs)
    if not nostdinc:
        dirs.append(_PKG_INCLUDE)
    return dirs


# ---------------------------------------------------------------------------
# Compile / link orchestration
# ---------------------------------------------------------------------------
def _object_output_name(source_path: str, ext: str = ".sbo") -> str:
    base = os.path.splitext(os.path.basename(source_path))[0]
    return os.path.join(".", base + ext)


def _write_object(obj, output: str) -> None:
    if os.path.splitext(output)[1].lower() == ".o":
        write_elf_object(obj, output)
    else:
        write_sbo(obj, output)


def _compile_source_to_object(
    source: str,
    output: str,
    args,
    defines: Dict[str, MacroDef],
    undefines: List[str],
    warn: _WarningOptions,
    use_runtime_deps: bool,
) -> None:
    from .compile_api import build_compilation

    include_dirs = _include_dirs_for(source, args.include_dirs, args.nostdinc)
    result = build_compilation(
        source,
        include_dirs=include_dirs,
        name_mangling_mode=NameManglingMode.NONE,
        default_alignment=None,
        data_seg_align=4096,
        percpu_copies=1,
        link_style="shared",
        compile_only=True,
        debugging_symbols=args.debug,
        defines=defines,
        undefines=undefines,
        warnings_as_errors=warn.warnings_as_errors,
        use_runtime_deps=use_runtime_deps,
    )
    _write_object(
        result.cmpl_obj.to_stackvm_object(result.link_opts.extern_deps, None),
        output,
    )


def _assemble_source_to_object(
    source: str,
    output: str,
    args,
    defines: Dict[str, MacroDef],
    undefines: List[str],
    warn: _WarningOptions,
) -> None:
    """Assemble a ``.s`` / ``.S`` file into a ``.sbo`` object.

    ``.S`` (uppercase) is preprocessed first -- with ``__ASSEMBLER__`` defined
    and the active ``-D`` / ``-U`` / ``-I`` flags -- exactly as GCC drives
    ``cpp`` before ``as``.  ``.s`` (lowercase) is assembled verbatim.
    """
    from .code_gen.stackvm_binutils.svm_as import AssemblerError, assemble_object

    try:
        with open(source, "r") as fl:
            text = fl.read()
    except OSError as exc:
        raise GccDriverError(str(exc)) from exc
    if os.path.splitext(source)[1] == ".S":
        include_dirs = _include_dirs_for(source, args.include_dirs, args.nostdinc)
        as_defines = dict(defines)
        as_defines.setdefault(
            "__ASSEMBLER__", MacroDef("__ASSEMBLER__", None, "1")
        )
        text = preprocess(
            text, include_dirs, as_defines, undefines, warn.warnings_as_errors
        )
    try:
        obj = assemble_object(text)
    except AssemblerError as exc:
        raise GccDriverError("%s: %s" % (source, exc)) from exc
    _write_object(obj, output)


def _run_preprocess_only(
    args,
    defines: Dict[str, MacroDef],
    undefines: List[str],
    warn: _WarningOptions,
) -> int:
    """Implement ``-E``: preprocess each input and emit the expanded text.

    Output goes to the ``-o`` file when given, otherwise to stdout.  As with
    ``-c``, ``-o`` may only be combined with a single input file.
    """
    if args.output is not None and len(args.inputs) > 1:
        raise GccDriverError("cannot specify -o with -E and multiple input files")
    parts: List[str] = []
    for path in args.inputs:
        try:
            with open(path, "r") as fl:
                source = fl.read()
        except OSError as exc:
            raise GccDriverError(str(exc)) from exc
        include_dirs = _include_dirs_for(path, args.include_dirs, args.nostdinc)
        expanded = preprocess(
            source,
            include_dirs,
            defines,
            undefines,
            warn.warnings_as_errors,
        )
        parts.append(expanded)
        # Keep successive files on separate lines when concatenating.
        if not expanded.endswith("\n"):
            parts.append("\n")
    text = "".join(parts)
    if args.output is not None:
        _check_output_parent(args.output)
        with open(args.output, "w") as fl:
            fl.write(text)
    else:
        sys.stdout.write(text)
    return 0


def _run_compile_only(
    args,
    sources: List[str],
    asm_sources: List[str],
    link_inputs: List[str],
    defines: Dict[str, MacroDef],
    undefines: List[str],
    warn: _WarningOptions,
    use_runtime_deps: bool,
) -> int:
    if link_inputs:
        print(
            "warning: %s: linker input file unused because -c was given"
            % ", ".join(link_inputs),
            file=sys.stderr,
        )
    total = len(sources) + len(asm_sources)
    if args.output is not None and total > 1:
        raise GccDriverError("cannot specify -o with -c and multiple source files")
    for source in sources:
        output = args.output if args.output is not None else _object_output_name(source)
        _check_output_parent(output)
        _compile_source_to_object(
            source, output, args, defines, undefines, warn, use_runtime_deps
        )
    for source in asm_sources:
        output = args.output if args.output is not None else _object_output_name(source)
        _check_output_parent(output)
        _assemble_source_to_object(source, output, args, defines, undefines, warn)
    return 0


def _link(
    args,
    sources: List[str],
    asm_sources: List[str],
    link_inputs: List[str],
    defines: Dict[str, MacroDef],
    undefines: List[str],
    warn: _WarningOptions,
    use_runtime_deps: bool,
) -> int:
    output = args.output if args.output is not None else "a.out"
    _check_output_parent(output)

    linker_script_path = args.linker_scripts[-1] if args.linker_scripts else None

    # Convenience hosted path: a single translation unit, no extra objects,
    # no libraries and no linker script -> compile and link in-process so the
    # produced image embeds the runtime and a startup wrapper that calls main.
    # Any assembly inputs force the general object-then-link path.
    convenience = (
        len(sources) == 1
        and not asm_sources
        and not link_inputs
        and not args.libs
        and linker_script_path is None
    )
    if convenience:
        from .compile_api import build_compilation

        include_dirs = _include_dirs_for(sources[0], args.include_dirs, args.nostdinc)
        try:
            result = build_compilation(
                sources[0],
                include_dirs=include_dirs,
                name_mangling_mode=NameManglingMode.NONE,
                default_alignment=None,
                data_seg_align=4096,
                percpu_copies=1,
                link_style="shared" if args.shared else "standalone",
                compile_only=False,
                debugging_symbols=args.debug,
                defines=defines,
                undefines=undefines,
                warnings_as_errors=warn.warnings_as_errors,
                use_runtime_deps=use_runtime_deps,
            )
        except NameError as exc:
            # Missing main() in a standalone executable link is a normal user
            # error (akin to ld's "undefined reference to `main'"), not a crash.
            raise GccDriverError(str(exc)) from exc
        _write_standalone_image(result.cmpl_obj, output)
        return 0

    # General path: compile/assemble every source to a temporary object, then
    # run the raw linker over the objects, archives and resolved libraries.
    with tempfile.TemporaryDirectory(prefix="isaacc-gcc-") as tmpdir:
        object_paths: List[str] = []
        for index, source in enumerate(sources):
            base = os.path.splitext(os.path.basename(source))[0]
            obj_path = os.path.join(tmpdir, f"{index}_{base}.sbo")
            _compile_source_to_object(
                source, obj_path, args, defines, undefines, warn, use_runtime_deps
            )
            object_paths.append(obj_path)
        for index, source in enumerate(asm_sources):
            base = os.path.splitext(os.path.basename(source))[0]
            obj_path = os.path.join(tmpdir, f"asm{index}_{base}.sbo")
            _assemble_source_to_object(source, obj_path, args, defines, undefines, warn)
            object_paths.append(obj_path)

        prefer_static = args.static
        lib_paths = [resolve_library(lib, args.lib_dirs, prefer_static) for lib in args.libs]

        all_inputs = object_paths + list(link_inputs) + lib_paths
        if not all_inputs:
            raise GccDriverError("no input files")

        try:
            link_files(
                all_inputs,
                output,
                None,
                allow_undefined=args.shared,
                linker_script=(
                    None
                    if linker_script_path is None
                    else load_linker_script(linker_script_path)
                ),
            )
        except (LinkerError, OSError, ValueError) as exc:
            raise GccDriverError(str(exc)) from exc
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_gcc_driver(argv: List[str]) -> int:
    """Parse *argv* (GCC-style) and perform the requested action.

    Returns a process exit code; user errors are reported on stderr.
    """
    parser = build_gcc_parser()
    namespace, unknown = parser.parse_known_args(normalize_gcc_args(argv))
    for token in unknown:
        if token.startswith("-"):
            print(
                "warning: unrecognized command-line option '%s'" % token,
                file=sys.stderr,
            )

    macro_ops = getattr(namespace, "macro_ops", None) or []

    try:
        # -march only accepts the StackVM target.
        if namespace.march is not None and namespace.march.lower() != "stackvm":
            raise GccDriverError(
                "unsupported -march=%s (only 'stackvm' is supported)"
                % namespace.march
            )

        # -print-file-name short-circuits everything else.
        if namespace.print_file_name is not None:
            print(find_file_name(namespace.print_file_name, namespace.lib_dirs))
            return 0

        warn = interpret_warnings(namespace.warnings)
        fflags = interpret_fflags(namespace.fflags)
        defines, undefines = resolve_macros(macro_ops, namespace.std)
        use_runtime_deps = fflags["builtin"] and not namespace.nostdlib

        if not namespace.inputs:
            raise GccDriverError("no input files")

        # -E (preprocess only) takes precedence over -c and linking.
        if namespace.preprocess_only:
            return _run_preprocess_only(namespace, defines, undefines, warn)

        sources, asm_sources, link_inputs = classify_inputs(namespace.inputs)
        if namespace.compile_only:
            return _run_compile_only(
                namespace,
                sources,
                asm_sources,
                link_inputs,
                defines,
                undefines,
                warn,
                use_runtime_deps,
            )
        return _link(
            namespace,
            sources,
            asm_sources,
            link_inputs,
            defines,
            undefines,
            warn,
            use_runtime_deps,
        )
    except (GccDriverError, PreprocessorError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
