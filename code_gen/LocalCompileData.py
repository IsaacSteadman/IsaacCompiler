from typing import Dict, List, Optional, Set, Tuple, TypeVar, Union

from ..parser.type.align_util import align_up

_T = TypeVar("_T")


class BreakableScope(object):
    def __init__(
        self,
        continue_link: Optional["Linkage"],
        break_link: "Linkage",
        continue_cleanup_target: Optional["LocalCompileData"],
        break_cleanup_target: "LocalCompileData",
    ):
        self.continue_link = continue_link
        self.break_link = break_link
        self.continue_cleanup_target = continue_cleanup_target
        self.break_cleanup_target = break_cleanup_target


class LocalCompileData(object):
    def __init__(self, parent: Optional["LocalCompileData"] = None):
        initial_bp_off = 0 if parent is None else parent.bp_off
        self._bp_off: int = initial_bp_off
        self._frame_max_ref: List[int] = (
            [initial_bp_off] if parent is None else parent._frame_max_ref
        )
        self.scope_bp_off_start: int = initial_bp_off
        self.vars: List[Tuple["ContextVariable", "BaseLink"]] = []
        self.local_stack_sizes: List[int] = []
        self.local_links: Dict[str, int] = {}
        self.sizes = {}  # TODO: appears unused
        self.parent = parent
        self.dynamic_stack_size_links: List["BaseLink"] = (
            [] if parent is None else list(parent.dynamic_stack_size_links)
        )
        self.local_labels: Dict[str, "Linkage"] = (
            {} if parent is None else parent.local_labels
        )
        self.local_label_references: Set[str] = (
            set() if parent is None else parent.local_label_references
        )
        self.cur_breakable: Optional[BreakableScope] = (
            None if parent is None else parent.cur_breakable
        )
        self.res_data: Optional[Tuple["BaseType", "BaseLink"]] = None

    @property
    def bp_off(self) -> int:
        return self._bp_off

    @bp_off.setter
    def bp_off(self, value: int) -> None:
        self._bp_off = value
        if value > self._frame_max_ref[0]:
            self._frame_max_ref[0] = value

    @property
    def max_frame_size(self) -> int:
        return self._frame_max_ref[0]

    def _emit_rst_sp(self, cmpl_obj: "BaseCmplObj", stack_sz: int) -> None:
        if stack_sz:
            sz_cls = emit_load_i_const(cmpl_obj.memory, stack_sz, False)
            cmpl_obj.memory.extend([BC_RST_SP1 + sz_cls])

    def _compile_cleanup_call(
        self,
        cmpl_obj: "BaseCmplObj",
        context: "CompileContext",
        ctx_var: "ContextVariable",
        link: "BaseLink",
    ) -> None:
        if ctx_var.cleanup_name is None:
            return

        from ..parser.type.IdentifiedQualType import IdentifiedQualType
        from ..parser.type.PrimitiveType import void_t
        from ..parser.type.QualType import QualType
        from ..parser.type.align_size_of import size_of
        from ..parser.type.is_fn_type import is_fn_type
        from ..parser.type.qual_atomic_type_util import compare_no_cvr, get_value_type
        from .branch_emit import emit_rel_call
        from ..StackVM.PyStackVM import BC_ADD_SP1

        try:
            cleanup_var = context.scoped_get(ctx_var.cleanup_name)
        except KeyError:
            cleanup_var = None
        if not isinstance(cleanup_var, ContextVariable) or not is_fn_type(
            cleanup_var.typ
        ):
            raise TypeError(
                "cleanup function '%s' was not declared" % ctx_var.cleanup_name
            )
        fn_type = get_value_type(cleanup_var.typ)
        if not isinstance(fn_type, QualType) or fn_type.qual_id != QualType.QUAL_FN:
            raise TypeError("cleanup target '%s' is not a function" % cleanup_var.name)
        if not compare_no_cvr(get_value_type(fn_type.tgt_type), void_t):
            raise TypeError("cleanup function '%s' must return void" % cleanup_var.name)
        if (
            not isinstance(fn_type.ext_inf, list)
            or len(fn_type.ext_inf) != 1
            or fn_type.ext_inf[0] is None
        ):
            raise TypeError(
                "cleanup function '%s' must accept one pointer argument"
                % cleanup_var.name
            )
        param_type = fn_type.ext_inf[0]
        if isinstance(param_type, IdentifiedQualType):
            param_type = param_type.typ
        expected_type = QualType(QualType.QUAL_PTR, ctx_var.typ)
        param_value_type = get_value_type(param_type)
        accepts_void_ptr = (
            isinstance(param_value_type, QualType)
            and param_value_type.qual_id == QualType.QUAL_PTR
            and compare_no_cvr(get_value_type(param_value_type.tgt_type), void_t)
        )
        if not accepts_void_ptr and not compare_no_cvr(param_type, expected_type):
            raise TypeError(
                "cleanup function '%s' parameter must be compatible with a pointer "
                "to '%s'" % (cleanup_var.name, ctx_var.name)
            )

        sz_ret = size_of(fn_type.tgt_type)
        sz_cls_ret = emit_load_i_const(cmpl_obj.memory, sz_ret, False)
        cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls_ret])
        self.bp_off += sz_ret
        link.emit_lea(cmpl_obj.memory)
        self.bp_off += 8
        emit_rel_call(cmpl_obj.memory, cmpl_obj.get_link(cleanup_var.get_link_name()))
        sz_cls_args = emit_load_i_const(cmpl_obj.memory, 8, False)
        cmpl_obj.memory.extend([BC_RST_SP1 + sz_cls_args])
        self.bp_off -= 8
        self.bp_off -= sz_ret

    def _compile_leave_scope_lifo(
        self, cmpl_obj: "BaseCmplObj", context: "CompileContext"
    ):
        from ..parser.type.vla import contains_variable_length_array_type

        fixed_to_pop = 0
        c = len(self.vars)
        while c > 0:
            c -= 1
            assert isinstance(c, int)
            ctx_var, _lnk = self.vars[c]
            stack_sz = self.local_stack_sizes[c]
            self._compile_cleanup_call(cmpl_obj, context, ctx_var, _lnk)
            if contains_variable_length_array_type(ctx_var.typ):
                self._emit_rst_sp(cmpl_obj, fixed_to_pop)
                fixed_to_pop = 0
                res = ctx_var.typ.compile_var_de_init(
                    cmpl_obj, context, VarRefTosNamed(ctx_var), self
                )
                assert res == 0, "unexpected VLA de-initialization result"
                fixed_to_pop += stack_sz
                continue
            res = ctx_var.typ.compile_var_de_init(
                cmpl_obj, context, VarRefTosNamed(ctx_var), self
            )
            assert res == -1, "cannot do complex de-initialization"
            fixed_to_pop += stack_sz
        self._emit_rst_sp(cmpl_obj, fixed_to_pop)

    def compile_leave_scope(self, cmpl_obj: "BaseCmplObj", context: "CompileContext"):
        from ..parser.type.vla import contains_variable_length_array_type

        stack_sz = self.bp_off - self.scope_bp_off_start
        if not stack_sz and not any(ctx_var.cleanup_name for ctx_var, _ in self.vars):
            return
        if any(contains_variable_length_array_type(ctx_var.typ) for ctx_var, _ in self.vars):
            self._compile_leave_scope_lifo(cmpl_obj, context)
            return
        c = len(
            self.vars
        )  # TODO: Convert to putLocal and __getitem__ for LocalLink access
        while c > 0:
            c -= 1
            assert isinstance(c, int)
            ctx_var, lnk = self.vars[c]
            # TODO: change steps involved
            # step 1:
            #   do deinitialization (non-trivial destructors including member variables)
            #     NOTE: this may require new instruction for load (REG_SP to get current stack pointer)
            # step 2:
            #   do deallocation (if necessary)
            self._compile_cleanup_call(cmpl_obj, context, ctx_var, lnk)
            res = ctx_var.typ.compile_var_de_init(
                cmpl_obj, context, VarRefTosNamed(ctx_var), self
            )
            assert res == -1, "cannot do complex de-initialization"
        self._emit_rst_sp(cmpl_obj, stack_sz)

    def get_rel_bp_off(self):
        parent = self.parent
        return self.bp_off + (0 if parent is None else parent.bp_off)

    def get_label(self, k: str) -> "Linkage":
        link = self.local_labels.get(k, None)
        if link is None:
            link = self.local_labels[k] = Linkage()
        return link

    def reference_label(self, k: str) -> "Linkage":
        self.local_label_references.add(k)
        return self.get_label(k)

    def get_local(self, k: str) -> "BaseLink":
        return self[k][1]

    def make_local_ref(self, bp_off: int, sz_var: int, bp_off_pre_inc: bool) -> "BaseLink":
        if self.dynamic_stack_size_links:
            base_bp_off = bp_off + sz_var if bp_off_pre_inc else bp_off
            return DynamicLocalRef(
                base_bp_off, sz_var, self.dynamic_stack_size_links
            )
        return (
            LocalRef.from_bp_off_pre_inc(bp_off, sz_var)
            if bp_off_pre_inc
            else LocalRef.from_bp_off_post_inc(bp_off, sz_var)
        )

    def reserve_stack_storage(
        self,
        ctx_var: "ContextVariable",
        sz_var: Optional[int] = None,
        bp_off: Optional[int] = None,
        bp_off_pre_inc: bool = False,
    ) -> "BaseLink":
        if sz_var is None:
            sz_var = size_of(ctx_var.typ)
        if bp_off is None:
            bp_off = self.bp_off
        add_bp = bp_off == self.bp_off
        align = ctx_var.effective_alignment()
        if align > 1:
            if bp_off_pre_inc:
                bp_off = align_up(bp_off + sz_var, align) - sz_var
            else:
                bp_off = align_up(bp_off, align)
        lnk = self.make_local_ref(bp_off, sz_var, bp_off_pre_inc)
        if add_bp:
            self.bp_off = bp_off + sz_var
        return lnk

    def put_local(
        self,
        ctx_var: "ContextVariable",
        link_name: str = None,
        sz_var: Optional[int] = None,
        bp_off: Optional[int] = None,
        bp_off_pre_inc: bool = False,
    ) -> "BaseLink":
        if link_name is None:
            link_name = ctx_var.get_link_name()
        if sz_var is None:
            sz_var = size_of(ctx_var.typ)
        lnk = self.reserve_stack_storage(
            ctx_var, sz_var, bp_off, bp_off_pre_inc
        )
        # print "PUT_LOCAL: link_name=%r, initial-bp_off=%r, lnk.RelAddr=%r" % (link_name, self.bp_off, lnk.RelAddr)
        self.setitem(link_name, (ctx_var, lnk), sz_var)
        # print "PUT_LOCAL: final-bp_off=%r" % self.bp_off
        return lnk

    def __getitem__(self, k: str) -> Tuple["ContextVariable", "BaseLink"]:
        try:
            return self.vars[self.local_links[k]]
        except KeyError:
            if self.parent is None:
                raise
            return self.parent[k]

    def setitem(
        self,
        k: str,
        v: Tuple["ContextVariable", "BaseLink"],
        stack_size: int = 0,
    ):
        var_index = self.local_links.get(k, None)
        if var_index is not None:
            raise KeyError("Variable '%s' already exists" % k)
        self.local_links[k] = len(self.vars)
        self.vars.append(v)
        self.local_stack_sizes.append(stack_size)

    def strict_get(self, k: str, default: _T = None) -> Union["BaseLink", _T]:
        var_index = self.local_links.get(k, None)
        if var_index is None:
            return default
        return self.vars[var_index][1]

    def get(self, k: str, default: _T = None) -> Union["BaseLink", _T]:
        lnk = self.strict_get(k, None)
        if lnk is None:
            if self.parent is None:
                return default
            return self.parent.get(k, default)
        return lnk


from .BaseCmplObj import BaseCmplObj
from .BaseLink import BaseLink
from .DynamicLocalRef import DynamicLocalRef
from ..parser.type.BaseType import BaseType
from ..parser.type.ContextVariable import ContextVariable
from .Linkage import Linkage
from .LocalRef import LocalRef
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import BC_RST_SP1
from ..parser.type.CompileContext import CompileContext
from ..parser.type.align_size_of import size_of
from ..parser.type.helpers.VarRef import VarRefTosNamed
