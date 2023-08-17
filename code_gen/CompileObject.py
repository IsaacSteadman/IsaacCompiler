from .BaseCmplObj import BaseCmplObj
from .Linkage import Linkage


class CompileObject(BaseCmplObj):
    def __init__(self, typ, name):
        super(CompileObject, self).__init__()
        self.typ = typ
        self.name = name
        self.parent = None
        self.local_links = {}

    def get_local_link(self, name):
        """
        :param str name:
        :rtype: Linkage
        """
        if name not in self.local_links:
            self.local_links[name] = Linkage()
        return self.local_links[name]

    def set_parent(self, parent):
        """
        :param Compilation parent:
        """
        self.parent = parent
        return self

