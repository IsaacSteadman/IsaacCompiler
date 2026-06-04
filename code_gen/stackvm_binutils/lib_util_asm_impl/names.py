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
    "strlen": "?FPCczstrlen",
    "__svm_bswap2": "?Ftz__svm_bswap2",
    "__svm_bswap4": "?Fjz__svm_bswap4",
    "__svm_bswap8": "?Fyz__svm_bswap8",
    "__svm_clz4": "?Fjz__svm_clz4",
    "__svm_clz8": "?Fyz__svm_clz8",
    "__svm_ctz4": "?Fjz__svm_ctz4",
    "__svm_ctz8": "?Fyz__svm_ctz8",
    "__svm_ffs4": "?Fjz__svm_ffs4",
    "__svm_ffs8": "?Fyz__svm_ffs8",
    "__svm_popcnt4": "?Fjz__svm_popcnt4",
    "__svm_popcnt8": "?Fyz__svm_popcnt8",
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
