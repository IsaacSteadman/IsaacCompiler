"""Regression tests guarding the refactor of the inline assembler.

``code_gen/stackvm_binutils/assemble.py`` was refactored to extract a reusable
per-line encoder (:func:`encode_asm_line`) and emit-environment abstraction so
that the standalone object assembler (``svm-as``) can share it.  The historical
:func:`assemble` entry point must keep behaving exactly as before -- it is on
the hot path for every inline ``asm`` block and every bundled runtime helper.

These tests lock that behaviour: local labels resolve in place, global and
external-code references are routed to the right tables, and the whole bundled
runtime library still assembles cleanly.
"""

import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.code_gen.BaseCmplObj import BaseCmplObj
from IsaacCompiler.code_gen.Linkage import Linkage
from IsaacCompiler.code_gen.NameMangling import NameManglingMode
from IsaacCompiler.code_gen.stackvm_binutils.assemble import assemble
from IsaacCompiler.code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import (
    get_lib_utils_abi,
)


# The real memset body (see lib_util_asm_impl/memset.py): a backward branch to
# :beginLoop and a forward branch to :endLoop, both local code labels.
_MEMSET_ASM = """
@ptr
lRa*res
STOR-ABS_S8|SZ_8
~+end,8d0
@ptr
@num
ADD8
lRa*end
STOR-ABS_S8|SZ_8
:beginLoop
@ptr
@end
CMP8
GE0
lRr[1]*:endLoop
RJMPIF


@value
@ptr
STOR-ABS_S8|SZ_1

@ptr
8d1
ADD8
lRa*ptr
STOR-ABS_S8|SZ_8
lRr[1]*:beginLoop
RJMP
:endLoop
~-end
RET
"""

_MEMSET_RELBP = {"ptr": (0x10, 8), "value": (0x18, 1), "num": (0x19, 8), "res": (0x21, 8)}


class AssembleRegressionTests(unittest.TestCase):
    def test_inline_asm_resolves_local_labels(self):
        unit = BaseCmplObj()
        unresolved = assemble(unit, dict(_MEMSET_RELBP), _MEMSET_ASM)
        # All :beginLoop / :endLoop references resolve in place -> nothing left.
        self.assertEqual(unresolved, {})
        self.assertTrue(len(unit.memory) > 0)
        # No global linkages were created for purely-local assembly.
        self.assertEqual(
            [name for name, lnk in unit.linkages.items() if lnk.lst_tgt], []
        )

    def test_assembly_is_deterministic(self):
        unit_a = BaseCmplObj()
        assemble(unit_a, dict(_MEMSET_RELBP), _MEMSET_ASM)
        unit_b = BaseCmplObj()
        assemble(unit_b, dict(_MEMSET_RELBP), _MEMSET_ASM)
        self.assertEqual(bytes(unit_a.memory), bytes(unit_b.memory))

    def test_local_branch_offsets_are_patched(self):
        # A short loop: a forward branch to :done and a backward branch to :top
        # must be back-patched (the 8-byte placeholder is no longer all zero).
        unit = BaseCmplObj()
        asm = """
:top
8d1
lRr[1]*:done
RJMPIF
lRr[1]*:top
RJMP
:done
RET
"""
        unresolved = assemble(unit, {}, asm)
        self.assertEqual(unresolved, {})
        # Both branches are back-patched, so no unpatched 8-byte relocation
        # placeholder (a run of 8 zero bytes) survives in the assembled body.
        self.assertNotIn(bytes(8), bytes(unit.memory))

    def test_global_reference_routes_to_compilation_unit(self):
        unit = BaseCmplObj()
        unresolved = assemble(unit, {}, "gRa*external_fn\nRET\n")
        # A global reference is recorded on the compilation unit (for the
        # compiler/linker to resolve), not in the returned local-label dict.
        self.assertEqual(unresolved, {})
        self.assertIn("external_fn", unit.linkages)
        self.assertEqual(len(unit.linkages["external_fn"].lst_tgt), 1)

    def test_external_code_link_is_recorded_not_resolved(self):
        # asm-goto style: a code label owned by the caller is recorded in the
        # supplied dict and left for the caller to resolve.
        unit = BaseCmplObj()
        external = {"c_label": Linkage()}
        unresolved = assemble(
            unit, {}, "lRr[1]*:c_label\nRJMP\n", external_code_links=external
        )
        self.assertEqual(unresolved, {})
        self.assertEqual(len(external["c_label"].lst_tgt), 1)

    def test_bundled_runtime_library_still_assembles(self):
        # Exercises every add_* helper (memcpy/memmove/memset/syscall/print/pow
        # and the ByteCopyFn family) through the refactored encoder.  Bypass the
        # lru_cache so the assembly genuinely re-runs.
        compilation = get_lib_utils_abi.__wrapped__(NameManglingMode.NONE)
        self.assertTrue(compilation.objects)
        for name, obj in compilation.objects.items():
            self.assertTrue(len(obj.memory) > 0, "empty runtime helper: %s" % name)


if __name__ == "__main__":
    unittest.main()
