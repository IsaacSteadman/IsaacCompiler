PERCPU_SECTION_NAME = ".data..percpu"

PERCPU_START_SYMBOLS = ("__percpu_start", "__per_cpu_start")
PERCPU_END_SYMBOLS = ("__percpu_end", "__per_cpu_end")
PERCPU_SIZE_SYMBOLS = ("__percpu_size", "__per_cpu_size")

PERCPU_PRIMARY_START_SYMBOL = PERCPU_START_SYMBOLS[0]
PERCPU_PRIMARY_SIZE_SYMBOL = PERCPU_SIZE_SYMBOLS[0]

PERCPU_LINKER_DEFINED_SYMBOLS = frozenset(
    PERCPU_START_SYMBOLS + PERCPU_END_SYMBOLS + PERCPU_SIZE_SYMBOLS
)


def matches_percpu_section(name: str) -> bool:
    return name == PERCPU_SECTION_NAME or name.startswith(PERCPU_SECTION_NAME + ".")
