from ....PrettyRepr import PrettyRepr, get_pretty_repr, get_pretty_repr_enum
from ....ParseConstants import LST_INIT_TYPES, INIT_NONE


class SingleVarDecl(PrettyRepr):
    # used to declare variables (init_args is list of expressions) and define functions (init_args is list of statements)
    def __init__(
        self,
        type_name: "BaseType",
        var_name: str,
        init_args,
        ext_spec,
        init_type=INIT_NONE,
    ):
        """
        :param list[BaseExpr]|list[CurlyStmnt] init_args:
        :param int ext_spec:
        :param int init_type:
        """
        self.type_name = type_name
        self.var_name = var_name
        self.op_fn_type = OperatorType.FUNCTION
        self.op_fn_data = None
        # TODO: add support for curly initialization (arrays and structs)
        if type_name.type_class_id in [TypeClass.QUAL, TypeClass.PRIM]:
            fn_types = type_name.get_ctor_fn_types()
            if len(fn_types):
                index_fn_t, lst_conv = abstract_overload_resolver(init_args, fn_types)
                if index_fn_t >= len(fn_types):
                    raise TypeError(
                        "No overloaded constructor for %s exists for argument types: (%s)"
                        % (
                            get_user_str_from_type(type_name),
                            ", ".join(
                                [get_user_str_from_type(x.t_anot) for x in init_args]
                            ),
                        )
                    )
                self.op_fn_type = OperatorType.NATIVE
                self.op_fn_data = index_fn_t
                assert lst_conv is not None
                init_args = lst_conv
        self.init_args = init_args
        for expr in init_args:
            if isinstance(expr, BaseExpr):
                expr.init_temps(None)
        self.ext_spec = ext_spec
        self.init_type = init_type

    # TODO: Maybe put a stub build Method?

    def pretty_repr(self, pretty_repr_ctx=None):
        rtn = [self.__class__.__name__] + get_pretty_repr(
            (self.type_name, self.var_name, self.init_args, self.ext_spec),
            pretty_repr_ctx,
        )
        rtn[-1:-1] = [","] + get_pretty_repr_enum(LST_INIT_TYPES, self.init_type)
        return rtn


from ...expr.BaseExpr import BaseExpr
from ...expr.OperatorType import OperatorType
from ...type.BaseType import BaseType, TypeClass
from ...expr.abstract_overload_resolver import abstract_overload_resolver
from ...type.get_user_str_from_type import get_user_str_from_type
