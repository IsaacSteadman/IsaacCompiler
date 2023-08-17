
def mangle_decl(name, typ, is_local, is_op_fn=False):
    """
    :param is_op_fn:
    :param str name:
    :param BaseType typ:
    :param bool is_local:
    :rtype: str
    """
    name = name.rsplit("::", 1)
    if is_local:
        lst_rtn, name = ([], name[0]) if len(name) <= 1 else (list(map(int, name[0].split("::"))), name[1])
        return "$" + "?".join(map(str, lst_rtn)) + "?" + typ.to_mangle_str(False) + name
    else:
        lst_rtn, name = ([], name[0]) if len(name) <= 1 else (name[0].split("::"), name[1])
        if is_op_fn:
            raise NotImplementedError("Operater mangling is not implemented")
            # TODO replace `OP_MANGLE` with a mapping from operator name and type to its mangled name
            # return "@".join(lst_rtn) + "$" + self.typ.ToMangleStr(True) + `OP_MANGLE` + "_g"
        else:
            return "@".join(lst_rtn) + "?" + typ.to_mangle_str(True) + name

