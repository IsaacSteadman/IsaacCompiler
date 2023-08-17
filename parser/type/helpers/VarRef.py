
# Top Of Stack uninitialized
VAR_REF_TOS_NAMED = 0  # has a name


# references a link to preallocated memory
VAR_REF_LNK_PREALLOC = 1


class VarRef(object):
    ref_type = None


class VarRefTosNamed(VarRef):
    ref_type = VAR_REF_TOS_NAMED

    def __init__(self, ctx_var):
        """
        :param ContextVariable|None ctx_var:
        """
        self.ctx_var = ctx_var


class VarRefLnkPrealloc(VarRef):
    ref_type = VAR_REF_LNK_PREALLOC

    def __init__(self, lnk):
        """
        :param BaseLink lnk:
        """
        self.lnk = lnk