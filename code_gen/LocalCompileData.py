from typing import Dict, List, Optional, TYPE_CHECKING, Tuple, TypeVar, Union


class LocalCompileData(object):
    def __init__(self, parent: Optional["LocalCompileData"] = None):
        self.bp_off: int = 0 if parent is None else parent.bp_off
        self.vars: List[Tuple["ContextVariable", "LocalRef"]] = []
        self.local_links: Dict[str, int] = {}
        self.sizes = {}  # TODO: appears unused
        self.parent = parent
        self.local_labels: Dict[str, "Linkage"] = (
            {} if parent is None else parent.local_labels
        )
        self.cur_breakable: Optional[Tuple["Linkage", "Linkage"]] = (
            None if parent is None else parent.cur_breakable
        )
        self.res_data: Optional[Tuple["BaseType", "BaseLink"]] = None

    def compile_leave_scope(self, cmpl_obj: "BaseCmplObj", context: "CompileContext"):
        rel_bp_off = self.get_rel_bp_off()
        if not rel_bp_off:
            return
        stack_sz = 0
        c = len(
            self.vars
        )  # TODO: Convert to putLocal and __getitem__ for LocalLink access
        while c > 0:
            c -= 1
            assert isinstance(c, int)
            ctx_var, lnk = self.vars[c]
            sz_var = size_of(ctx_var.typ)
            # TODO: change steps involved
            # step 1:
            #   do deinitialization (non-trivial destructors including member variables)
            #     NOTE: this may require new instruction for load (REG_SP to get current stack pointer)
            # step 2:
            #   do deallocation (if necessary)
            res = ctx_var.typ.compile_var_de_init(
                cmpl_obj, context, VarRefTosNamed(ctx_var), self
            )
            assert res == -1, "cannot do complex de-initialization"
            stack_sz += sz_var
        if stack_sz != 0:
            sz_cls = emit_load_i_const(cmpl_obj.memory, stack_sz, False)
            cmpl_obj.memory.extend([BC_RST_SP1 + sz_cls])

    def get_rel_bp_off(self):
        parent = self.parent
        return self.bp_off + (0 if parent is None else parent.bp_off)

    def get_label(self, k: str) -> "Linkage":
        link = self.local_labels.get(k, None)
        if link is None:
            link = self.local_labels[k] = Linkage()
        return link

    def get_local(self, k: str) -> "LocalRef":
        return self[k][1]

    def put_local(
        self,
        ctx_var: "ContextVariable",
        link_name: str = None,
        sz_var: Optional[int] = None,
        bp_off: Optional[int] = None,
        bp_off_pre_inc: bool = False,
    ) -> "LocalRef":
        if link_name is None:
            link_name = ctx_var.get_link_name()
        if sz_var is None:
            sz_var = size_of(ctx_var.typ)
        if bp_off is None:
            bp_off = self.bp_off
        add_bp = bp_off == self.bp_off
        lnk = (
            LocalRef.from_bp_off_pre_inc(bp_off, sz_var)
            if bp_off_pre_inc
            else LocalRef.from_bp_off_post_inc(bp_off, sz_var)
        )
        # print "PUT_LOCAL: link_name=%r, initial-bp_off=%r, lnk.RelAddr=%r" % (link_name, self.bp_off, lnk.RelAddr)
        self.setitem(link_name, (ctx_var, lnk))
        if add_bp:
            self.bp_off += sz_var
        # print "PUT_LOCAL: final-bp_off=%r" % self.bp_off
        return lnk

    def __getitem__(self, k: str) -> Tuple["ContextVariable", "LocalRef"]:
        try:
            return self.vars[self.local_links[k]]
        except KeyError:
            if self.parent is None:
                raise
            return self.parent[k]

    def setitem(self, k: str, v: Tuple["ContextVariable", "LocalRef"]):
        var_index = self.local_links.get(k, None)
        if var_index is not None:
            raise KeyError("Variable '%s' already exists" % k)
        self.local_links[k] = len(self.vars)
        self.vars.append(v)

    def strict_get(
        self, k: str, default: TypeVar("T") = None
    ) -> Union["LocalRef", TypeVar("T")]:
        var_index = self.local_links.get(k, None)
        if var_index is None:
            return default
        return self.vars[var_index][1]

    def get(
        self, k: str, default: TypeVar("T") = None
    ) -> Union["LocalRef", TypeVar("T")]:
        lnk = self.strict_get(k, None)
        if lnk is None:
            if self.parent is None:
                return default
            return self.parent.get(k, default)
        return lnk


if TYPE_CHECKING:
    from .BaseCmplObj import BaseCmplObj
    from .BaseLink import BaseLink
    from ..parser.type.BaseType import BaseType
    from ..parser.type.types import ContextVariable

from .Linkage import Linkage
from .LocalRef import LocalRef
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import BC_RST_SP1
from ..parser.type.types import CompileContext, size_of
from ..parser.type.helpers.VarRef import VarRefTosNamed
