def get_sh_fn_type(typ: "BaseType"):
    return QualType(
        QualType.QUAL_FN,
        typ,
        [typ, PrimitiveType.from_type_code(PrimitiveTypeId.INT_C, 1)],
    )


from .PrimitiveType import PrimitiveType, PrimitiveTypeId
from .QualType import QualType
from .BaseType import BaseType
