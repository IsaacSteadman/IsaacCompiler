def compile_conv_general(cmpl_obj, conv_expr, context, cmpl_data=None, temp_links=None):
    """
    :param BaseCmplObj cmpl_obj:
    :param CastOpExpr conv_expr:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    :param list[(BaseType,BaseLink)]|None temp_links:
    """
    expr = conv_expr.expr
    typ = conv_expr.type_name
    src_pt, src_vt, is_src_ref = get_tgt_ref_type(expr.t_anot)
    tgt_pt, tgt_vt, is_tgt_ref = get_tgt_ref_type(typ)
    owns_temps = temp_links is None
    sz = 0
    temps_off = conv_expr.temps_off
    if owns_temps:
        temp_links = setup_temp_links(cmpl_obj, conv_expr, context, cmpl_data)
    if compare_no_cvr(src_vt, tgt_vt):
        if is_src_ref and is_tgt_ref:  # do nothing, just pass the reference along
            assert compare_no_cvr(src_vt, tgt_vt)
            sz = compile_expr(cmpl_obj, expr, context, cmpl_data, tgt_pt, temp_links)
            assert sz == 8
        elif is_tgt_ref:  # DO temporary materialization
            assert not is_src_ref
            assert len(temp_links) == len(conv_expr.temps), "temp_links = %r, ConvExpr.temps = %r" % (
                temp_links, conv_expr.temps
            )
            temp_type, temp_link = temp_links[temps_off]
            temp_type.compile_var_init(cmpl_obj, [expr], context, VarRefLnkPrealloc(temp_link), cmpl_data, temp_links)
            temp_link.emit_lea(cmpl_obj.memory)
            sz = 8
        elif is_src_ref:  # Do argument initialization given a reference
            sz = tgt_pt.compile_var_init(cmpl_obj, [expr], context, VarRefTosNamed(None), cmpl_data, temp_links)
        else:  # Do argument initialization given a value
            # for now do nothing (the source instance is the target instance)
            # TODO: maybe need to change this?
            sz = compile_expr(cmpl_obj, expr, context, cmpl_data, tgt_pt, temp_links)
    else:
        if is_src_ref and is_tgt_ref:  # do nothing, just pass the reference along
            raise TypeError("cannot do reference to reference cast")
        elif is_tgt_ref:  # DO temporary materialization
            raise TypeError("cannot do temporary materialization passing the wrong type of argument")
        elif is_src_ref:  # Do argument initialization given a reference
            if src_vt.type_class_id == TypeClass.QUAL and tgt_vt.type_class_id == TypeClass.QUAL:
                assert isinstance(src_vt, QualType)
                assert isinstance(tgt_vt, QualType)
                if tgt_vt.qual_id == QualType.QUAL_PTR:
                    if src_vt.qual_id == QualType.QUAL_ARR:
                        if src_vt.ext_inf is not None and compare_no_cvr(src_vt.tgt_type, tgt_vt.tgt_type):
                            sz = compile_expr(cmpl_obj, expr, context, cmpl_data, None, temp_links)
                            assert sz == 8
                    elif src_vt.qual_id == QualType.QUAL_FN:
                        if compare_no_cvr(src_vt, tgt_vt.tgt_type):
                            sz = compile_expr(cmpl_obj, expr, context, cmpl_data, None, temp_links)
                            assert sz == 8
            err0 = "cannot do argument initialization given a reference to a different type expr.t_anot = %s, Type = %s"
            if sz == 0:
                raise TypeError(err0 % (get_user_str_from_type(expr.t_anot), get_user_str_from_type(typ)))
        else:  # Do argument initialization given a value
            # for now do nothing (the source instance is the target instance)
            sz = typ.compile_conv(cmpl_obj, expr, context, cmpl_data, temp_links)
    if owns_temps:
        tear_down_temp_links(cmpl_obj, temp_links, conv_expr, context, cmpl_data)
    return sz
