def get_dict_links(cmpl_obj: "BaseCmplObj"):
    rtn = {}
    for k in cmpl_obj.linkages:
        lnk = cmpl_obj.linkages[k]
        for lnk_ref in lnk.lst_tgt:
            assert isinstance(lnk_ref, LinkRef)
            rtn[lnk_ref.pos] = (k, True)
    for k in cmpl_obj.string_pool:
        lnk = cmpl_obj.string_pool[k]
        for lnk_ref in lnk.lst_tgt:
            assert isinstance(lnk_ref, LinkRef)
            rtn[lnk_ref.pos] = ("<bytes %r>" % k, True)
    return rtn


from .BaseCmplObj import BaseCmplObj
from .LinkRef import LinkRef
