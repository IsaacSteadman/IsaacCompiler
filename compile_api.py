"""Shared compilation pipeline used by both the native ``compile`` subcommand
and the GCC-compatible driver (:mod:`IsaacCompiler.gcc_driver`).

The native CLI (``IsaacCompiler.__main__``) historically inlined the whole
tokenize → parse → compile → merge/link pipeline at module scope.  That logic
is factored out here so the GCC-compatible front end can reuse exactly the same
behaviour instead of duplicating (and slowly diverging from) it.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Set, Tuple

from .Preprocessing import MacroDef, preprocess as cpp_preprocess
from .code_gen.Compilation import Compilation
from .code_gen.CompilerOptions import CompilerOptions
from .code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from .code_gen.NameMangling import NameManglingMode
from .code_gen.compile_stmnt import compile_stmnt
from .lexer.lexer import get_list_tokens
from .lib.runtime_support import get_runtime_extern_deps
from .parser.stmnt.BaseStmnt import BaseStmnt
from .parser.stmnt.get_stmnt import get_stmnt
from .parser.type.types import (
    CompileContext,
    PrimitiveType,
    QualType,
    TypeDefCtxMember,
)


def flatify_dep_desc(dep_dct: Dict[str, List[str]], start_k: str) -> Set[str]:
    """Return every dependency reachable from *start_k* in *dep_dct*."""
    rtn: Set[str] = set()
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


def _token_line_col(tokens, index) -> Tuple[int, int]:
    token = tokens[min(max(index, 0), len(tokens) - 1)]
    return token.line, token.col


class CompilationResult(object):
    """Everything the callers need after :func:`build_compilation` runs."""

    __slots__ = [
        "cmpl_obj",
        "global_ctx",
        "lst_stmnt",
        "link_opts",
        "cmpl_opts",
    ]

    def __init__(
        self,
        cmpl_obj: Compilation,
        global_ctx: CompileContext,
        lst_stmnt: List[BaseStmnt],
        link_opts: LinkerOptions,
        cmpl_opts: CompilerOptions,
    ) -> None:
        self.cmpl_obj = cmpl_obj
        self.global_ctx = global_ctx
        self.lst_stmnt = lst_stmnt
        self.link_opts = link_opts
        self.cmpl_opts = cmpl_opts


def build_compilation(
    input_file: str,
    *,
    include_dirs: List[str],
    name_mangling_mode: NameManglingMode,
    default_alignment: Optional[int],
    data_seg_align: int,
    percpu_copies: int,
    link_style: str,
    compile_only: bool,
    debugging_symbols: bool,
    defines: Optional[Dict[str, MacroDef]] = None,
    undefines: Optional[List[str]] = None,
    warnings_as_errors: bool = False,
    use_runtime_deps: bool = True,
    verbose: bool = False,
) -> CompilationResult:
    """Tokenize, parse, compile and (unless *compile_only*) merge/link *input_file*.

    Parameters mirror the historical ``compile`` subcommand behaviour:

    ``include_dirs``
        Full ordered ``#include`` search path (the caller is responsible for
        prepending the source directory and, unless ``-nostdinc``, the bundled
        StackVM headers).
    ``link_style``
        ``"standalone"`` emits a startup wrapper that calls ``main`` then halts;
        ``"shared"`` merges/links without a startup wrapper.
    ``compile_only``
        When True, produce a relocatable object (no merge/link, no startup).
    ``use_runtime_deps``
        When False (``-nostdlib`` / ``-fno-builtin``) the bundled runtime
        support objects are not offered to the linker.
    """
    with open(input_file, "r") as fl:
        source = fl.read()
    source = cpp_preprocess(
        source,
        include_dirs,
        defines,
        undefines,
        warnings_as_errors,
    )
    tokens = get_list_tokens(source)

    global_ctx = CompileContext(
        "",
        None,
        default_alignment,
        name_mangling_mode=name_mangling_mode,
    )
    # Register built-in type alias: typedef unsigned char *va_list
    va_list_base = PrimitiveType.from_str_name(["unsigned", "char"])
    va_list_t = QualType(QualType.QUAL_PTR, va_list_base)
    global_ctx.new_type(
        "va_list", TypeDefCtxMember("va_list", global_ctx, va_list_t)
    )

    runtime_extern_deps = (
        get_runtime_extern_deps(name_mangling_mode) if use_runtime_deps else None
    )
    link_opts = LinkerOptions(
        True,
        data_seg_align,
        runtime_extern_deps,
        (
            0
            if compile_only
            else (LNK_RUN_STANDALONE if link_style == "standalone" else 0)
        ),
        default_alignment,
        name_mangling_mode,
        percpu_copies,
    )
    cmpl_opts = CompilerOptions(
        link_opts,
        not compile_only,
        debugging_symbols,
        name_mangling_mode,
    )
    cmpl_obj = Compilation(
        cmpl_opts.keep_local_syms,
        name_mangling_mode,
        default_alignment,
    )
    cmpl_obj.source_path = os.path.abspath(input_file)

    if verbose:
        print("Generating AST and binary inline")
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
                f"error when attempting to parse statement after "
                f"{input_file}:{ln}:{col}"
            ) from exc
        lst_stmnt.append(stmnt)
        try:
            compile_stmnt(cmpl_obj, stmnt, global_ctx, None)
        except Exception as exc:
            lnA, colA = _token_line_col(tokens, prev_c)
            lnB, colB = _token_line_col(tokens, c)
            raise RuntimeError(
                f"compile error when compiling statement between "
                f"{input_file}:{lnA}:{colA} and {input_file}:{lnB}:{colB}"
            ) from exc

    if compile_only:
        cmpl_obj.finalize_global_initializer()
    elif link_opts.run_method == LNK_RUN_STANDALONE:
        main_var = global_ctx.var_name_strict("main")
        if main_var is None:
            raise NameError("Standalone output requires a definition of main")
        cmpl_obj.emit_standalone_startup(main_var.get_link_name())

    if not compile_only:
        if verbose:
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
        if len(unused_deps) and verbose:
            print("UNUSED: " + ", ".join(sorted(unused_deps)))
        if cmpl_opts.merge_and_link:
            excl = unused_deps if link_opts.remove_unused_deps else None
            cmpl_obj.merge_all(link_opts, link_opts.extern_deps, excl)
            cmpl_obj.link_all()

    return CompilationResult(
        cmpl_obj,
        global_ctx,
        lst_stmnt,
        link_opts,
        cmpl_opts,
    )
