from .BaseCmplObj import BaseCmplObj
from .Linkage import Linkage


class CompileObject(BaseCmplObj):
    def __init__(self, typ, name):
        super(CompileObject, self).__init__()
        self.typ = typ
        self.name = name
        self.parent = None
        self.local_links = {}
        self.alignment = 1
        self.section_name = None
        self.debug_source_file = None
        self.debug_line_records = []
        self.debug_frame_size = 0
        self.debug_return_address_offset = 0
        self.debug_previous_bp_offset = 8

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

    def add_debug_line(self, offset, source_file, line, column):
        if source_file is None or line < 0 or column < 0:
            return
        self.debug_line_records.append((offset, source_file, line, column))
