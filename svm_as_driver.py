"""GNU-``as``-compatible command-line front end for the StackVM assembler.

This is reached as the ``as`` subcommand::

    python -m IsaacCompiler as -o output.sbo input.S

It accepts the small slice of the GNU ``as`` flag vocabulary that build systems
actually use (``-o``, ``-I``, ``--defsym``, ``-g``, warning flags) and turns one
or more StackVM assembly files into a single relocatable ``.sbo`` object.

Following GCC's driver convention, an uppercase ``.S`` input is run through the C
preprocessor first (so ``#include`` / ``#define`` work and ``__ASSEMBLER__`` is
defined), whereas a lowercase ``.s`` input is assembled verbatim (a leading ``#``
is an assembly comment, not a preprocessor directive).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

from .Preprocessing import MacroDef, PreprocessorError, preprocess
from .code_gen.stackvm_binutils.elf_file import write_elf_object
from .code_gen.stackvm_binutils.object_file import write_sbo
from .code_gen.stackvm_binutils.svm_as import AssemblerError, ObjectAssembler
from .gcc_driver import (
    GccDriverError,
    _check_output_parent,
    _include_dirs_for,
)


def build_as_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="IsaacCompiler as",
        description="GNU-as-compatible StackVM assembler",
        add_help=True,
        allow_abbrev=False,
    )
    parser.add_argument("-o", dest="output", default="a.out", metavar="file")
    parser.add_argument("-I", action="append", default=[], dest="include_dirs")
    parser.add_argument(
        "--defsym", action="append", default=[], dest="defsyms", metavar="sym=val"
    )
    parser.add_argument("-g", "--gen-debug", action="store_true", dest="debug")
    # Accepted-and-ignored GNU as flags (so real build commands parse cleanly).
    parser.add_argument("-W", "--no-warn", action="store_true", dest="no_warn")
    parser.add_argument("--warn", action="store_true", dest="warn")
    parser.add_argument("--fatal-warnings", action="store_true", dest="fatal_warnings")
    parser.add_argument("-nostdinc", action="store_true", dest="nostdinc")
    parser.add_argument("inputs", nargs="*")
    return parser


def _parse_defsym(spec: str) -> tuple:
    name, sep, value = spec.partition("=")
    name = name.strip()
    if not sep or not name:
        raise GccDriverError("invalid --defsym (expected name=value): %r" % spec)
    try:
        number = int(value.strip(), 0)
    except ValueError as exc:
        raise GccDriverError(
            "--defsym value must be an integer: %r" % spec
        ) from exc
    return name, number


def _read_source(path: str) -> str:
    try:
        with open(path, "r") as fl:
            return fl.read()
    except OSError as exc:
        raise GccDriverError(str(exc)) from exc


def run_svm_as(argv: List[str]) -> int:
    """Parse *argv* (GNU-as style) and assemble the inputs into one ``.sbo``."""
    parser = build_as_parser()
    namespace, unknown = parser.parse_known_args(argv)
    for token in unknown:
        if token.startswith("-"):
            print(
                "warning: unrecognized assembler option '%s'" % token,
                file=sys.stderr,
            )

    try:
        if not namespace.inputs:
            raise GccDriverError("no input files")

        assembler = ObjectAssembler()
        for spec in namespace.defsyms:
            name, value = _parse_defsym(spec)
            assembler.constants[name] = value

        for path in namespace.inputs:
            source = _read_source(path)
            # Only an uppercase .S is preprocessed (GCC convention).
            if os.path.splitext(path)[1] == ".S":
                include_dirs = _include_dirs_for(
                    path, namespace.include_dirs, namespace.nostdinc
                )
                defines = {"__ASSEMBLER__": MacroDef("__ASSEMBLER__", None, "1")}
                source = preprocess(source, include_dirs, defines, [], False)
            assembler.assemble_text(source)

        obj = assembler.to_object()
        _check_output_parent(namespace.output)
        if os.path.splitext(namespace.output)[1].lower() == ".o":
            write_elf_object(obj, namespace.output)
        else:
            write_sbo(obj, namespace.output)
        return 0
    except (GccDriverError, AssemblerError, PreprocessorError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
