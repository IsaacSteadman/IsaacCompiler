import argparse
import os
import struct
from typing import Callable, Dict, List, Optional, Set, Union
from .PrettyRepr import format_pretty
from .StackVM.PyStackVM import BC_CALL, BC_HLT
from .code_gen.Compilation import Compilation
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
from .parser.type.types import CompileContext
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


argparser = argparse.ArgumentParser(description="Compile C++ code to StackVM bytecode")
argparser.add_argument(
    "input",
    metavar="input",
    type=str,
    help="input CPP file",
)
argparser.add_argument(
    "-a",
    "--data-seg-align",
    metavar="data_seg_align",
    choices=[4096, 8192, 16384, 32768],
    default=4096,
)
argparser.add_argument(
    "-o",
    "--output-binary",
    metavar="output_binary",
    type=str,
    help="output file, usually with a .sbc extension for Stackvm ByteCode",
    default=None,
)
argparser.add_argument(
    "-s",
    "--output-ast",
    metavar="output_ast",
    type=str,
    help="output file, usually with a .ast extension for Abstract Syntax Tree",
    default=None,
)
argparser.add_argument(
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
argparser.add_argument(
    "-g",
    "--debugging-symbols",
    action="store_true",
    help="generate debugging symbols",
)
argparser.add_argument(
    "-d",
    "--disassembly-output",
    metavar=("disassembly_output_file", "include_addresses", "include_syms"),
    type=str,
    nargs=3,
    help="disassembly output file. usually with a .sasm extension for Stackvm Assembly",
    dest="output_disassembly",
    default=None,
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

args = argparser.parse_args()
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
):
    print("No output specified. Use -o, -s, or -d to specify output.")
    raise SystemExit(1)


print("Tokenizing")
with open(input_file, "r") as fl:
    tokens = get_list_tokens(fl)


global_ctx = CompileContext("", None)
c = 0
end = len(tokens)
lst_stmnt: List[BaseStmnt] = []


if args.output_binary is not None or args.output_disassembly is not None:
    link_style = args.link_style
    link_opts = LinkerOptions(
        True,
        args.data_seg_align,
        lib_utils_abi.objects,
        LNK_RUN_STANDALONE if link_style == "standalone" else 0,
    )
    cmpl_opts = CompilerOptions(link_opts, True, args.debugging_symbols)
    cmpl_obj = Compilation(cmpl_opts.keep_local_syms)
    if link_opts.run_method == LNK_RUN_STANDALONE:
        main_fn = cmpl_obj.get_link("?FiPPczmain")
        emit_load_i_const(cmpl_obj.memory, 1, True, 2)
        main_fn.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_CALL, BC_HLT])
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
    used_deps = flatify_dep_desc(dep_dct, "?FiPPczmain")
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
            fl.write(
                b"\xF7SVE\0\0\0\0"
            )  # [S]tack[V]m [E]xecutable magic number for version 0000
            fl.write(
                struct.pack(
                    "<QQQ",
                    cmpl_obj.code_segment_end,
                    cmpl_obj.data_segment_start,
                    len(cmpl_obj.memory),
                )
            )
            fl.write(cmpl_obj.memory)
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
