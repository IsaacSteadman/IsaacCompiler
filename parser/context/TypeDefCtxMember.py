class TypeDefCtxMember(ContextMember):
    def __init__(self, name, parent, typ):
        """

        :param str name:
        :param CompileContext|None parent:
        :param BaseType typ:
        """
        super(TypeDefCtxMember, self).__init__(name, parent)
        self.typ = typ

    def is_type(self):
        return True

    def get_underlying_type(self):
        return self.typ
