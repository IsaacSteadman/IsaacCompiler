from ...NameMangling import (
    NameManglingMode,
    normalize_name_mangling_mode,
    select_external_link_name,
)


ISAAC_RUNTIME_LINK_NAMES = {
    "memcpy": "?FPvPCvyzmemcpy",
    "memmove": "?FPvPvyzmemmove",
    "memset": "?FPvcyzmemset",
    "print": "?FPCczprint",
    "syscall": "?Fyyyyyzsyscall",
    "pow": "?Fdizpow",
}


def get_runtime_link_name(
    source_name: str,
    mode: NameManglingMode = NameManglingMode.NONE,
) -> str:
    mode = normalize_name_mangling_mode(mode)
    return select_external_link_name(
        source_name,
        ISAAC_RUNTIME_LINK_NAMES[source_name],
        mode,
    )
