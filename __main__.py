import argparse
import os
import struct
import sys
from typing import Callable, List, Optional, Union
from .PrettyRepr import format_pretty
from .Preprocessing import preprocess as cpp_preprocess
from .StackVM.runner import add_cmd_argv_vm, load_sbc, run_in_vm
from .code_gen.NameMangling import NameManglingMode
from .code_gen.get_dict_link_src import get_dict_link_src
from .code_gen.get_dict_links import get_dict_links
from .lexer.lexer import get_list_tokens
from .code_gen.stackvm_binutils.disassemble import disassemble
from .code_gen.stackvm_binutils.linker import (
    LinkerError,
    link_files,
    load_linker_script,
    load_version_script,
)
from .code_gen.stackvm_binutils.elf_file import write_elf_object
from .code_gen.stackvm_binutils.object_file import write_sbo
from .parser.type.CompileContext import CompileContext
from .parser.type.QualType import QualType
from .parser.type.PrimitiveType import PrimitiveType
from .parser.type.TypeDefCtxMember import TypeDefCtxMember
from .parser.stmnt.BaseStmnt import BaseStmnt
from .parser.stmnt.get_stmnt import get_stmnt

_SVC_MAGIC = (
    b"\xf7SVE\0\0\0\0"  # [S]tack[V]m [E]xecutable magic number for version 0000
)
_SVC_SPARSE_MAGIC = (
    b"\xf7SVE\0\0\0\1"  # executable with an omitted trailing zero-filled region
)

no_addr_options = {
    "no_addr",
    "no_address",
    "no_addresses",
    "na",
}
incl_addr_options = {
    "incl_addr",
    "include_addr",
    "include_address",
    "incl_address",
    "incl_addresses",
    "include_addresses",
    "ia",
}
no_sym_options = {
    "no_sym",
    "no_symbol",
    "no_symbols",
    "ns",
}
incl_sym_options = {
    "incl_sym",
    "incl_syms",
    "include_sym",
    "include_syms",
    "include_symbol",
    "incl_symbol",
    "incl_symbols",
    "include_symbols",
    "is",
}


def _parse_alignment_arg(value: str) -> int:
    align = int(value, 0)
    if align < 1:
        raise argparse.ArgumentTypeError("alignment must be a positive integer")
    if align & (align - 1):
        raise argparse.ArgumentTypeError("alignment must be a power of two")
    return align


def _parse_nonnegative_int_arg(value: str) -> int:
    number = int(value, 0)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return number


def _parse_positive_int_arg(value: str) -> int:
    number = int(value, 0)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def _write_object_output(obj, output_path: str) -> None:
    if os.path.splitext(output_path)[1].lower() == ".o":
        write_elf_object(obj, output_path)
    else:
        write_sbo(obj, output_path)


def _token_line_col(tokens, index):
    token = tokens[min(max(index, 0), len(tokens) - 1)]
    return token.line, token.col


# ---------------------------------------------------------------------------
# Shared optional flags inherited by both subparsers via parents=
# ---------------------------------------------------------------------------
_vm_flags_parser = argparse.ArgumentParser(add_help=False)
_vm_flags_parser.add_argument(
    "--vm-size",
    metavar="vm_size",
    type=int,
    default=65536,
    help="StackVM heap size in bytes (default: 65536)",
    dest="vm_size",
)
_vm_flags_parser.add_argument(
    "--virt-mem",
    action="store_true",
    help="enable virtual memory (4-level paging) in the StackVM",
    dest="virt_mem",
)
_vm_flags_parser.add_argument(
    "--debug",
    action="store_true",
    help="launch the interactive debugger instead of executing to completion",
)
_vm_flags_parser.add_argument(
    "--backend",
    choices=["python", "cpp"],
    default="python",
    help="StackVM backend to use: 'python' (default) or 'cpp' (native via ctypes)",
    dest="backend",
)
_vm_flags_parser.add_argument(
    "--syscalls",
    nargs="*",
    metavar="SET",
    default=[],
    dest="syscalls",
    help="syscall sets to enable: os, pygame, all, none (default: none)",
)

# ---------------------------------------------------------------------------
# Top-level parser
# ---------------------------------------------------------------------------
argparser = argparse.ArgumentParser(
    description="Compile C++ code to StackVM bytecode",
)
subparsers = argparser.add_subparsers(dest="subcommand")
subparsers.required = True

# ---------------------------------------------------------------------------
# 'compile' subcommand
# ---------------------------------------------------------------------------
compile_parser = subparsers.add_parser(
    "compile",
    help="compile a C++ source file to StackVM bytecode",
    parents=[_vm_flags_parser],
)
compile_parser.add_argument(
    "input",
    metavar="input",
    type=str,
    help="input CPP file",
)
compile_parser.add_argument(
    "-c",
    "--compile-only",
    action="store_true",
    help="compile to a relocatable StackVM object file (.sbo)",
    dest="compile_only",
)
name_mangling_group = compile_parser.add_mutually_exclusive_group()
name_mangling_group.add_argument(
    "--mangle",
    action="store_const",
    const=NameManglingMode.ISAAC,
    dest="name_mangling_mode",
    help="use Isaac/C++ external symbol name mangling",
)
name_mangling_group.add_argument(
    "--no-mangle",
    action="store_const",
    const=NameManglingMode.NONE,
    dest="name_mangling_mode",
    help="use raw C external symbol names (default)",
)
compile_parser.set_defaults(name_mangling_mode=NameManglingMode.NONE)
compile_parser.add_argument(
    "-a",
    "--data-seg-align",
    metavar="data_seg_align",
    type=int,
    choices=[4096, 8192, 16384, 32768],
    default=4096,
    help="align the start of the data segment to a page-sized boundary",
)
compile_parser.add_argument(
    "--default-alignment",
    metavar="alignment",
    type=_parse_alignment_arg,
    default=None,
    dest="default_alignment",
    help="use ALIGNMENT as the maximum natural alignment for ordinary objects "
    "and struct/union members; if omitted, keep the current no-alignment behavior",
)
compile_parser.add_argument(
    "--percpu-copies",
    metavar="count",
    type=_parse_positive_int_arg,
    default=1,
    dest="percpu_copies",
    help="reserve COUNT initialized .data..percpu units in direct linked output",
)
compile_parser.add_argument(
    "-o",
    "--output-binary",
    metavar="output_binary",
    type=str,
    help="output file, usually .sbc or .sbo",
    default=None,
)
compile_parser.add_argument(
    "-s",
    "--output-ast",
    metavar="output_ast",
    type=str,
    help="output file, usually with a .ast extension for Abstract Syntax Tree",
    default=None,
)
compile_parser.add_argument(
    "-l",
    "--link-style",
    choices=["standalone", "shared"],
    default="standalone",
    help="""Linking style.

standalone means that the output file will assume that there is no operating system and will
not link to any external libraries. linking in standalone mode will also add a wrapper section
to the output file that will call the main function and then run BC_HLT after main returns.

shared means that the output file will assume that there is an operating system and will link
to external libraries.""",
)
compile_parser.add_argument(
    "-g",
    "--debugging-symbols",
    action="store_true",
    help="generate debugging symbols",
)
compile_parser.add_argument(
    "-d",
    "--disassembly-output",
    metavar=("disassembly_output_file", "include_addresses", "include_syms"),
    type=str,
    nargs=3,
    help="disassembly output file, usually with a .sasm extension for Stackvm Assembly",
    dest="output_disassembly",
    default=None,
)
compile_parser.add_argument(
    "-I",
    "--include-dir",
    metavar="dir",
    action="append",
    default=[],
    dest="include_dirs",
    help="add a directory to the #include search path (may be given multiple times)",
)
compile_parser.add_argument(
    "-r",
    "--run",
    action="store_true",
    help="after compilation, run the output in the StackVM",
)
compile_parser.add_argument(
    "program_args",
    nargs="*",
    help="arguments forwarded to the compiled program; separate with '--' "
    "(e.g. compile input.cpp --run -- MyProg arg1 arg2)",
)

# ---------------------------------------------------------------------------
# 'link' subcommand
# ---------------------------------------------------------------------------
link_parser = subparsers.add_parser(
    "link",
    help="link StackVM object and archive files into a .sbc binary",
)
link_parser.add_argument(
    "inputs",
    nargs="+",
    metavar="input",
    help="input .sbo object or .sba archive files, processed from left to right",
)
link_parser.add_argument(
    "-o",
    "--output-binary",
    metavar="output_binary",
    default="a.sbc",
    dest="output_binary",
    help="output .sbc file (default: a.sbc)",
)
link_parser.add_argument(
    "-M",
    "-Map",
    "--map",
    "--map-file",
    metavar="map_file",
    default=None,
    dest="map_file",
    help="write a linker map showing final object and symbol addresses",
)
link_parser.add_argument(
    "-T",
    "--script",
    metavar="linker_script",
    default=None,
    dest="linker_script",
    help="use a linker script defining .text, .init.text, .init_array, "
    ".fini_array, .data, .data..percpu, .tdata, .rodata, and .bss",
)
link_parser.add_argument(
    "--allow-undefined",
    action="store_true",
    help="allow unresolved relocations and leave their addends unmodified",
)
link_parser.add_argument(
    "--code-base",
    type=_parse_nonnegative_int_arg,
    default=0,
    help="virtual address at which code begins (default: 0)",
)
link_parser.add_argument(
    "--data-base",
    type=_parse_nonnegative_int_arg,
    default=0x1000,
    help="minimum virtual address at which data begins (default: 0x1000)",
)
link_parser.add_argument(
    "-a",
    "--data-seg-align",
    type=_parse_alignment_arg,
    default=0x1000,
    dest="data_seg_align",
    help="align the data segment start to this power of two (default: 4096)",
)
link_parser.add_argument(
    "--no-runtime-aliases",
    action="store_false",
    default=True,
    dest="runtime_aliases",
    help="do not treat known mangled and unmangled runtime names as aliases",
)
link_parser.add_argument(
    "--percpu-copies",
    metavar="count",
    type=_parse_positive_int_arg,
    default=1,
    dest="percpu_copies",
    help="reserve COUNT initialized .data..percpu units (default: 1)",
)
link_parser.add_argument(
    "--gc-sections",
    action="store_true",
    dest="gc_sections",
    help="garbage-collect input sections unreachable from the entry/KEEP roots",
)
link_parser.add_argument(
    "-e",
    "--entry",
    metavar="symbol",
    default="_start",
    dest="entry_symbol",
    help="set the entry symbol used as a --gc-sections root (default: _start)",
)
link_parser.add_argument(
    "-u",
    "--undefined",
    action="append",
    default=[],
    metavar="symbol",
    dest="keep_symbols",
    help="force SYMBOL to be a --gc-sections root (repeatable)",
)
link_parser.add_argument(
    "--build-id",
    nargs="?",
    const="sha1",
    default=None,
    metavar="style",
    dest="build_id",
    help="emit a .note.gnu.build-id (style: sha1|md5|uuid|0xHEX|none)",
)
link_parser.add_argument(
    "--emit-relocs",
    action="store_true",
    dest="emit_relocs",
    help="retain symbolic relocations in the linked ELF (for KASLR)",
)
link_parser.add_argument(
    "--version-script",
    metavar="file",
    default=None,
    dest="version_script",
    help="apply a GNU symbol-version script (localizes matched symbols)",
)
link_parser.add_argument(
    "--whole-archive",
    action="store_true",
    dest="_whole_archive_flag",
    help="include every member of the archives that follow",
)
link_parser.add_argument(
    "--no-whole-archive",
    action="store_true",
    dest="_no_whole_archive_flag",
    help="turn off --whole-archive for the archives that follow",
)
link_parser.add_argument(
    "-shared",
    "--shared",
    action="store_true",
    dest="shared",
    help="produce a shared object (ET_DYN) with a dynamic section",
)
link_parser.add_argument(
    "-pie",
    "--pie",
    action="store_true",
    dest="pie",
    help="produce a position-independent executable (ET_DYN)",
)
link_parser.add_argument(
    "-soname",
    "--soname",
    metavar="name",
    default=None,
    dest="soname",
    help="set the DT_SONAME of a shared object",
)
link_parser.add_argument(
    "--needed",
    action="append",
    default=[],
    metavar="name",
    dest="needed",
    help="record a DT_NEEDED dependency (repeatable)",
)
link_parser.add_argument(
    "--subsystem",
    metavar="type",
    default=None,
    dest="subsystem",
    help="EFI subsystem for a PE/COFF (.efi) output: efi-application "
    "(default), efi-boot-service-driver, or efi-runtime-driver",
)

# Options that consume a following value token; used to reconstruct the
# positional ``--whole-archive`` regions (argparse cannot preserve the relative
# order of a batched positional list and the surrounding flags).
_LINK_VALUE_OPTS = {
    "-o", "--output-binary", "-M", "-Map", "--map", "--map-file", "-T", "--script",
    "--code-base", "--data-base", "-a", "--data-seg-align", "--percpu-copies",
    "--version-script", "-e", "--entry", "-soname", "--soname", "--needed",
    "-u", "--undefined", "--subsystem",
}
_BUILD_ID_STYLES = {"sha1", "md5", "uuid", "none", "default", "tree"}


def _compute_whole_archive_flags(link_argv, input_paths):
    """Return a per-input boolean list marking inputs inside a
    ``--whole-archive`` region, reconstructed from the raw link argv."""

    flags_in_order = []
    state = False
    skip_next = False
    for index, token in enumerate(link_argv):
        if skip_next:
            skip_next = False
            continue
        if token == "--whole-archive":
            state = True
            continue
        if token == "--no-whole-archive":
            state = False
            continue
        if token == "--build-id":
            nxt = link_argv[index + 1] if index + 1 < len(link_argv) else None
            if nxt is not None and (
                nxt in _BUILD_ID_STYLES or nxt.lower().startswith("0x")
            ):
                skip_next = True
            continue
        base = token.split("=", 1)[0]
        if base in _LINK_VALUE_OPTS:
            if "=" not in token:
                skip_next = True
            continue
        if token.startswith("-") and token != "-":
            continue
        flags_in_order.append(state)
    if len(flags_in_order) != len(input_paths):
        return [False] * len(input_paths)
    return flags_in_order

# ---------------------------------------------------------------------------
# 'addr2line' subcommand
# ---------------------------------------------------------------------------
addr2line_parser = subparsers.add_parser(
    "addr2line",
    help="resolve StackVM code addresses to source file and line",
)
addr2line_parser.add_argument(
    "binary",
    metavar="binary",
    help="input .sbc executable or .sbo object with a .debug section",
)
addr2line_parser.add_argument(
    "addresses",
    nargs="+",
    metavar="address",
    help="code address to resolve, decimal or 0x-prefixed",
)
addr2line_parser.add_argument(
    "-f",
    "--functions",
    action="store_true",
    help="print the containing function name before each source location",
)

# ---------------------------------------------------------------------------
# 'run' subcommand
# ---------------------------------------------------------------------------
run_parser = subparsers.add_parser(
    "run",
    help="load a compiled .sbc binary and run it in the StackVM",
    parents=[_vm_flags_parser],
)
run_parser.add_argument(
    "input",
    metavar="input",
    type=str,
    help="input .sbc binary file produced by 'compile -o'",
)
run_parser.add_argument(
    "program_args",
    nargs="*",
    help="arguments forwarded to the program; separate with '--' "
    "(e.g. run input.sbc -- MyProg arg1 arg2)",
)

# ---------------------------------------------------------------------------
# GCC-compatible front end (COMPAT-H1)
# ---------------------------------------------------------------------------
# Build systems (Kconfig/CMake/Meson/autoconf) invoke the compiler as if it
# were gcc — with no subcommand and gcc-style flags.  Dispatch to the
# gcc-compatible driver either explicitly (``gcc``/``cc``) or implicitly
# (the first token is not a native subcommand and not a help request).
_KNOWN_SUBCOMMANDS = {"compile", "link", "addr2line", "run"}
_raw_argv = sys.argv[1:]
if _raw_argv and _raw_argv[0] in {"gcc", "cc"}:
    from .gcc_driver import run_gcc_driver

    raise SystemExit(run_gcc_driver(_raw_argv[1:]))
if _raw_argv and _raw_argv[0] == "as":
    from .svm_as_driver import run_svm_as

    raise SystemExit(run_svm_as(_raw_argv[1:]))
# Host binutils CLIs kbuild invokes (workstream C2): nm/objdump/readelf/size/
# strip/objcopy plus the ranlib archive helper and the kallsyms generator.
_BINUTILS_TOOLS = {
    "nm",
    "objdump",
    "readelf",
    "size",
    "strip",
    "objcopy",
    "ranlib",
    "kallsyms",
}
if _raw_argv and _raw_argv[0] in _BINUTILS_TOOLS:
    from .code_gen.stackvm_binutils import host_cli

    _tool_runner = {
        "nm": host_cli.run_nm,
        "objdump": host_cli.run_objdump,
        "readelf": host_cli.run_readelf,
        "size": host_cli.run_size,
        "strip": host_cli.run_strip,
        "objcopy": host_cli.run_objcopy,
        "ranlib": host_cli.run_ranlib,
        "kallsyms": host_cli.run_kallsyms,
    }[_raw_argv[0]]
    raise SystemExit(_tool_runner(_raw_argv[1:]))
if (
    _raw_argv
    and _raw_argv[0] not in _KNOWN_SUBCOMMANDS
    and _raw_argv[0] not in {"-h", "--help"}
):
    from .gcc_driver import run_gcc_driver

    raise SystemExit(run_gcc_driver(_raw_argv))

# ---------------------------------------------------------------------------
# Parse and normalise program_args
# ---------------------------------------------------------------------------
args = argparser.parse_args()

program_args: List[str] = getattr(args, "program_args", [])
if program_args and program_args[0] == "--":
    program_args = program_args[1:]

# ---------------------------------------------------------------------------
# 'compile' subcommand logic
# ---------------------------------------------------------------------------
if args.subcommand == "compile":
    if args.compile_only and args.run:
        compile_parser.error("-c/--compile-only cannot be combined with --run")
    if args.compile_only and args.output_disassembly is not None:
        compile_parser.error(
            "-c/--compile-only cannot be combined with disassembly output"
        )
    if args.compile_only and args.output_binary is None:
        base_name = os.path.splitext(os.path.basename(args.input))[0]
        args.output_binary = os.path.join(".", base_name + ".sbo")
    if args.output_disassembly is not None:
        assert (
            args.output_disassembly[1].lower() in no_addr_options | incl_addr_options
        ), "\n".join(
            [
                f"invalid option for include_addresses: {args.output_disassembly[1]}",
                f"expected one of {no_addr_options!r} for excluding addresses",
                f"or {incl_addr_options!r} for including addresses",
            ]
        )
        assert (
            args.output_disassembly[2].lower() in no_sym_options | incl_sym_options
        ), "\n".join(
            [
                f"invalid option for include_symbols: {args.output_disassembly[2]}",
                f"expected one of {no_sym_options!r} for excluding symbols",
                f"or {incl_sym_options!r} for including symbols",
            ]
        )
        assert os.path.isdir(
            os.path.dirname(os.path.abspath(args.output_disassembly[0]))
        ), "parent directory of disassembly output file does not exist"
    if args.output_binary is not None:
        assert os.path.isdir(
            os.path.dirname(os.path.abspath(args.output_binary))
        ), "parent directory of binary output file does not exist"
    if args.output_ast is not None:
        assert os.path.isdir(
            os.path.dirname(os.path.abspath(args.output_ast))
        ), "parent directory of ast output file does not exist"

    input_file = args.input

    if (
        args.output_binary is None
        and args.output_ast is None
        and args.output_disassembly is None
        and not args.run
        and not args.compile_only
    ):
        print("No output specified. Use -o, -s, -d, or --run to specify output.")
        raise SystemExit(1)

    print("Tokenizing")
    _pkg_include = os.path.join(os.path.dirname(__file__), "StackVM", "include")
    _src_dir = os.path.dirname(os.path.abspath(input_file))
    _include_dirs = [_src_dir, _pkg_include] + (args.include_dirs or [])

    if (
        args.output_binary is not None
        or args.output_disassembly is not None
        or args.run
        or args.compile_only
    ):
        # The tokenize → parse → compile → merge/link pipeline lives in
        # compile_api.build_compilation so the gcc-compatible driver can share
        # exactly this behaviour.  Imported lazily so the run / link / addr2line
        # subcommands (and gcc-mode -E / -print-file-name) do not pay the cost
        # of compiling the bundled runtime support library.
        from .compile_api import build_compilation

        _result = build_compilation(
            input_file,
            include_dirs=_include_dirs,
            name_mangling_mode=args.name_mangling_mode,
            default_alignment=args.default_alignment,
            data_seg_align=args.data_seg_align,
            percpu_copies=args.percpu_copies,
            link_style=args.link_style,
            compile_only=args.compile_only,
            debugging_symbols=args.debugging_symbols,
            verbose=True,
        )
        cmpl_obj = _result.cmpl_obj
        global_ctx = _result.global_ctx
        lst_stmnt = _result.lst_stmnt
        link_opts = _result.link_opts
        if args.output_disassembly is not None:
            outf, incl_addr_str, incl_sym_str = args.output_disassembly
            incl_addr = incl_addr_str.lower() in incl_addr_options
            incl_sym = incl_sym_str.lower() in incl_sym_options
            address_fmt: Optional[Union[str, Callable[[str, int], str]]] = None
            if incl_sym:
                address_fmt = f"  0x%0{len(str(cmpl_obj.code_segment_end - 1))}X: %s"
            with open(args.output_disassembly[0], "w") as fl:
                fl.write(
                    disassemble(
                        cmpl_obj.memory,
                        None,
                        cmpl_obj.code_segment_end,
                        get_dict_links(cmpl_obj) if incl_sym else {},
                        address_fmt if incl_addr else None,
                        get_dict_link_src(cmpl_obj) if incl_sym else None,
                    )
                )
        if args.output_binary is not None:
            if args.compile_only:
                _write_object_output(
                    cmpl_obj.to_stackvm_object(
                        link_opts.extern_deps,
                        args.default_alignment,
                    ),
                    args.output_binary,
                )
            else:
                with open(args.output_binary, "wb") as fl:
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
        if args.run:
            print("Running in StackVM")
            syscall_sets = args.syscalls or []
            run_in_vm(
                cmpl_obj.memory,
                cmpl_obj.code_segment_end,
                cmpl_obj.data_segment_start,
                get_dict_links(cmpl_obj),
                program_args,
                args.vm_size,
                args.virt_mem,
                args.debug,
                args.backend,
                syscall_sets if syscall_sets else None,
            )
    else:
        print("Generating AST")
        with open(input_file, "r") as fl:
            _source = fl.read()
        _source = cpp_preprocess(_source, _include_dirs)
        tokens = get_list_tokens(_source)
        global_ctx = CompileContext(
            "",
            None,
            args.default_alignment,
            name_mangling_mode=args.name_mangling_mode,
        )
        # Register built-in type alias: typedef unsigned char *va_list
        _va_list_base = PrimitiveType.from_str_name(["unsigned", "char"])
        _va_list_t = QualType(QualType.QUAL_PTR, _va_list_base)
        global_ctx.new_type(
            "va_list", TypeDefCtxMember("va_list", global_ctx, _va_list_t)
        )
        lst_stmnt: List[BaseStmnt] = []
        c = 0
        end = len(tokens)
        while c < end:
            prev_c = c
            try:
                stmnt, c = get_stmnt(tokens, c, end, global_ctx)
            except Exception as exc:
                ln, col = _token_line_col(tokens, c)
                raise SyntaxError(
                    f"error when attempting to parse statement after {input_file}:{ln}:{col}"
                ) from exc
            lst_stmnt.append(stmnt)
    if args.output_ast is not None:
        with open(args.output_ast, "w") as fl:
            fl.write(
                format_pretty(
                    {
                        "lst_stmnt": lst_stmnt,
                        "global_ctx": global_ctx,
                    }
                )
            )

# ---------------------------------------------------------------------------
# 'link' subcommand logic
# ---------------------------------------------------------------------------
elif args.subcommand == "link":
    for target in (args.output_binary, args.map_file):
        if target is not None and not os.path.isdir(
            os.path.dirname(os.path.abspath(target))
        ):
            link_parser.error("parent directory does not exist: %s" % target)
    whole_archive_flags = _compute_whole_archive_flags(sys.argv[2:], args.inputs)
    try:
        result = link_files(
            args.inputs,
            args.output_binary,
            args.map_file,
            allow_undefined=args.allow_undefined,
            code_base=args.code_base,
            data_base=args.data_base,
            data_alignment=args.data_seg_align,
            runtime_aliases=args.runtime_aliases,
            linker_script=(
                None
                if args.linker_script is None
                else load_linker_script(args.linker_script)
            ),
            percpu_copies=args.percpu_copies,
            whole_archive_flags=whole_archive_flags,
            gc_sections=args.gc_sections,
            entry_symbol=args.entry_symbol,
            keep_symbols=args.keep_symbols,
            build_id=args.build_id,
            emit_relocs=args.emit_relocs,
            version_script=(
                None
                if args.version_script is None
                else load_version_script(args.version_script)
            ),
            shared=args.shared,
            pie=args.pie,
            soname=args.soname,
            needed=args.needed,
            subsystem=args.subsystem,
        )
    except (LinkerError, OSError, ValueError) as exc:
        link_parser.error(str(exc))
    summary = "Linked %u object(s): code end %#x, data start %#x, image size %#x" % (
        len(result.included_objects),
        result.code_segment_end,
        result.data_segment_start,
        len(result.memory),
    )
    if result.removed_sections:
        summary += " (gc removed %u section(s))" % len(result.removed_sections)
    if result.build_id:
        summary += " build-id %s" % result.build_id.hex()
    print(summary)

# ---------------------------------------------------------------------------
# 'addr2line' subcommand logic
# ---------------------------------------------------------------------------
elif args.subcommand == "addr2line":
    from .code_gen.stackvm_binutils.addr2line import (
        Addr2LineError,
        load_debug_info,
        parse_address,
        resolve_addresses,
    )

    try:
        addresses = [parse_address(value) for value in args.addresses]
        info = load_debug_info(args.binary)
    except (Addr2LineError, OSError, ValueError, argparse.ArgumentTypeError) as exc:
        addr2line_parser.error(str(exc))
    for line in resolve_addresses(info, addresses, args.functions):
        print(line)

# ---------------------------------------------------------------------------
# 'run' subcommand logic
# ---------------------------------------------------------------------------
elif args.subcommand == "run":
    input_file = args.input
    print(f"Loading binary: {input_file}")
    memory, code_segment_end, data_segment_start = load_sbc(input_file)
    total_memory_length = len(memory)
    print(
        f"  code_segment_end   = {code_segment_end:#010x}\n"
        f"  data_segment_start = {data_segment_start:#010x}\n"
        f"  memory_size        = {total_memory_length:#010x}"
    )
    print("Running in StackVM")
    syscall_sets = args.syscalls or []
    run_in_vm(
        memory,
        code_segment_end,
        data_segment_start,
        {},  # no debug symbols available from bare .sbc binary
        program_args,
        args.vm_size,
        args.virt_mem,
        args.debug,
        args.backend,
        syscall_sets if syscall_sets else None,
    )
