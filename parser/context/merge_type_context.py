from typing import Union


def merge_type_context(
    typ: Union["EnumType", "ClassType", "UnionType", "StructType"],
    context: "CompileContext",
) -> Union["EnumType", "ClassType", "UnionType", "StructType", "ContextMember"]:
    other = context.type_name_strict(typ.name)
    assert other is None or isinstance(
        other, (ClassType, StructType, UnionType, EnumType)
    ), "Issue: %s is not a Composite Type" % repr(other)
    # TODO: account for other = typedef
    if other is None:
        if typ.defined:
            other = context.new_type(typ.name, typ)
        else:
            other = context.type_name(typ.name)
            if other is None:
                other = context.new_type(typ.name, typ)
    elif typ.defined and other.defined:
        raise NameError("Redefinition of Typename '%s' not allowed" % typ.name)
    elif typ.defined:
        typ.merge_to(other)
    return other


from ..type.ClassType import ClassType
from ..type.UnionType import UnionType
from ..context.CompileContext import CompileContext
from ..context.ContextMember import ContextMember
from ..type.EnumType import EnumType
from ..type.StructType import StructType
