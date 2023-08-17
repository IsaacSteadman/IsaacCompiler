# only_tn means assume Only type_name
def is_type_name_part(s: str, context: "CompileContext", only_tn: bool = False) -> bool:
    if s in TYPE_WORDS or s in META_TYPE_WORDS:
        return True
    elif only_tn:
        return context.type_name(s) is not None
    else:
        x = context.get(s)
        if x is None:
            return False
        return x.is_type()


from ..constants import META_TYPE_WORDS, TYPE_WORDS
from ..context.CompileContext import CompileContext