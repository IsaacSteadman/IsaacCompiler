from enum import Enum
from typing import Dict, Optional, Set
from .BaseCmplObj import BaseCmplObj


class CompileObjectType(Enum):
    GLOBAL = 0  # initialization of a global
    FUNCTION = 1  # definition of a function


class Compilation(BaseCmplObj):
    def __init__(self, keep_local_syms: bool):
        super(Compilation, self).__init__()
        self.keep_local_syms = keep_local_syms
        self.objects: Dict[str, CompileObject] = {}
        self.code_segment_end = None
        self.data_segment_start = None

    def spawn_compile_object(
        self, typ: CompileObjectType, name: str
    ) -> "CompileObject":
        rtn = CompileObject(typ, name)
        self.objects[name] = rtn
        return rtn.set_parent(self)

    def merge_all(
        self,
        link_opts: "LinkerOptions",
        extern: Optional[Dict[str, "CompileObject"]] = None,
        excl: Optional[Set[str]] = None,
    ):
        # memory Layout
        #   FUNCTION
        #   GLOBALS
        #   STRINGS
        funcs = []
        globs = []
        for k in sorted(self.objects):
            cur = self.objects[k]
            if cur.typ == CompileObjectType.FUNCTION:
                funcs.append(cur)
            elif cur.typ == CompileObjectType.GLOBAL:
                globs.append(cur)
            else:
                raise TypeError(
                    "Unexpected Compile Object name = %r Type = %u"
                    % (cur.name, cur.typ)
                )
        if extern is not None:
            for k in sorted(extern):
                cur = extern[k]
                if cur.typ == CompileObjectType.FUNCTION:
                    funcs.append(cur)
                elif cur.typ == CompileObjectType.GLOBAL:
                    globs.append(cur)
                else:
                    raise TypeError(
                        "Unexpected Compile Object name = %r Type = %u"
                        % (cur.name, cur.typ)
                    )
        for lst_objects in [funcs, globs]:
            for cur in lst_objects:
                assert isinstance(cur, CompileObject)
                if excl is not None and cur.name in excl:
                    continue
                obj_lnk = self.get_link(cur.name)
                if obj_lnk.src is not None:
                    raise NameError(
                        "Redefinition of name = '%s' is not allowed" % cur.name
                    )
                mem_off = len(self.memory)
                self.memory.extend(cur.memory)
                obj_lnk.src = mem_off
                for k1 in cur.string_pool:
                    cur1 = cur.string_pool[k1]
                    lnk = self.get_string_link(k1)
                    lnk.merge_from(cur1, mem_off)
                for k1 in cur.linkages:
                    cur1 = cur.linkages[k1]
                    lnk = self.get_link(k1)
                    lnk.merge_from(cur1, mem_off)
            if lst_objects is funcs:
                self.code_segment_end = len(self.memory)
                dsa = link_opts.data_seg_align
                if dsa > 1:
                    length = len(self.memory)
                    self.memory.extend([0] * (dsa - length % dsa))
                self.data_segment_start = len(self.memory)
        for k in self.string_pool:
            assert isinstance(k, bytes)
            cur = self.string_pool[k]
            assert cur.src is None
            mem_off = len(self.memory)
            self.memory.extend(k)
            cur.src = mem_off

    def link_all(self):
        rtn = True
        for k in self.linkages:
            lnk = self.linkages[k]
            assert isinstance(lnk, Linkage)
            if lnk.src is None:
                fmt = (
                    "Unresolved "
                    + ("External " if lnk.is_extern else "")
                    + "Symbol: "
                    + k
                )
                if len(lnk.lst_tgt):
                    rtn = False
                    print("ERROR: " + fmt)
                else:
                    print("WARN_: " + fmt)
            else:
                lnk.fill_all(self.memory)
        for k in self.string_pool:
            lnk = self.string_pool[k]
            assert isinstance(lnk, Linkage)
            if lnk.src is None:
                fmt = (
                    "Unresolved "
                    + ("External " if lnk.is_extern else "")
                    + "Symbol: <bytes %r>" % k
                )
                if len(lnk.lst_tgt):
                    rtn = False
                    print("ERROR: " + fmt)
                else:
                    print("WARN_: " + fmt)
            else:
                lnk.fill_all(self.memory)
        return rtn


from .CompileObject import CompileObject
from .Linkage import Linkage
from .LinkerOptions import LinkerOptions
