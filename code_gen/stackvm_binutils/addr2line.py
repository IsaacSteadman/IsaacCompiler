import argparse
from typing import Iterable, List, Optional

from .debug_info import (
    DEBUG_SECTION_NAME,
    StackVMDebugInfo,
    format_addr2line,
    loads_debug,
    resolve_function,
    resolve_line,
)
from .executable_file import SBC_DEBUG_MAGIC, load_sbc
from .elf_file import ELF_MAGIC, load_elf_executable, load_elf_object
from .object_file import SBO_MAGIC, ObjectSegment, StackVMObject, load_sbo


class Addr2LineError(Exception):
    pass


def _debug_from_stackvm_object(obj: StackVMObject, path: str) -> bytes:
    chunks = []
    for section in obj.sections:
        if section.name == DEBUG_SECTION_NAME or section.name.startswith(
            DEBUG_SECTION_NAME + "."
        ):
            if section.segment != ObjectSegment.DATA or section.is_nobits:
                raise Addr2LineError("invalid .debug section in %s" % path)
            chunks.append(obj.data[section.offset : section.offset + section.size])
    if not chunks:
        return b""
    if len(chunks) > 1:
        infos = [loads_debug(chunk) for chunk in chunks]
        lines = []
        functions = []
        for info in infos:
            lines.extend(info.lines)
            functions.extend(info.functions)
        from .debug_info import dumps_debug

        return dumps_debug(StackVMDebugInfo(lines, functions))
    return chunks[0]


def _debug_from_object(path: str) -> bytes:
    return _debug_from_stackvm_object(load_sbo(path), path)


def load_debug_info(path: str) -> StackVMDebugInfo:
    with open(path, "rb") as fl:
        magic = fl.read(8)
    if magic == SBO_MAGIC:
        debug_payload = _debug_from_object(path)
    elif magic[:4] == ELF_MAGIC:
        try:
            debug_payload = _debug_from_stackvm_object(load_elf_object(path), path)
        except ValueError:
            try:
                debug_payload = load_elf_executable(path).debug_info
            except ValueError as exc:
                raise Addr2LineError("unrecognized input format: %s" % path) from exc
    elif magic == SBC_DEBUG_MAGIC:
        debug_payload = load_sbc(path).debug_info
    else:
        try:
            executable = load_sbc(path)
        except ValueError as exc:
            raise Addr2LineError("unrecognized input format: %s" % path) from exc
        debug_payload = executable.debug_info
    if not debug_payload:
        return StackVMDebugInfo()
    try:
        return loads_debug(debug_payload)
    except ValueError as exc:
        raise Addr2LineError("invalid debug information in %s: %s" % (path, exc))


def parse_address(value: str) -> int:
    try:
        address = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid address: %s" % value) from exc
    if address < 0:
        raise argparse.ArgumentTypeError("address must be non-negative")
    return address


def resolve_addresses(
    info: StackVMDebugInfo,
    addresses: Iterable[int],
    include_functions: bool = False,
) -> List[str]:
    lines = []
    for address in addresses:
        if include_functions:
            function = resolve_function(info, address)
            lines.append("??" if function is None else function.name)
        lines.append(format_addr2line(resolve_line(info, address)))
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stackvm-addr2line",
        description="Resolve StackVM code addresses to source locations.",
    )
    parser.add_argument("binary", help="input .sbc executable or .sbo object")
    parser.add_argument("addresses", nargs="+", type=parse_address)
    parser.add_argument(
        "-f",
        "--functions",
        action="store_true",
        help="print the containing function name before each source location",
    )
    args = parser.parse_args(argv)
    try:
        info = load_debug_info(args.binary)
    except (OSError, Addr2LineError, ValueError) as exc:
        parser.error(str(exc))
    for line in resolve_addresses(info, args.addresses, args.functions):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
