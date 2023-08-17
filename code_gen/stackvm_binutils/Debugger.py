from typing import Tuple
from ...StackVM import VM_DISABLED, VM_4_LVL_9_BIT, MRQ_DONT_CHECK
from .disassembly_lst_lines import disassembly_lst_lines
from ...PyIsaacUtils.AlgoUtils import bisect_search_base


def lst_code_key_fn(x: Tuple[int, str], i: int) -> int:
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
