

def is_array_type(typ):
    """
    :param BaseType typ:
    :rtype: bool
    """
    if typ.type_class_id == TypeClass.QUAL:
        assert isinstance(typ, QualType)
        return typ.qual_id == QualType.QUAL_ARR
    return False