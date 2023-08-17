
def get_ellipses_conv_expr(expr):
    """
    :param BaseExpr expr:
    :rtype: (BaseExpr, int)|None
    """
    src_pt = get_base_prim_type(expr.t_anot)
    to_type = expr.t_anot
    src_vt = src_pt
    if src_pt.type_class_id == TypeClass.QUAL:
        assert isinstance(src_pt, QualType)
        if src_pt.qual_id == QualType.QUAL_REF:
            src_vt = src_pt.tgt_type
    if src_vt.type_class_id == TypeClass.QUAL:
        assert isinstance(src_vt, QualType)
        if src_vt.qual_id == QualType.QUAL_FN:
            to_type = QualType(QualType.QUAL_PTR, src_vt)
    elif src_vt.type_class_id == TypeClass.PRIM:
        assert isinstance(src_vt, PrimitiveType)
        if src_vt.typ in INT_TYPE_CODES:
            if src_vt.size < SIZE_SIGN_MAP[PrimitiveTypeId.INT_I][0]:
                to_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_I, -1 if src_vt.sign else 1)
        elif src_vt.typ in FLT_TYPE_CODES:
            if src_vt.size < SIZE_SIGN_MAP[PrimitiveTypeId.FLT_D][0]:
                to_type = PrimitiveType.from_type_code(PrimitiveTypeId.FLT_D)
        else:
            raise ValueError("Unexpected Primitive Type = %r" % src_vt)
    else:
        raise ValueError("Unexpected Type = %r" % src_vt)
    rtn = expr
    if to_type is not expr.t_anot:
        rtn = CastOpExpr(to_type, expr, CastType.IMPLICIT)
    return rtn, 6

