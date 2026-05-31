import argparse
import os
import struct
from typing import Callable, Dict, List, Optional, Set, Union
from .PrettyRepr import format_pretty
from .Preprocessing import preprocess as cpp_preprocess
from .StackVM.PyStackVM import BC_CALL, BC_HLT, BC_RET
from .StackVM.runner import add_cmd_argv_vm, run_in_vm
from .code_gen.Compilation import Compilation, INIT_GLOBALS_LINK_NAME
from .code_gen.CompilerOptions import CompilerOptions
from .code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from .code_gen.compile_stmnt import compile_stmnt
from .code_gen.get_dict_link_src import get_dict_link_src
from .code_gen.get_dict_links import get_dict_links
from .lexer.lexer import get_list_tokens
from .code_gen.stackvm_binutils.disassemble import disassemble
from .code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from .parser.stmnt.BaseStmnt import BaseStmnt
from .parser.stmnt.get_stmnt import get_stmnt
from .parser.type.types import CompileContext, QualType, PrimitiveType, TypeDefCtxMember
from .code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import lib_utils_abi


def flatify_dep_desc(dep_dct: Dict[str, List[str]], start_k: str) -> Set[str]:
    rtn = set()
    set_next = {start_k}
    while len(set_next):
        set_get = set_next
        rtn |= set_get
        set_next = set()
        for k in set_get:
            if k not in dep_dct:
                raise KeyError("Unresolved External Symbol: " + k)
            set_next.update(dep_dct[k])
        set_next -= rtn
    return rtn


_SVC_MAGIC = (
    b"\xf7SVE\0\0\0\0"  # [S]tack[V]m [E]xecutable magic number for version 0000
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
    "-a",
    "--data-seg-align",
    metavar="data_seg_align",
    choices=[4096, 8192, 16384, 32768],
    default=4096,
)
compile_parser.add_argument(
    "-o",
    "--output-binary",
    metavar="output_binary",
    type=str,
    help="output file, usually with a .sbc extension for Stackvm ByteCode",
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
    nargs=argparse.REMAINDER,
    help="arguments forwarded to the compiled program; separate with '--' "
    "(e.g. compile input.cpp --run -- MyProg arg1 arg2)",
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
    nargs=argparse.REMAINDER,
    help="arguments forwarded to the program; separate with '--' "
    "(e.g. run input.sbc -- MyProg arg1 arg2)",
)

# ---------------------------------------------------------------------------
# Parse and normalise program_args
# ---------------------------------------------------------------------------
args = argparser.parse_args()

program_args: List[str] = args.program_args
if program_args and program_args[0] == "--":
    program_args = program_args[1:]

# ---------------------------------------------------------------------------
# 'compile' subcommand logic
# ---------------------------------------------------------------------------
if args.subcommand == "compile":
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
    ):
        print("No output specified. Use -o, -s, -d, or --run to specify output.")
        raise SystemExit(1)

    print("Tokenizing")
    with open(input_file, "r") as fl:
        _source = fl.read()
    _pkg_include = os.path.join(os.path.dirname(__file__), "StackVM", "include")
    _src_dir = os.path.dirname(os.path.abspath(input_file))
    _include_dirs = [_src_dir, _pkg_include] + (args.include_dirs or [])
    _source = cpp_preprocess(_source, _include_dirs)
    tokens = get_list_tokens(_source)

    global_ctx = CompileContext("", None)
    # Register built-in type alias: typedef unsigned char *va_list
    _va_list_base = PrimitiveType.from_str_name(["unsigned", "char"])
    _va_list_t = QualType(QualType.QUAL_PTR, _va_list_base)
    global_ctx.new_type("va_list", TypeDefCtxMember("va_list", global_ctx, _va_list_t))
    c = 0
    end = len(tokens)
    lst_stmnt: List[BaseStmnt] = []

    if (
        args.output_binary is not None
        or args.output_disassembly is not None
        or args.run
    ):
        link_style = args.link_style
        link_opts = LinkerOptions(
            True,
            args.data_seg_align,
            lib_utils_abi.objects,
            LNK_RUN_STANDALONE if link_style == "standalone" else 0,
        )
        cmpl_opts = CompilerOptions(link_opts, True, args.debugging_symbols)
        cmpl_obj = Compilation(cmpl_opts.keep_local_syms)
        print("Generating AST and binary inline")
        while c < end:
            prev_c = c
            try:
                stmnt, c = get_stmnt(tokens, c, end, global_ctx)
            except Exception as exc:
                ln = tokens[c].line
                col = tokens[c].col
                raise SyntaxError(
                    f"error when attempting to parse statement after {input_file}:{ln}:{col}"
                ) from exc
            lst_stmnt.append(stmnt)
            try:
                compile_stmnt(cmpl_obj, stmnt, global_ctx, None)
            except Exception as exc:
                lnA = tokens[prev_c].line
                colA = tokens[prev_c].col
                lnB = tokens[c].line
                colB = tokens[c].col
                raise RuntimeError(
                    f"compile error when compiling statement between {input_file}:{lnA}:{colA} and {input_file}:{lnB}:{colB}"
                ) from exc
        if link_opts.run_method == LNK_RUN_STANDALONE:
            init_obj = cmpl_obj.objects.get(INIT_GLOBALS_LINK_NAME)
            if init_obj is not None:
                init_obj.memory.append(BC_RET)
                cmpl_obj.get_link(INIT_GLOBALS_LINK_NAME).emit_lea(cmpl_obj.memory)
                cmpl_obj.memory.extend([BC_CALL])
            main_fn = cmpl_obj.get_link("?FiPPczmain")
            emit_load_i_const(cmpl_obj.memory, 1, True, 2)
            main_fn.emit_lea(cmpl_obj.memory)
            cmpl_obj.memory.extend([BC_CALL, BC_HLT])
        print("building dependency tree")
        dep_tree = [("", sorted(cmpl_obj.linkages))]
        for k in cmpl_obj.objects:
            cur = cmpl_obj.objects[k]
            dep_tree.append((k, sorted(cur.linkages)))
        if link_opts.extern_deps is not None:
            for k in link_opts.extern_deps:
                cur = link_opts.extern_deps[k]
                dep_tree.append((k, sorted(cur.linkages)))
        dep_dct: Dict[str, List[str]] = dict(dep_tree)
        used_deps = flatify_dep_desc(dep_dct, "")
        def_deps = {k for k, _ in dep_tree if k}
        unused_deps = def_deps - used_deps
        if len(unused_deps):
            print("UNUSED: " + ", ".join(sorted(unused_deps)))
        if cmpl_opts.merge_and_link:
            excl = unused_deps if link_opts.remove_unused_deps else None
            cmpl_obj.merge_all(link_opts, link_opts.extern_deps, excl)
            cmpl_obj.link_all()
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
        while c < end:
            prev_c = c
            try:
                stmnt, c = get_stmnt(tokens, c, end, global_ctx)
            except Exception as exc:
                ln = tokens[c].line
                col = tokens[c].col
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
# 'run' subcommand logic
# ---------------------------------------------------------------------------
elif args.subcommand == "run":
    input_file = args.input
    print(f"Loading binary: {input_file}")
    with open(input_file, "rb") as fl:
        magic = fl.read(8)
        assert (
            magic == _SVC_MAGIC
        ), f"invalid magic in binary file: expected {_SVC_MAGIC!r}, got {magic!r}"
        header_bytes = fl.read(24)
        assert (
            len(header_bytes) == 24
        ), "binary file is too short to contain a valid header"
        code_segment_end, data_segment_start, total_memory_length = struct.unpack(
            "<QQQ", header_bytes
        )
        memory = bytearray(fl.read(total_memory_length))
    assert len(memory) == total_memory_length, (
        f"binary file is truncated: expected {total_memory_length} bytes of memory, "
        f"got {len(memory)}"
    )
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
