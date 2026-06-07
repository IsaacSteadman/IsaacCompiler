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
    if ctx_var.cleanup_name is not None and not ctx_var.uses_stack_storage():
        raise TypeError("cleanup attribute requires automatic local storage")
    if ctx_var.noreturn and not is_function:
        raise TypeError("noreturn attribute requires a function")
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
    symbol_defined = defined or ctx_var.alias_name is not None
    compilation.register_symbol(
        link_name,
        ctx_var.name,
        decl_type,
        binding,
        ObjectSegment.CODE if is_function else ObjectSegment.DATA,
        SymbolType.FUNCTION if is_function else SymbolType.OBJECT,
        True,
        symbol_defined,
        size if symbol_defined else 0,
        alignment,
        ctx_var.section_name,
        ctx_var.used,
    )
    if ctx_var.alias_name is not None:
        target_name = ctx_var.alias_name
        target_var = None
        if ctx_var.parent is not None:
            try:
                target_var = ctx_var.parent.scoped_get(target_name)
            except KeyError:
                target_var = None
        if isinstance(target_var, ContextVariable):
            target_name = target_var.get_link_name()
        compilation.register_symbol_alias(link_name, target_name)
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
