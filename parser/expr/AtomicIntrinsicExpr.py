from typing import List

from .BaseExpr import BaseExpr, ExprType


class AtomicIntrinsicExpr(BaseExpr):
    """AST node for compiler-lowered atomic intrinsics."""

    expr_id = ExprType.ATOMIC_INTRINSIC

    INTRINSIC_LOAD = 0
    INTRINSIC_STORE = 1
    INTRINSIC_XCHG = 2
    INTRINSIC_CAS_STRONG = 3
    INTRINSIC_FADD = 4
    INTRINSIC_FSUB = 5
    INTRINSIC_FAND = 6
    INTRINSIC_FOR = 7
    INTRINSIC_FXOR = 8

    _NAMES = [
        "__svm_atomic_load_explicit",
        "__svm_atomic_store_explicit",
        "__svm_atomic_exchange_explicit",
        "__svm_atomic_compare_exchange_strong_explicit",
        "__svm_atomic_fetch_add_explicit",
        "__svm_atomic_fetch_sub_explicit",
        "__svm_atomic_fetch_and_explicit",
        "__svm_atomic_fetch_or_explicit",
        "__svm_atomic_fetch_xor_explicit",
    ]

    def __init__(
        self,
        intrinsic_id: int,
        args: List["BaseExpr"],
        value_type: "BaseType",
        order: int,
        fail_order: int = 0,
    ):
        self.intrinsic_id = intrinsic_id
        self.args = args
        self.value_type = value_type
        self.order = order
        self.fail_order = fail_order

    def pretty_repr(self, pretty_repr_ctx=None):
        from ...PrettyRepr import get_pretty_repr

        return (
            [self.__class__.__name__, "(", self._NAMES[self.intrinsic_id], ","]
            + get_pretty_repr(self.args, pretty_repr_ctx)
            + [",", repr(self.order), ")"]
        )


from ..type.BaseType import BaseType
