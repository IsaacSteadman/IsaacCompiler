from typing import Dict, Tuple


class StackDict(object):
    def __init__(self, base):
        self.base = base
        self.stack = []
        self.data = {}

    def __getitem__(self, key):
        try:
            lst = self.data[key]
            return self.stack[lst[-1]]
        except KeyError:
            return self.base[key]

    def __setitem__(self, key, v):
        lst = self.data.setdefault(key, [])
        lst.append(len(self.stack))
        self.stack.append(v)

    def __delitem__(self, key):
        lst = self.data[key]
        if len(lst) == 0:
            del self.data[key]
            lst = self.data[key]
        elif lst[-1] + 1 < len(self.stack):
            raise KeyError("Cannot delete item that is not at top of stack: key = %s" % repr(key))
        else:
            self.stack.pop()
            lst.pop()
        if len(lst) == 0:
            del self.data[key]

    def top_item(self):
        return self.stack[-1]

    def __contains__(self, key):
        return key in self.data or key in self.base


def assemble(cmpl_unit: "BaseCmplObj", rel_bp_names: Dict[str, Tuple[int, int]], str_asm: str) -> Dict[str, "Linkage"]:
    """
    rel_bp_names: a dictionary mapping variable names to 2-tuples of (base pointer offset, variable size)
    """
    lines = str_asm.split("\n")
    lines = [remove_comment_asm(line) for line in lines]
    code_links = {}
    local_vars = StackDict(rel_bp_names)
    for c, Line in enumerate(lines):
        try:
            if len(Line) == 0:
                continue
            part = ["", Line]
            while len(part[0]) == 0 and len(part[-1]) > 0:
                part = part[-1].split(" ", 1)
            if not len(part[0]):
                continue
            if len(part) > 1 and len(part[1]) > 0 and not part[1].isspace():
                raise SyntaxError("Only one item per line")
            if part[0][0].isdigit():
                num, sign, sz_cls, is_float, end = parse_number(part[0])
                cmpl_unit.memory.extend([
                    BC_LOAD, BCR_ABS_C | (sz_cls << 5)])
                if is_float:
                    if sz_cls == 2:
                        cmpl_unit.memory.extend(float_t.pack(num))
                    elif sz_cls == 3:
                        cmpl_unit.memory.extend(double_t.pack(num))
                else:
                    cmpl_unit.memory.extend(sz_cls_align_long(num, sign, sz_cls))
            elif "*" in part[0]:  # pointer
                names = part[0].split("*", 1)
                name = names[1]
                is_code = False
                if name.startswith(":"):
                    name = name[1:]
                    is_code = True
                is_rel = None
                is_l_rel = None
                is_global = None
                lnk_rel = None
                rel_spec = None
                for Ch in names[0]:
                    # rel/abs:
                    #   r means result relative (to ip for global/code, to bp for local)
                    #     (can have relspec if global/code)
                    #   a means result absolute
                    #   R means link relative (to ip for global/code, to bp for local)
                    #   A means link absolute (not supported for local)
                    if rel_spec is not None:
                        assert isinstance(rel_spec, str)
                        if Ch.lower() == "]":
                            lnk_rel = rel_spec
                            rel_spec = None
                            continue
                        rel_spec += Ch
                    elif Ch == "[" and lnk_rel is None and is_rel:
                        rel_spec = ""
                    elif Ch in "ra":
                        if is_rel is None:
                            is_rel = (Ch == 'r')
                        else:
                            raise SyntaxError("Cannot specify 'r' or 'a' more than once")
                    elif Ch in "RA":
                        if is_l_rel is None:
                            is_l_rel = Ch == 'R'
                        else:
                            raise SyntaxError("Cannot specify 'R' or 'A' more than once")
                    elif Ch in "gGlL":
                        if is_global is None:
                            is_global = Ch.lower() == 'g'
                        else:
                            raise SyntaxError("Cannot specify 'g' or 'l' more than once")
                    else:
                        raise SyntaxError("unrecognized specifier: '%s'" % Ch)
                if rel_spec is not None:
                    raise SyntaxError("expected ']' to terminate relspec after '['")
                if is_global is None:
                    is_global = False
                if is_l_rel is None:
                    is_l_rel = True
                if is_rel is None:
                    is_rel = False
                if lnk_rel is not None:
                    raise SyntaxError("Cannot use rel_spec right now")
                if is_global or is_code:
                    lnk = None if is_code else cmpl_unit.get_link(name)
                    if lnk is None:
                        lnk = code_links.get(name, None)
                        if lnk is None:
                            lnk = code_links[name] = Linkage()
                    start_pos = len(cmpl_unit.memory)
                    cmpl_unit.memory.extend([
                        BC_LOAD, BCR_SZ_8, 0, 0, 0, 0, 0, 0, 0, 0])
                    lnk_ref = LinkRef(start_pos + 2)
                    if is_l_rel:
                        lnk_ref.rel_off = 0
                        cmpl_unit.memory[start_pos + 1] |= BCR_ABS_C if is_rel else BCR_EA_R_IP
                    else:
                        if is_rel:
                            raise SyntaxError("Relative result linking is not allowed")
                            # CmplUnit.memory.extend([BC_LOAD, BCR_EA_R_IP | BCR_SZ_1, 1, BC_SUB8])
                        else:
                            cmpl_unit.memory[start_pos + 1] |= BCR_ABS_C
                    lnk.lst_tgt.append(lnk_ref)
                else:
                    if not is_l_rel:
                        raise SyntaxError("cannot use non-relative link for local")
                    off = local_vars[name][0]
                    if is_rel:
                        byts, sz_cls = get_sz_cls_align_long(off, True)
                        cmpl_unit.memory.extend([
                            BC_LOAD, BCR_ABS_C | (sz_cls << 5)])
                        cmpl_unit.memory.extend(byts)
                    else:
                        byts = sz_cls_align_long(off, True, 3)
                        cmpl_unit.memory.extend([
                            BC_LOAD, BCR_ABS_C | BCR_SZ_8])
                        cmpl_unit.memory.extend(byts)
                        cmpl_unit.memory.extend([
                            BC_LOAD, BCR_REG_BP | BCR_SZ_8, BC_ADD8])
            elif part[0].startswith(":"):  # code-pointer declaration
                name = part[0][1:]
                lnk = code_links.get(name, None)
                if lnk is None:
                    lnk = code_links[name] = Linkage()
                lnk.src = len(cmpl_unit.memory)
                # raise NotImplementedError("Code-Pointer is Not Implemented")
            elif part[0].startswith("~+"):  # local variable decl
                names = part[0][2:].split(",")
                if len(names) != 2:
                    raise SyntaxError("In order to declare a variable, size or an initial value must be provided")
                name = names[0]
                top = (0, 0)
                try:
                    top = local_vars.top_item()
                except IndexError:
                    pass
                size = int(names[1]) if names[1].isdigit() else None
                if size is not None:
                    cmpl_unit.memory.extend([
                        BC_LOAD, BCR_ABS_C])
                    byts, sz_cls = get_sz_cls_align_long(size, False, 3)
                    cmpl_unit.memory[-1] |= sz_cls << 5
                    cmpl_unit.memory.extend(byts)
                    cmpl_unit.memory.extend([
                        BC_ADD_SP1 + sz_cls])
                else:
                    num, sign, sz_cls, is_float, end = parse_number(names[1])
                    cmpl_unit.memory.extend([
                        BC_LOAD, BCR_ABS_C | (sz_cls << 5)])
                    if is_float:
                        if sz_cls == 2:
                            cmpl_unit.memory.extend(float_t.pack(num))
                        elif sz_cls == 3:
                            cmpl_unit.memory.extend(double_t.pack(num))
                    else:
                        cmpl_unit.memory.extend(sz_cls_align_long(num, sign, sz_cls))
                    size = 1 << sz_cls
                off = top[0] - size
                local_vars[name] = (off, size)
            elif part[0].startswith("~-"):  # local variable undecl
                name = part[0][2:]
                del local_vars[name]
            elif "@" in part[0]:  # value @ pointer
                names = part[0].split("@", 1)
                is_global = names[0].startswith("g")
                if is_global:
                    """lnk = CmplUnit.GetLink(names[1])
                    CmplUnit.memory.extend([
                        BC_LOAD, BCR_ABS | BCR_SZ_8, 0, 0, 0, 0, 0, 0, 0, 0
                    ])
                    lnk.lst_tgt.append(LinkRef(len(CmplUnit.memory) - 8, 1))"""
                    raise NotImplementedError("Dereferencing a global is Not Implemented")
                else:
                    var = local_vars[names[1]]
                    off = var[0]
                    sz = var[1]
                    sz_cls_1 = [1, 2, 4, 8].index(sz)
                    byts, sz_cls = get_sz_cls_align_long(off, True)
                    cmpl_unit.memory.extend([
                        BC_LOAD, (BCR_R_BP1 + sz_cls) | (sz_cls_1 << 5)])
                    cmpl_unit.memory.extend(byts)
            else:
                cur_part = part[0]
                cur_def_code_type = "BCR"
                while len(cur_part):
                    byts = None
                    if cur_part[0].isdigit():
                        num, sign, sz_cls, is_float, end = parse_number(cur_part, True)
                        if is_float:
                            if sz_cls == 2:
                                byts = float_t.pack(num)
                            elif sz_cls == 3:
                                byts = double_t.pack(num)
                        else:
                            byts = sz_cls_align_long(num, sign, sz_cls)
                    else:
                        byts, end, last_instr, prev_code_type = parse_aux_codes(cur_part, cur_def_code_type)
                        if last_instr is None:
                            cur_def_code_type = "BCR"
                        elif prev_code_type is None:
                            if last_instr == BC_LOAD:
                                cur_def_code_type = "BCR"
                            elif last_instr == BC_CONV:
                                cur_def_code_type = "BCC"
                            elif last_instr == BC_SWAP:
                                cur_def_code_type = "BCS"
                            elif last_instr == BC_RET_E:
                                cur_def_code_type = "BCRE"
                            elif last_instr == BC_CALL_E:
                                cur_def_code_type = "BCCE"
                            else:
                                cur_def_code_type = "BCR"
                        elif prev_code_type == "BCR" and last_instr & BCR_TYP_MASK == BCR_SYSREG:
                            cur_def_code_type = "SVSR"
                    if byts is None:
                        raise SyntaxError("No bytes gotten")
                    else:
                        cmpl_unit.memory.extend(byts)
                    cur_part = cur_part[end:]
                    if len(cur_part):
                        if cur_part[0] == "-":
                            cur_part = cur_part[1:]
                        else:
                            raise SyntaxError("Expected '-' to separate tokens")
        except (ValueError, SyntaxError, TypeError, LookupError, EnvironmentError, NotImplementedError) as Exc:
            if not Exc.args:
                Exc.args = ("",)
            Exc.args = Exc.args + ("At Line %u" % c,)
            raise
    out_code_links = {}
    for k in code_links:
        lnk = code_links[k]
        assert isinstance(lnk, Linkage)
        if lnk.src is None:
            print("ERROR: unlinkable CodeLink (no-decl): %s" % k)
            out_code_links[k] = lnk
        elif len(lnk.lst_tgt) == 0:
            print("WARN: unused CodeLink: %s" % k)
        else:
            lst_failed = []
            for Ref in lnk.lst_tgt:
                assert isinstance(Ref, LinkRef)
                if not Ref.try_fill_ref_rel(cmpl_unit.memory, lnk.src):
                    print("WARN: Linker Failed to link %s into location 0x%016X (%u)" % (k, Ref.pos, Ref.pos))
                    lst_failed.append(Ref)
            if len(lst_failed):
                out_code_links[k] = Linkage()
                out_code_links[k].lst_tgt.extend(lst_failed)
                out_code_links[k].src = lnk.src
    return out_code_links


from ...StackVM.PyStackVM import BCR_ABS_C, BCR_EA_R_IP, BCR_REG_BP, BCR_R_BP1,\
    BCR_SYSREG, BCR_SZ_8, BCR_TYP_MASK, BC_ADD8, BC_ADD_SP1, BC_CALL_E,\
    BC_CONV, BC_LOAD, BC_RET_E, BC_SWAP, double_t, float_t
from ..BaseCmplObj import BaseCmplObj
from ..LinkRef import LinkRef
from ..Linkage import Linkage
from .get_sz_cls_align_long import get_sz_cls_align_long
from .parse_aux_codes import parse_aux_codes
from .parse_number import parse_number
from .remove_comment_asm import remove_comment_asm
from .sz_cls_align_long import sz_cls_align_long