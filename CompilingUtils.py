from typing import Any, Callable, Dict, Literal, Optional, Tuple, TypeVar, Union
'''from PyIsaacUtils.AlgoUtils import bisect_search_base
from StackVM.PyStackVM import BC_ADD8, BC_ADD_SP1, BC_CALL_E, BC_CONV, BC_GE0, BC_INT, BC_LOAD, BC_LSHIFT1, BC_NOP,\
    BC_RET_E, BC_RET_N2, BC_RST_SP1, BC_STOR, BC_SWAP, BC_SYSRET, BCC_I_MASK, BCC_O_MASK, BCCE_N_REL, BCCE_SYSCALL,\
    BCR_ABS_A4, BCR_ABS_A8, BCR_ABS_C, BCR_ABS_S8, BCR_EA_R_IP, BCR_R_BP1, BCR_R_BP_MASK, BCR_R_BP_VAL, BCR_REG_BP,\
    BCR_RES, BCR_SYSREG, BCR_SZ_8, BCR_SZ_MASK, BCR_TYP_MASK, BCRE_RES_SZ_MASK, BCRE_RST_SP_SZ_MASK, BCRE_SYS,\
    BCS_SZ8_B, BCS_SZ_A_MASK, BCS_SZ_B_MASK, MRQ_DONT_CHECK, VM_4_LVL_9_BIT, VM_DISABLED, LstStackVM_BCC_Types,\
    LstStackVM_BCR_Types, LstStackVM_BCS_Types, LstStackVM_Codes, LstStackVM_sysregs, StackVM_BCC_Codes,\
    StackVM_BCCE_Codes, StackVM_BCR_Codes, StackVM_BCRE_Codes, StackVM_BCS_Codes, StackVM_Codes, StackVM_SVSR_Codes,\
    float_t, double_t'''

from PyIsaacUtils.AlgoUtils import *

from StackVM.PyStackVM import *


T = TypeVar("T")


def get_sz_cls_align_long(long: int, signed: bool, max_sz_cls: Literal[0, 1, 2, 3] = 3):
    if long < 0:
        if signed:
            long = abs(long) - 1
        else:
            raise ValueError("Long < 0 when bool(Signed) == True ")
    else:
        signed = False
    res = bytearray(1)
    c = 0
    sz_cls = 0
    while long > 0:
        if c >= len(res):
            res.extend([0] * len(res))
            sz_cls += 1
            if sz_cls > max_sz_cls:
                raise ValueError("Long is Too big")
        res[c] = long & 0xFF
        long >>= 8
    if signed:
        if 0x80 & res[-1]:
            res.extend([0] * len(res))
            sz_cls += 1
            if sz_cls > max_sz_cls:
                raise ValueError("Long is Too big")
        for c in range(len(res)):
            res[c] ^= 0xFF
    return res, sz_cls


def sz_cls_align_long(long, signed, sz_cls):
    if signed:
        if long < 0:
            long = abs(long) - 1
        else:
            signed = False
    rtn = bytearray(1 << sz_cls)
    for c in range(len(rtn)):
        rtn[c] = long & 0xFF
        if signed:
            rtn[c] ^= 0xFF
        long >>= 8
    return rtn


CMPL_T_GLOBAL = 0  # initialization of a global
CMPL_T_FUNCTION = 1  # definition of a function


class BaseLink(object):
    def get_offset_link(self, offset: int) -> "BaseLink":
        raise NotImplementedError("Not Implemented")

    def emit_lea(self, memory: Union[memoryview, bytearray]):
        """
        Load Effective Address
        """
        raise NotImplementedError("Not Implemented")

    def emit_load_pot(self, memory: Union[memoryview, bytearray], sz_cls: int):
        self.emit_lea(memory)
        memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])

    def emit_stor_pot(self, memory: Union[memoryview, bytearray], sz_cls: int):
        self.emit_lea(memory)
        memory.extend([
            # BC_SWAP, BCS_SZ8_B | sz_cls,  # SzCls0 does not need to be shifted as BCS_SZ_A_MASK is 0x7
            BC_STOR, BCR_ABS_S8 | (sz_cls << 5)])

    def emit_load(
            self,
            memory: bytearray,
            size: int,
            byte_copy_arg: T,
            byte_copy_intrinsic: Callable[[T, Union[memoryview, bytearray], Optional[int], bool, bool], Any]
    ):
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 3:
            sz_cls_1 = emit_load_i_const(memory, size, False)
            memory.extend([BC_ADD_SP1 + sz_cls_1])
            self.emit_lea(memory)
            # using @@ByteCopyFn1
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, True)
            sz_cls_1 = emit_load_i_const(memory, stack_left, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_load_pot(memory, sz_cls_0)

    def emit_stor(
            self,
            memory: bytearray,
            size: int,
            byte_copy_arg: T,
            byte_copy_intrinsic: Callable[[T, Union[memoryview, bytearray], Optional[int], bool, bool], Any]
    ):
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 3:
            self.emit_lea(memory)
            # using @@ByteCopyFn2
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, False)
            sz_cls_1 = emit_load_i_const(memory, stack_left + size, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_stor_pot(memory, sz_cls_0)
    # byte_copy_intrinsic
    # OutIsStack for Load, InIsStack for Stor
    #   Arg: Generic
    #   memory: bytearray
    #   size: int
    #   IsStack: bool
    #   IsLoad
    '''def EmitLoad(self, memory, size, byte_copy_arg, byte_copy_intrinsic):
        """
        :param bytearray memory:
        :param int size:
        :param T byte_copy_arg:
        :param (T, bytearray, int|None, bool, bool) -> any byte_copy_intrinsic:
        """
        raise NotImplementedError("Not Implemented")
    def EmitStor(self, memory, size, byte_copy_arg, byte_copy_intrinsic):
        """
        :param bytearray memory:
        :param int size:
        :param T byte_copy_arg:
        :param (T, bytearray, int|None, bool, bool) -> any byte_copy_intrinsic:
        """
        raise NotImplementedError("Not Implemented")'''


def get_load_i_const(num: int, sign: Optional[bool]=None, sz_cls: Optional[int]=None) -> Tuple[bytearray, int]:
    if sign is None:
        sign = num < 0
    if sz_cls is None:
        byts, sz_cls = get_sz_cls_align_long(num, sign)
    else:
        byts = sz_cls_align_long(num, sign, sz_cls)
    rtn = bytearray([
        BC_LOAD, BCR_ABS_C | (sz_cls << 5)])
    rtn.extend(byts)
    return rtn, sz_cls


def emit_load_i_const(memory: bytearray, num: int, sign: Optional[bool]=None, sz_cls: Optional[int]=None) -> int:
    byts, sz_cls = get_load_i_const(num, sign, sz_cls)
    memory.extend(byts)
    return sz_cls

# @@ByteCopyFn is (SizeL sz, void *src, void *dest) -> None
#   push order [dest] [src] [sz]

# @@ByteCopyFn1 is (SizeL sz, void *src) -> None
#   push order [src] [sz]
#    dest is implicit as (bp + 16 + 16 for arguments)

# @@ByteCopyFn2 is (SizeL sz, void *dest) -> None
#   push order [dest] [sz]
#    src is implicit as (bp + 16 + 16 for arguments)


class OffsetLocalRef(BaseLink):
    def __init__(self, parent: "LocalRef", offset: int):
        self.parent = parent
        self.offset = offset
        self.sz = parent.sz - offset

    def get_offset_link(self, offset: int) -> BaseLink:
        # TODO: Convert EmitLoad, EmitStor, EmitLEA
        return OffsetLocalRef(self.parent, self.offset + offset)

    def emit_load_pot(self, memory: bytearray, sz_cls: int):
        byts, sz_cls_r_bp = get_sz_cls_align_long(self.parent.rel_addr + self.offset, True)
        memory.extend([BC_LOAD, (BCR_R_BP1 + sz_cls_r_bp) | (sz_cls << 5)])
        memory.extend(byts)

    def emit_stor_pot(self, memory: bytearray, sz_cls: int):
        byts, sz_cls_r_bp = get_sz_cls_align_long(self.parent.rel_addr + self.offset, True)
        memory.extend([BC_STOR, (BCR_R_BP1 + sz_cls_r_bp) | (sz_cls << 5)])
        memory.extend(byts)

    def emit_lea(self, memory: bytearray):
        byts = sz_cls_align_long(self.parent.rel_addr + self.offset, True, 3)
        memory.extend([BC_LOAD, BCR_REG_BP | BCR_SZ_8, BC_LOAD, BCR_ABS_C | BCR_SZ_8])
        memory.extend(byts)
        memory.extend([BC_ADD8])


class LocalRef(BaseLink):
    @classmethod
    def from_bp_off_post_inc(cls, bp_off: int, sz: int):
        return cls(-bp_off, sz)

    @classmethod
    def from_bp_off_pre_inc(cls, bp_off: int, sz: int):
        return cls(-(bp_off + sz), sz)

    def __init__(self, rel_addr: int, sz: int):
        self.rel_addr = rel_addr
        self.sz = sz

    def get_offset_link(self, offset: int) -> BaseLink:
        return OffsetLocalRef(self, offset)

    def emit_load_pot(self, memory: bytearray, sz_cls: int):
        byts, sz_cls_r_bp = get_sz_cls_align_long(self.rel_addr, True)
        memory.extend([BC_LOAD, (BCR_R_BP1 + sz_cls_r_bp) | (sz_cls << 5)])
        memory.extend(byts)

    def emit_stor_pot(self, memory: bytearray, sz_cls: int):
        byts, sz_cls_r_bp = get_sz_cls_align_long(self.rel_addr, True)
        memory.extend([BC_STOR, (BCR_R_BP1 + sz_cls_r_bp) | (sz_cls << 5)])
        memory.extend(byts)

    def emit_lea(self, memory: bytearray):
        byts = sz_cls_align_long(self.rel_addr, True, 3)
        memory.extend([BC_LOAD, BCR_REG_BP | BCR_SZ_8, BC_LOAD, BCR_ABS_C | BCR_SZ_8])
        memory.extend(byts)
        memory.extend([BC_ADD8])


class LinkRef(object):
    def __init__(self, pos: int, rel_off: Optional[int]=None):
        self.pos = pos
        self.rel_off = rel_off

    def try_fill_ref_abs(self, memory: bytearray, abs_addr: int) -> bool:
        if self.rel_off is None:
            memory[self.pos:self.pos + 8] = sz_cls_align_long(abs_addr, False, 3)
        else:
            memory[self.pos:self.pos + 8] = sz_cls_align_long(abs_addr - (self.pos + 8 + self.rel_off), True, 3)
        return True

    def try_fill_ref_rel(self, memory: bytearray, local_abs_addr: int) -> bool:
        if self.rel_off is None:
            return False
        else:
            memory[self.pos:self.pos + 8] = sz_cls_align_long(local_abs_addr - (self.pos + 8 + self.rel_off), True, 3)
        return True

    def fill_ref(self, memory: bytearray, abs_addr: int):
        self.try_fill_ref_abs(memory, abs_addr)

    def get_new_link_off(self, mem_off: int):
        return LinkRef(self.pos + mem_off, self.rel_off)


class OffsetIndirectLink(BaseLink):
    def __init__(self, parent: "IndirectLink", offset: int):
        self.parent = parent
        self.offset = offset

    def get_offset_link(self, offset: int):
        return OffsetIndirectLink(self.parent, self.offset + offset)

    def emit_lea(self, memory: bytearray):
        self.parent.emit_lea(memory)
        emit_load_i_const(memory, self.offset, True, 3)
        memory.append(BC_ADD8)


class IndirectLink(BaseLink):
    def __init__(self, addr_link: BaseLink):
        self.addr_link = addr_link

    def get_offset_link(self, offset):
        return OffsetIndirectLink(self, offset)

    def emit_lea(self, memory: Union[memoryview, bytearray]):
        self.addr_link.emit_load(memory, 8, None, dummy_byte_copy_intrinsic)


def dummy_byte_copy_intrinsic(arg, mem, sz, b0, b1):
    raise ValueError("A Byte copy intrinsic was not provided for %r, memory(len=%u), sz=%u, b0=%r, b1=%r" % (arg, len(mem), sz, b0, b1))


class OffsetLinkage(BaseLink):
    def __init__(self, parent: "Linkage", offset: int):
        self.parent = parent
        self.offset = offset

    def get_offset_link(self, offset: int):
        return OffsetLinkage(self.parent, offset + self.offset)

    def emit_lea(self, memory: Union[memoryview, bytearray]):
        memory.extend([
            BC_LOAD, BCR_EA_R_IP | BCR_SZ_8,
            0, 0, 0, 0, 0, 0, 0, 0])
        self.parent.lst_tgt.append(LinkRef(len(memory) - 8, -self.offset))

    def emit_load(self, memory: bytearray, size: int, byte_copy_arg: T, byte_copy_intrinsic: Callable[[T, Optional[int], bool, bool], Any]):
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 3:
            sz_cls_1 = emit_load_i_const(memory, size, False)
            memory.extend([BC_ADD_SP1 + sz_cls_1])
            self.emit_lea(memory)
            # using @@ByteCopyFn1
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, True)
            sz_cls_1 = emit_load_i_const(memory, stack_left, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_load_pot(memory, sz_cls_0)

    def emit_stor(
            self,
            memory: bytearray,
            size: int,
            byte_copy_arg: T,
            byte_copy_intrinsic: Callable[[T, Union[memoryview, bytearray], Optional[int], bool, bool], Any]
    ):
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 3:
            self.emit_lea(memory)
            # using @@ByteCopyFn2
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, False)
            sz_cls_1 = emit_load_i_const(memory, stack_left + size, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_stor_pot(memory, sz_cls_0)


class Linkage(BaseLink):
    """
    :type lst_tgt: list[LinkRef]
    :type src: int|None
    :type is_extern: bool
    """
    def __init__(self):
        self.lst_tgt = []
        self.src = None
        self.is_extern = False

    def get_offset_link(self, offset):
        return OffsetLinkage(self, offset)

    def emit_load(
            self,
            memory: Union[memoryview, bytearray],
            size: int,
            byte_copy_arg: T,
            byte_copy_intrinsic: Callable[[T, Union[memoryview, bytearray], Optional[int], bool, bool], Any]
    ):
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 3:
            sz_cls_1 = emit_load_i_const(memory, size, False)
            memory.extend([BC_ADD_SP1 + sz_cls_1])
            self.emit_lea(memory)
            # using @@ByteCopyFn1
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, True)
            sz_cls_1 = emit_load_i_const(memory, stack_left, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_load_pot(memory, sz_cls_0)

    def emit_stor(
            self,
            memory: Union[memoryview, bytearray],
            size: int,
            byte_copy_arg: T,
            byte_copy_intrinsic: Callable[[T, Union[bytearray,memoryview], Optional[int], bool, bool], Any]
    ):
        sz_cls_0 = size.bit_length() - 1
        if 1 << sz_cls_0 != size or sz_cls_0 > 3:
            self.emit_lea(memory)
            # using @@ByteCopyFn2
            stack_left = byte_copy_intrinsic(byte_copy_arg, memory, size, True, False)
            sz_cls_1 = emit_load_i_const(memory, stack_left + size, False)
            memory.extend([BC_RST_SP1 + sz_cls_1])
        else:
            self.emit_stor_pot(memory, sz_cls_0)

    def emit_lea(self, memory: Union[memoryview, bytearray]):
        memory.extend([
            BC_LOAD, BCR_EA_R_IP | BCR_SZ_8,
            0, 0, 0, 0, 0, 0, 0, 0])
        self.lst_tgt.append(LinkRef(len(memory) - 8, 0))

    def fill_all(self, memory: Union[memoryview, bytearray]):
        assert self.src is not None
        assert not self.is_extern
        for Tgt in self.lst_tgt:
            assert isinstance(Tgt, LinkRef)
            Tgt.fill_ref(memory, self.src)

    def merge_from(self, other, mem_off):
        if (self.src is not None) and (other.src is not None):
            raise NameError("Link Error on merge: source ('src') is defined in 'self' and 'other'")
        if other.src is not None:
            self.src = other.src + mem_off
        start = len(self.lst_tgt)
        self.lst_tgt.extend([None] * len(other.lst_tgt))
        for c in range(start, len(self.lst_tgt)):
            a = other.lst_tgt[c - start]
            assert isinstance(a, LinkRef)
            self.lst_tgt[c] = a.get_new_link_off(mem_off)


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


LNK_OPT_ALL = 3  # Linker option: optimize all imports
LNK_RUN_STANDALONE = 1


class LinkerOptions(object):
    __slots__ = ["optimize", "data_seg_align", "extern_deps", "run_method"]

    def __init__(
            self,
            optimize: int = LNK_OPT_ALL,
            data_seg_align: int = 1,
            extern_deps: Optional[Dict[str,BaseCmplObj]] = None,
            run_method: int = LNK_RUN_STANDALONE
    ):
        self.optimize = optimize
        self.data_seg_align = data_seg_align
        self.extern_deps = extern_deps
        self.run_method = run_method


class CompilerOptions(object):
    __slots__ = ["link_opts", "merge_and_link", "keep_local_syms"]

    def __init__(self, link_opts: LinkerOptions, merge_and_link: bool = True, keep_local_syms: bool = False):
        self.link_opts = link_opts
        self.merge_and_link = merge_and_link
        self.keep_local_syms = keep_local_syms


class Compilation(BaseCmplObj):
    """
    :type objects: dict[str, CompileObject]
    """
    def __init__(self, keep_local_syms: bool):
        super(Compilation, self).__init__()
        self.keep_local_syms = keep_local_syms
        self.objects: Dict[str, CompileObject] = {}
        self.code_segment_end = None
        self.data_segment_start = None

    def spawn_compile_object(self, typ, name):
        rtn = CompileObject(typ, name)
        self.objects[name] = rtn
        return rtn.set_parent(self)

    def merge_all(self, link_opts, extern=None, excl=None):
        """
        :param LinkerOptions link_opts:
        :param dict[str,CompileObject]|None extern:
        :param set[str]|None excl:
        """

        # memory Layout
        #   FUNCTION
        #   GLOBALS
        #   STRINGS
        funcs = []
        globs = []
        for k in sorted(self.objects):
            cur = self.objects[k]
            if cur.typ == CMPL_T_FUNCTION:
                funcs.append(cur)
            elif cur.typ == CMPL_T_GLOBAL:
                globs.append(cur)
            else:
                raise TypeError("Unexpected Compile Object name = %r Type = %u" % (cur.name, cur.typ))
        if extern is not None:
            for k in sorted(extern):
                cur = extern[k]
                if cur.typ == CMPL_T_FUNCTION:
                    funcs.append(cur)
                elif cur.typ == CMPL_T_GLOBAL:
                    globs.append(cur)
                else:
                    raise TypeError("Unexpected Compile Object name = %r Type = %u" % (cur.name, cur.typ))
        for lst_objects in [funcs, globs]:
            for cur in lst_objects:
                assert isinstance(cur, CompileObject)
                if excl is not None and cur.name in excl:
                    continue
                obj_lnk = self.get_link(cur.name)
                if obj_lnk.src is not None:
                    raise NameError("Redefinition of name = '%s' is not allowed" % cur.name)
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
                fmt = "Unresolved " + ("External " if lnk.is_extern else "") + "Symbol: " + k
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
                fmt = "Unresolved " + ("External " if lnk.is_extern else "") + "Symbol: <bytes %r>" % k
                if len(lnk.lst_tgt):
                    rtn = False
                    print("ERROR: " + fmt)
                else:
                    print("WARN_: " + fmt)
            else:
                lnk.fill_all(self.memory)
        return rtn


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


def parse_number(part, parens=False):
    """
    :param str part:
    :param bool parens:
    :rtype: (float|int, bool, int, bool, int)
    """
    if not part[0].isdigit():
        raise SyntaxError("expected number, got '%s'" % part)
    c = 1
    while part[c].isdigit() and c < len(part):
        c += 1
    if c >= len(part):
        raise SyntaxError("Expected character to terminate size specifier for number")
    sign = part[c].isupper()
    typ = part[c].lower()
    map_int_base = {"d": 10, "o": 8, "x": 16, "b": 2}
    n_bytes = int(part[0:c])
    sz_cls = n_bytes.bit_length() - 1
    if 1 << sz_cls != n_bytes or sz_cls > 7:
        raise SyntaxError("Expected a power of 2 byte size specifier that satisfies size <= 128")
    c += 1
    base = map_int_base.get(typ, None)
    end = len(part)
    if typ in map_int_base:
        if sz_cls > 3:
            raise SyntaxError("integer literal must be 1, 2, 4 or 8 bytes. got %u" % n_bytes)
        if parens:
            if part[c] != '(':
                raise SyntaxError("Expected '(' to begin number literal")
            c += 1
            end = part.find(")", c)
            if end == -1:
                raise SyntaxError("Expected ')' to terminate number literal")
        num = int(part[c:end], base)
    elif typ == "f":
        if sz_cls != 2 and sz_cls != 3:
            raise SyntaxError("float literal must be 4 or 8 bytes. got %u" % n_bytes)
        if parens:
            if part[c] != '(':
                raise SyntaxError("Expected '(' to begin number literal")
            c += 1
            end = part.find(")", c)
            if end == -1:
                raise SyntaxError("Expected ')' to terminate number literal")
        num = float(part[c:end])
    else:
        raise SyntaxError("Unrecognized literal type: '%s'" % typ)
    if parens:
        end += 1
    return num, sign, sz_cls, base is None, end


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


def get_dict_links(cmpl_obj):
    """
    :param BaseCmplObj cmpl_obj:
    """
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


def get_dict_link_src(cmpl_obj):
    """
    :param BaseCmplObj cmpl_obj:
    :rtype: dict[int, str]
    """
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


def disassembly_lst_lines(memory, start, end, named_indices):
    """
    :param bytearray memory:
    :param int|None start:
    :param int|None end:
    :param dict[int, (str, bool)] named_indices:
    :rtype: list[(int, str)]
    """
    if start is None:
        start = 0
    if end is None:
        end = len(memory)
    c = start
    lst = []
    while c < end:
        byt = memory[c]
        start_mem_pos = c
        if byt == BC_LOAD or byt == BC_STOR:
            c += 1
            typ0 = memory[c]
            sz = typ0 & BCR_SZ_MASK
            sz = 1 << (sz >> 5)
            typ1 = typ0 & BCR_TYP_MASK
            if byt == BC_STOR and typ1 in [BCR_ABS_C, BCR_RES, BCR_EA_R_IP]:
                raise ValueError("Cannot use STOR with BCR_%s (c = %u)" % (LstStackVM_BCR_Types[c], c))
            if typ1 == BCR_ABS_C:
                data = memory[c + 1: c + 1 + sz]
                num = 0
                for c1 in range(sz):
                    num |= data[c1] << (c1 * 8)
                name = named_indices.get(c + 1, None)
                if name is None:
                    s = "%ud%u ; hex = %X" % (sz, num, num)
                else:
                    scope = "g" if name[1] else "l"
                    s = scope + "Aa*%s ; size = %u num = %u hex = %X" % (name[0], sz, num, num)
                if data[-1] >= 0x80:
                    s += " signed = %i" % (num - (1 << (sz * 8)))
                c += sz
            elif typ1 == BCR_SYSREG:
                data = memory[c + 1]
                c += 1
                s = "%s-SYSREG-%s" % ("LOAD" if byt == BC_LOAD else "STOR", LstStackVM_sysregs[data])
            else:
                s = "%s-%s|SZ_%u" % (LstStackVM_Codes[byt], LstStackVM_BCR_Types[typ1], sz)
                if typ1 == BCR_REG_BP:
                    sz = 8
                a = 0
                if typ1 & BCR_R_BP_MASK == BCR_R_BP_VAL:
                    a = 1
                elif typ1 == BCR_ABS_A4:
                    a = 2
                elif typ1 == BCR_ABS_A8:
                    a = 3
                elif typ1 == BCR_EA_R_IP:
                    a = 4
                if a:
                    off_sz = sz
                    if a == 1:
                        off_sz = 1 << (typ1 - BCR_R_BP1)
                    elif a == 2:
                        off_sz = 4
                    elif a == 3:
                        off_sz = 8
                    data = memory[c + 1: c + 1 + off_sz]
                    off = 0
                    for c1 in range(off_sz):
                        off |= data[c1] << (c1 * 8)
                    if (a == 1 or a == 4) and data[-1] >= 0x80:
                        off -= 1 << (off_sz * 8)
                    name = named_indices.get(c + 1, None)
                    if name is None:
                        s += "-%ud(%i)" % (off_sz, off)
                    else:
                        lbl = "g" if name[1] else "l"
                        if a == 1:
                            lbl += "R@"
                        elif a == 2 or a == 3:
                            lbl += "A@"
                        else:
                            lbl += "Ra*"
                        lbl += name[0]
                        s += "-(%s) ; size = %u num = %i" % (lbl, off_sz, off)
                    c += off_sz
        elif BC_NOP <= byt <= BC_GE0 or BC_LSHIFT1 <= byt <= BC_RET_N2:
            s = LstStackVM_Codes[byt]
        elif byt == BC_SWAP:
            c += 1
            typ0 = memory[c]
            sz_a = typ0 & BCS_SZ_A_MASK
            sz_b = (typ0 & BCS_SZ_B_MASK) >> 3
            s = "SWAP-%sA|%sB" % (LstStackVM_BCS_Types[sz_a], LstStackVM_BCS_Types[sz_b])
        elif byt == BC_CONV:
            c += 1
            typ0 = memory[c]
            typ_i = typ0 & BCC_I_MASK
            typ_o = (typ0 & BCC_O_MASK) >> 4
            s = "CONV-%sI|%sO" % (LstStackVM_BCC_Types[typ_i], LstStackVM_BCC_Types[typ_o])
        elif byt == BC_INT:
            c += 1
            typ0 = memory[c]
            s = "INT-1x(%02X)" % typ0
            # raise ValueError("Unrecognized ByteCode at c = %u: BC_INT" % c)
        elif byt == BC_RET_E:
            c += 1
            typ0 = memory[c]
            if typ0 & BCRE_SYS:
                raise ValueError("Unrecognized ByteCode at c = %u: BC_RET_E-BCRE_SYS (SYSRET is not allowed)" % c)
            sz_cls_res = (typ0 & BCRE_RES_SZ_MASK) >> 3
            sz_cls_rst_sp = (typ0 & BCRE_RST_SP_SZ_MASK) >> 5
            s = "RET_E-RES_SZ%u|RST_SP_SZ%u" % (1 << sz_cls_res, 1 << sz_cls_rst_sp)
        elif byt == BC_CALL_E:
            c += 1
            typ0 = memory[c]
            if typ0 & BCCE_SYSCALL:
                sysn_sz_cls = typ0 >> 5
                s = "CALL_E-SYSCALL|S_SYSN_%u" % (1 << sysn_sz_cls)
            elif typ0 & BCCE_N_REL:
                s = "CALL_E-N_REL"
            else:
                s = "CALL_E-1x0"
        elif byt == BC_SYSRET:
            raise ValueError("Unrecognized ByteCode at c = %u: BC_SYSRET" % c)
        else:
            raise ValueError("Unrecognized Implementation defined instruction (c = %u): %u" % (c, byt))
        lst.append((start_mem_pos, s))
        c += 1
    return lst


def disassemble(memory, start, end, named_indices, address_fmt=None, src_pos=None):
    """
    :param bytearray memory:
    :param int|None start:
    :param int|None end:
    :param dict[int, (str, bool)] named_indices:
    :param str|None|((str, int) -> str) address_fmt:
    :param dict[int, str]|None src_pos:
    :rtype: str
    """
    lst = disassembly_lst_lines(memory, start, end, named_indices)
    lst_lines = [""] * len(lst)
    if address_fmt is None:
        for c in range(len(lst)):
            lst_lines[c] = lst[c][1]
    elif isinstance(address_fmt, str):
        for c in range(len(lst)):
            lst_lines[c] = address_fmt % (lst[c][0], lst[c][1])
    else:
        for c in range(len(lst)):
            lst_lines[c] = address_fmt(lst[c][1], lst[c][0])
    if src_pos is not None:
        lst_insert = []
        for c in range(len(lst)):
            addr = lst[c][0]
            name = src_pos.get(addr, None)
            if name is not None:
                lst_insert.append((c, name))
        for index, name in lst_insert[::-1]:
            lst_lines.insert(index, name)
    return "\n".join(lst_lines)


def lst_code_key_fn(x, i):
    """
    :param (int, str) x:
    :param i:
    :rtype: int
    """
    return x[i][0]


class Debugger(object):
    def __init__(self, vm_inst, code_start, code_end, named_indices):
        """
        :param VirtualMachine vm_inst:
        :param int code_start:
        :param int code_end:
        :param dict[int, (str, bool)] named_indices:
        """
        self.code_start = code_start
        self.code_end = code_end
        self.vm_inst = vm_inst
        self.ip_offset = 0
        if vm_inst.virt_mem_mode == VM_DISABLED:
            memory = vm_inst.memory
        elif vm_inst.virt_mem_mode == VM_4_LVL_9_BIT:
            memory = bytearray(code_end - code_start)
            assert code_start & 0xFFF == 0, "code must start at page boundary"
            part_pg_code_end = (code_end | 0xFFF) ^ 0xFFF
            if part_pg_code_end == code_end:
                full_pg_code_end = part_pg_code_end
            else:
                full_pg_code_end = part_pg_code_end + 0x1000
            for addr in range(code_start, part_pg_code_end, 4096):
                mv = vm_inst.get_mv_as_priv(vm_inst.priv_lvl, 4096, addr, MRQ_DONT_CHECK)
                memory[addr: addr + 4096] = mv
            memory[part_pg_code_end: code_end] = vm_inst.get_mv_as_priv(
                vm_inst.priv_lvl, code_end - part_pg_code_end, part_pg_code_end, MRQ_DONT_CHECK
            )
            self.ip_offset = code_start
        self.lst_code = disassembly_lst_lines(memory, code_start, code_end, named_indices)
        self.cur_loc = len(self.lst_code)
        self.set_of_brks = set()
        self.calc_loc()

    def add_brk_point(self, loc):
        """
        :param int loc:
        """
        addr = self.lst_code[loc][0]
        self.set_of_brks.add(addr)

    def calc_loc_from_ip(self, ip):
        ip -= self.ip_offset
        # returns lvl = 1 for splitting loc - 1 and loc
        # returns lvl = 2 for greater than the address of the last LOC
        # returns lvl = 3 for
        lst_code = self.lst_code
        begin, end = bisect_search_base(lst_code, ip, lst_code_key_fn)
        lvl = 0
        if begin == end:
            lvl = 1
        loc = begin
        if loc > len(lst_code):
            if len(lst_code) > 0:
                lvl = 2
            else:
                lvl = 3
        return lvl, loc

    def calc_loc(self):
        ip = self.vm_inst.ip
        ip -= self.ip_offset
        lst_code = self.lst_code
        begin, end = bisect_search_base(lst_code, ip, lst_code_key_fn)
        if begin == end:
            print("WARN: ip = %u, which splits the LOC %u and %u" % (ip, begin - 1, begin))
        self.cur_loc = begin
        if self.cur_loc > len(lst_code):
            if len(lst_code) > 0:
                print("WARN: ip = %u, greater than the address of the last LOC %u" % (ip, lst_code[-1][0]))
            else:
                print("WARN: ip = %u, and no lines of code were found")

    def step(self):
        if self.vm_inst.step():
            self.calc_loc()
            return self.cur_loc
        print("WARN: vmInst was Stopped")
        return -1

    def step_over(self):
        assert self.cur_loc + 1 < len(self.lst_code)
        next_ip = self.lst_code[self.cur_loc + 1][0]
        self.vm_inst.debug({next_ip})
        self.calc_loc()
        return self.cur_loc

    def debug(self):
        self.vm_inst.debug(self.set_of_brks)
        self.calc_loc()
        return self.cur_loc

    def print_state(self):
        print(self.get_state_str())

    def print_cur_line(self):
        print(self.get_cur_line_str())

    def get_cur_line_str(self):
        cur_loc = self.cur_loc
        ln = self.lst_code[cur_loc]
        return "0x%04X: %s ;; line=%04u" % (ln[0], ln[1], cur_loc)

    def print_step(self):
        self.step()
        self.print_state()

    def get_state_str(self):
        s = self.get_cur_line_str()
        sp, bp = self.vm_inst.sp, self.vm_inst.bp
        return "%s\n  sp = %u (0x%X) bp = %u (0x%X)" % (s, sp, sp, bp, bp)

    def get_state_data(self, do_tb=False):
        vm_inst = self.vm_inst
        return self.cur_loc, vm_inst.ip, vm_inst.bp, vm_inst.sp, (self.get_stack_data() if do_tb else None)

    def get_ext_state_data(self, prev_sp, do_tb=False):
        vm_inst = self.vm_inst
        stack_diff = None
        sp_diff = prev_sp - vm_inst.sp
        if sp_diff != 0:
            stack_diff = (sp_diff, vm_inst.get(sp_diff, vm_inst.sp) if sp_diff > 0 else None)
        return self.cur_loc, vm_inst.ip, vm_inst.bp, vm_inst.sp, (self.get_stack_data() if do_tb else None), stack_diff

    def get_state_data_watched(self, do_tb=False):
        vm_inst = self.vm_inst
        stack_diff = None
        if len(vm_inst.WatchData):
            stack_diff = vm_inst.WatchData
            vm_inst.WatchData = []
        return self.cur_loc, vm_inst.ip, vm_inst.bp, vm_inst.sp, (self.get_stack_data() if do_tb else None), stack_diff

    def get_state_entry_watched_str(self, data):
        loc, ip, bp, sp, the_tb, stack_diff = data
        line = self.lst_code[loc]
        s = "0x%04X: %s ;; line=%04u\n  sp = %u (0x%X) bp = %u (0x%X)" % (line[0], line[1], loc, sp, sp, bp, bp)
        if the_tb is not None:
            s += "\n  TRACEBACK:\n    " + "\n    ".join([
                "CodeAddr = 0x%04X, BasePointer = 0x%04X" % (bp1, ip1)
                for bp1, ip1 in the_tb
            ])
        if stack_diff is not None:
            s += "\n  STACK-DIFF:"
            for sz, Val in stack_diff:
                s += "\n    sz=%u, Val=%r" % (sz, Val)
        return s

    def get_ext_state_entry_str(self, data):
        loc, ip, bp, sp, the_tb, stack_diff = data
        line = self.lst_code[loc]
        s = "0x%04X: %s ;; line=%04u\n  sp = %u (0x%X) bp = %u (0x%X)" % (line[0], line[1], loc, sp, sp, bp, bp)
        if the_tb is not None:
            s += "\n  TRACEBACK:\n    " + "\n    ".join([
                "CodeAddr = 0x%04X, BasePointer = 0x%04X" % (bp1, ip1)
                for bp1, ip1 in the_tb
            ])
        if stack_diff is not None:
            s += "\n  STACK-DIFF: %u" % stack_diff[0]
            if stack_diff[1] is not None:
                s += ("\n    %ux%0" + "%uX" % (2 * stack_diff[0])) % (stack_diff[0], stack_diff[1])
        return s

    def get_state_entry_str(self, data):
        loc, ip, bp, sp, the_tb = data
        line = self.lst_code[loc]
        if the_tb is None:
            return "0x%04X: %s ;; line=%04u\n  sp = %u (0x%X) bp = %u (0x%X)" % (line[0], line[1], loc, sp, sp, bp, bp)
        else:
            return "0x%04X: %s ;; line=%04u\n  sp = %u (0x%X) bp = %u (0x%X)\n  TRACEBACK:\n    %s" % (
                line[0], line[1], loc, sp, sp, bp, bp, "\n    ".join([
                    "CodeAddr = 0x%04X, BasePointer = 0x%04X" % (bp1, ip1)
                    for bp1, ip1 in the_tb
                ]))

    def get_stack_data(self):
        vm_inst = self.vm_inst
        bp = vm_inst.bp
        ip = vm_inst.ip
        rtn = []
        while bp < len(vm_inst.memory):
            rtn.append((ip, bp))
            ip = vm_inst.get(8, bp)
            bp = vm_inst.get(8, bp + 8)
        return rtn

    def print_debug(self):
        self.debug()
        self.print_state()

    def print_step_over(self):
        self.step_over()
        self.print_state()


def do_map_reduce_lookup_stack_vm(lookup, s):
    rtn = 0
    for Tok in s.split("|"):
        rtn |= lookup[Tok]
    return rtn


def parse_aux_codes(part: str, def_code_type: Optional[str], c: int=0) -> bytearray:
    # TODO: this may be extended in the future to support
    # TODO:   arbitrary inline machine code with syntax like "(8d0)" for 8 BC_NOP instructions
    end = part.find("-", c)
    if end == -1:
        end = len(part)
    code_type = def_code_type
    pos = part.find('(', c, end)
    parenth = False
    if pos != -1:
        parenth = True
        if pos > c:
            code_type = part[c:pos]
        c = pos + 1
        end = part.find(')', c)
        if end == -1:
            raise SyntaxError("Expected ')' to terminate Auxiliary codes")
    rtn = bytearray()
    s = part[c:end]
    last_instr = None if parenth else StackVM_Codes.get(s, None)
    if last_instr is not None:
        code_type = None
    elif code_type == "BCR":
        last_instr = do_map_reduce_lookup_stack_vm(StackVM_BCR_Codes, s)
    elif code_type == "BCS":
        last_instr = do_map_reduce_lookup_stack_vm(StackVM_BCS_Codes, s)
    elif code_type == "BCC":
        last_instr = do_map_reduce_lookup_stack_vm(StackVM_BCC_Codes, s)
    elif code_type == "BCRE":
        last_instr = do_map_reduce_lookup_stack_vm(StackVM_BCRE_Codes, s)
    elif code_type == "BCCE":
        last_instr = do_map_reduce_lookup_stack_vm(StackVM_BCCE_Codes, s)
    elif code_type == "SVSR":
        last_instr = do_map_reduce_lookup_stack_vm(StackVM_SVSR_Codes, s)
    else:
        raise SyntaxError("Unrecognized code type: '%s'" % code_type)
    rtn.append(last_instr)
    return rtn, end + int(parenth), last_instr, code_type


def remove_comment_asm(line: str) -> str:
    pos = line.find(";")
    if pos != -1:
        line = line[:pos]
    return line


def assemble(cmpl_unit: BaseCmplObj, rel_bp_names: Dict[str, Tuple[int, int]], str_asm: str) -> Dict[str, Linkage]:
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
                '''Parts = part[0].split("-")
                for Comp in Parts:
                    ByteCode = StackVM_Codes.get(Comp.upper(), None)
                    if ByteCode is None:
                        ByteCode = 0
                        for Comp1 in Comp.split("|"):
                            Val = StackVM_BCR_Codes.get(Comp1.upper(), None)
                            if Val is None:
                                ByteCode = None
                                break
                            else: ByteCode |= Val
                    if ByteCode is None:
                        raise SyntaxError("Unrecognized Bytecode instruction: %s" % part[0])
                    else:
                        CmplUnit.memory.append(ByteCode)'''
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


'''MyMalloc = Compilation()
Assemble(
    MyMalloc.SpawnCompileObject(CMPL_T_FUNCTION, "_@IdAllocator@@FPB04Rangeyyy@IdAllocator"),
    {"this": (0x10, 8), "ArrRanges": (0x18, 8), "LenArr": (0x20, 8), "Min": (0x28, 8), "Max": (0x30, 8)}, """\
8d1
@this
8d8
ADD8
STOR-ABS_S8|SZ_8
@LenArr
@this
8d16
ADD8
STOR-ABS_S8|SZ_8
@ArrRanges
@this
STOR-ABS_S8|SZ_8
@Min
@this
8d24
ADD8
STOR-ABS_S8|SZ_8
@Max
@this
8d32
ADD8
STOR-ABS_S8|SZ_8
@Min
@this
LOAD-ABS_S8|SZ_8
STOR-ABS_S8|SZ_8
@Max
@this
LOAD-ABS_S8|SZ_8
8d8
ADD8
STOR-ABS_S8|SZ_8
""")
Assemble(
    # TODO: compile IdAllocator::ReduceRanges
    MyMalloc.SpawnCompileObject(CMPL_T_FUNCTION, "_@IdAllocator@@ReduceRanges@V"),
    {"this": (0x10, 8)}, """\
~+i,8d1
~+c,8d1
:checkFor
@c
@this
8d8
ADD8
LOAD-ABS_S8|SZ_8
CMP8
LT0
EQ0
lRa*:endFor
JMPIF

@i
@c
CMP8
NE0
EQ0
lRa*:endIf1
JMPIF

@this
LOAD-ABS_S8|SZ_8
@c
8d16
MUL8
ADD8
LOAD-ABS_S8|SZ_8
@this
LOAD-ABS_S8|SZ_8
@i
8d16
MUL8
ADD8
STOR-ABS_S8|SZ_8

@this
LOAD-ABS_S8|SZ_8
@c
8d16
MUL8
ADD8
LOAD-ABS_S8|SZ_8
@this
LOAD-ABS_S8|SZ_8
@i
8d16
MUL8
ADD8
STOR-ABS_S8|SZ_8
:endIf1

@i
@c
CMP8
NE0
EQ0
lRa*:elseIf2
JMPIF

:elseIf2

lRa*:endIf2

:endIf2

:endFor
""")
'''