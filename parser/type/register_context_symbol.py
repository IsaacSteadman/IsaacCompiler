def register_context_symbol(
    cmpl_obj: "BaseCmplObj",
    ctx_var: "ContextVariable",
    decl_type: "BaseType",
    defined: bool,
    size: int,
    alignment: int = 1,
) -> None:
    compilation = get_compilation(cmpl_obj)
    is_function = is_fn_type(decl_type)
    link_name = ctx_var.get_link_name()
    previous = compilation.symbol_registry.get(link_name)
    if (
        previous is not None
        and previous.typ is not None
        and not compare_no_cvr(previous.typ, decl_type)
    ):
        raise TypeError("Conflicting declarations for '%s'" % ctx_var.name)
    if not ctx_var.has_external_linkage():
        binding = SymbolBinding.LOCAL
    elif any(attr.name == "weak" for attr in ctx_var.attributes):
        binding = SymbolBinding.WEAK
    else:
        binding = SymbolBinding.GLOBAL
    compilation.register_symbol(
        link_name,
        ctx_var.name,
        decl_type,
        binding,
        ObjectSegment.CODE if is_function else ObjectSegment.DATA,
        SymbolType.FUNCTION if is_function else SymbolType.OBJECT,
        True,
        defined,
        size if defined else 0,
        alignment,
        ctx_var.section_name,
    )
    obj = compilation.objects.get(link_name)
    if obj is not None:
        obj.section_name = ctx_var.section_name


from .get_compilation import get_compilation
from .BaseType import BaseType
from .ContextVariable import ContextVariable
from ...code_gen.BaseCmplObj import BaseCmplObj
from ...code_gen.stackvm_binutils.object_file import (
    SymbolBinding,
    ObjectSegment,
    SymbolType,
)
from .is_fn_type import is_fn_type
from .qual_atomic_type_util import compare_no_cvr
