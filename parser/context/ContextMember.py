from typing import Optional, TYPE_CHECKING


class ContextMember(object):
    def __init__(self, name: str, parent: Optional["CompileContext"]):
        self.name = name
        self.parent = parent

    def get_full_name(self):
        if self.parent is None:
            return self.name
        return "%s::%s" % (self.parent.get_full_name(), self.name)

    def get_scope_name(self):
        if self.parent is None or not self.parent.is_local_scope():
            return self.name
        return "%s::%s" % (self.parent.get_scope_name(), self.name)

    def is_var(self):
        return not (self.is_type() or self.is_scopeable() or self.is_local_scope())

    def is_scopeable(self):
        return self.is_namespace() or self.is_class()

    def is_type(self):
        return False

    def is_class(self):
        return False

    def is_namespace(self):
        return False

    def is_local_scope(self):
        return False

    def get_underlying_type(self):
        # TODO: fix this so that structs/unions/classes will directly handle this (important)
        if isinstance(self, BaseType):
            return self
        return None


if TYPE_CHECKING:
    from .CompileContext import CompileContext
from ..type.BaseType import BaseType
