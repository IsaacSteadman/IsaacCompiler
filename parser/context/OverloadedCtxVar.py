from typing import List, Optional
from .ContextVariable import ContextVariable


# TODO: add code to deal with this type of context variable
class OverloadedCtxVar(ContextVariable):
    def __init__(
        self, name: str, specific_ctx_vars: Optional[List[ContextVariable]] = None
    ):
        super(OverloadedCtxVar, self).__init__(name, MultiType())
        self.specific_ctx_vars = [] if specific_ctx_vars is None else specific_ctx_vars

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.name, self.specific_ctx_vars)
        )

    def add_ctx_var(self, inst: ContextVariable):
        self.specific_ctx_vars.append(inst)


from ...PrettyRepr import get_pretty_repr
from ..type.MultiType import MultiType
