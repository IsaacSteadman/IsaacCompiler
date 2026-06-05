def get_compilation(cmpl_obj: "BaseCmplObj") -> "Compilation":
    if isinstance(cmpl_obj, Compilation):
        return cmpl_obj
    parent = getattr(cmpl_obj, "parent", None)
    if isinstance(parent, Compilation):
        return parent
    raise TypeError("Expected a Compilation-backed compile object")


from ...code_gen.BaseCmplObj import BaseCmplObj
from ...code_gen.Compilation import Compilation
