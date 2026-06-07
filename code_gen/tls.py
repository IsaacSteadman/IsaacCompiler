"""Thread-local storage (TLS) layout constants and the ``TlsLink`` helper.

The StackVM TLS ABI follows the classic *static / local-exec* model:

* Thread-local variables (``__thread`` / ``_Thread_local``) are emitted into a
  dedicated ``.tdata`` section.  Together these form the **TLS template** — the
  initialisation image that a loader copies into every thread's TLS block.
* The linker lays the template out contiguously and defines the boundary
  symbols ``__tls_template_start`` / ``__tls_template_end`` / ``__tls_size``.
* The thread pointer lives in the ``SVSR_TLS_BASE`` system register.  A
  thread-local object ``x`` is addressed at runtime as

      &x_runtime = SVSR_TLS_BASE + (&x_in_template - __tls_template_start)

  i.e. the variable's link-time offset within the template, biased by the
  per-thread base.  ``TlsLink`` emits exactly this computation in ``emit_lea``;
  because every load/store path in ``BaseLink`` funnels through ``emit_lea``,
  wrapping a variable's ordinary link in a ``TlsLink`` makes reads, writes,
  array decay and member access all resolve to the current thread's copy.

See ``StackVM/Documentation/ThreadLocalStorage.html`` for the full ABI.
"""

from .BaseLink import BaseLink
from ..StackVM.PyStackVM import (
    BCR_SYSREG,
    BCR_SZ_8,
    BC_ADD8,
    BC_LOAD,
    BC_SUB8,
    SVSR_TLS_BASE,
)

# Initialised thread-local data.  Zero-initialised thread-locals are emitted
# here too (as explicit zero bytes); a separate ``.tbss`` optimisation can be
# layered on later without changing the ABI seen by generated code.
TLS_SECTION_NAME = ".tdata"

# Linker-defined symbols describing the TLS template.
TLS_TEMPLATE_START_SYMBOL = "__tls_template_start"
TLS_TEMPLATE_END_SYMBOL = "__tls_template_end"
TLS_SIZE_SYMBOL = "__tls_size"
TLS_ALIGN_SYMBOL = "__tls_align"

TLS_LINKER_DEFINED_SYMBOLS = frozenset(
    (
        TLS_TEMPLATE_START_SYMBOL,
        TLS_TEMPLATE_END_SYMBOL,
        TLS_SIZE_SYMBOL,
        TLS_ALIGN_SYMBOL,
    )
)


def matches_tls_section(name: str) -> bool:
    return name == TLS_SECTION_NAME or name.startswith(TLS_SECTION_NAME + ".")


class TlsLink(BaseLink):
    """A link wrapper that resolves a thread-local variable to the current
    thread's TLS block.

    ``base_link`` is the variable's ordinary (template-relative) link, and
    ``tls_start_link`` is the link for ``__tls_template_start``.  ``emit_lea``
    pushes ``base_link`` address - template start + ``SVSR_TLS_BASE``.
    """

    def __init__(self, base_link: "BaseLink", tls_start_link: "BaseLink"):
        self.base_link = base_link
        self.tls_start_link = tls_start_link

    def get_offset_link(self, offset: int) -> "TlsLink":
        return TlsLink(self.base_link.get_offset_link(offset), self.tls_start_link)

    def emit_lea(self, memory):
        # &var_in_template
        self.base_link.emit_lea(memory)
        # - __tls_template_start  -> offset within the TLS block
        self.tls_start_link.emit_lea(memory)
        memory.append(BC_SUB8)
        # + SVSR_TLS_BASE  -> absolute address in the current thread's block
        memory.extend([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_TLS_BASE])
        memory.append(BC_ADD8)


def wrap_tls_link(cmpl_obj, ctx_var, link: "BaseLink") -> "BaseLink":
    """Return *link* wrapped in a ``TlsLink`` when *ctx_var* is thread-local,
    otherwise *link* unchanged."""
    if getattr(ctx_var, "is_thread_local", False):
        return TlsLink(link, cmpl_obj.get_link(TLS_TEMPLATE_START_SYMBOL))
    return link
