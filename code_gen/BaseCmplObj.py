from typing import Dict, Optional


class BaseCmplObj(object):
    def __init__(self):
        self.memory = bytearray()
        self.linkages: Dict[str, Linkage] = {}
        self.string_pool: Dict[bytes, Linkage] = {}
        self.data_segment_start: Optional[int] = None
        self.code_segment_end: Optional[int] = None

    def get_string_link(self, byts: bytes):
        link = self.string_pool.get(byts, None)
        if link is None:
            link = self.string_pool[byts] = Linkage()
        return link

    def get_link(self, name: str):
        link = self.linkages.get(name, None)
        if link is None:
            link = self.linkages[name] = Linkage()
        return link


from .Linkage import Linkage