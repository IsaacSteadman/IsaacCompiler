


class ExprLocalVars(object):
    """
    :type bp_off: int
    :type vars: list[(LocalRef, BaseType)]
    """
    def __init__(self, cmpl_data):
        """
        :param LocalCompileData cmpl_data:
        """
        self.bp_off = cmpl_data.bp_off
        self.vars = []

    def add_local(self, typ):
        """
        :param BaseType typ:
        :rtype: int
        """
        rtn = len(self.vars)
        sz_var = size_of(typ, False)
        self.vars.append((LocalRef.from_bp_off_pre_inc(self.bp_off, sz_var), typ))
        return rtn

    def merge(self, other):
        """
        :param ExprLocalVars other:
        :rtype: (ExprLocalVars, int)
        """