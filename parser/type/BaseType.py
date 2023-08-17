from enum import Enum
from typing import List, Optional, Tuple, Union, TYPE_CHECKING
from ...PrettyRepr import PrettyRepr


class TypeClass(Enum):
    PRIM = 0
    QUAL = 1
    ENUM = 2
    UNION = 3
    CLASS = 4
    STRUCT = 5
    MULTI = 6


class BaseType(PrettyRepr):
    type_class_id = None

    def to_mangle_str(self, top_decl: bool = False) -> str:
        raise NotImplementedError("Not Implemented")

    def to_user_str(self) -> str:
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self) -> List["BaseType"]:
        raise NotImplementedError("Not Implemented")

    def compile_var_init(
        self,
        cmpl_obj: "BaseCmplObj",
        init_args: List[Union["BaseExpr", "CurlyStmnt"]],
        context: "CompileContext",
        ref: "VarRef",
        cmpl_data: Optional["LocalCompileData"] = None,
        temp_links: Optional[List[Tuple["BaseType", "BaseLink"]]] = None,
    ):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(
        self,
        cmpl_obj: "BaseCmplObj",
        context: "CompileContext",
        ref: "VarRef",
        cmpl_data: Optional["LocalCompileData"] = None,
    ) -> int:
        # CompileVarDeInit is responsible for deallocating off the stack if CompileVarInit allocated on the stack
        #   CompileVarDeInit should return the size it deallocated
        #   or it should return -1/MAX_UINT if the size deallocation is all that is required
        #   this is done in-order to maintain the original code generation behavior that results in 2 instructions
        #   to deallocate all the variables in a scope all at once (if possible)
        # TODO: use CompileVarDeInit in CompileExpr/CompileStmnt/CompileLeaveScope? according the comments above
        raise NotImplementedError("Not Implemented")

    def compile_conv(
        self,
        cmpl_obj: "BaseCmplObj",
        expr: "BaseExpr",
        context: "CompileContext",
        cmpl_data: Optional["LocalCompileData"] = None,
        temp_links: Optional[List[Tuple["BaseType", "BaseLink"]]] = None,
    ):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr: "BaseExpr") -> "BaseType":
        raise NotImplementedError("Not Implemented")


if TYPE_CHECKING:
    from .helpers.VarRef import VarRef
    from ..context.CompileContext import CompileContext
    from ..stmnt.CurlyStmnt import CurlyStmnt
    from ..expr.BaseExpr import BaseExpr
    from ...code_gen.BaseCmplObj import BaseCmplObj
    from ...code_gen.BaseLink import BaseLink
    from ...code_gen.LocalCompileData import LocalCompileData
