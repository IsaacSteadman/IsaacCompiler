from typing import Optional
from .ContextMember import ContextMember


class TypeDefCtxMember(ContextMember):
    def __init__(self, name: str, parent: Optional["CompileContext"], typ: "BaseType"):
        super(TypeDefCtxMember, self).__init__(name, parent)
        self.typ = typ

    def is_type(self):
        return True

    def get_underlying_type(self):
        return self.typ


from .CompileContext import CompileContext
from .BaseType import BaseType
