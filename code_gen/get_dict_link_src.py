from typing import Dict


def get_dict_link_src(cmpl_obj: "BaseCmplObj") -> Dict[int, str]:
    rtn = {}
    for k in cmpl_obj.linkages:
        lnk = cmpl_obj.linkages[k]
        assert isinstance(lnk, Linkage)
        if lnk.src is not None:
            rtn[lnk.src] = k
    for k in cmpl_obj.string_pool:
        lnk = cmpl_obj.string_pool[k]
        assert isinstance(lnk, Linkage)
        if lnk.src is not None:
            rtn[lnk.src] = "<bytes %r>" % k
    return rtn


from .BaseCmplObj import BaseCmplObj
from .Linkage import Linkage
