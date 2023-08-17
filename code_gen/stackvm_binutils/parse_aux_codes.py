from typing import Optional

from StackVM.PyStackVM import StackVM_Codes, StackVM_BCR_Codes, StackVM_BCS_Codes, StackVM_BCC_Codes, StackVM_BCRE_Codes, StackVM_BCCE_Codes, StackVM_SVSR_Codes


def aggregate_lookup_stack_vm(lookup, s):
    rtn = 0
    for Tok in s.split("|"):
        rtn |= lookup[Tok]
    return rtn

def parse_aux_codes(part: str, def_code_type: Optional[str], c: int=0) -> bytearray:
    # TODO: this may be extended in the future to support arbitrary inline machine code with syntax like "(8d0)" for 8 BC_NOP instructions
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
        last_instr = aggregate_lookup_stack_vm(StackVM_BCR_Codes, s)
    elif code_type == "BCS":
        last_instr = aggregate_lookup_stack_vm(StackVM_BCS_Codes, s)
    elif code_type == "BCC":
        last_instr = aggregate_lookup_stack_vm(StackVM_BCC_Codes, s)
    elif code_type == "BCRE":
        last_instr = aggregate_lookup_stack_vm(StackVM_BCRE_Codes, s)
    elif code_type == "BCCE":
        last_instr = aggregate_lookup_stack_vm(StackVM_BCCE_Codes, s)
    elif code_type == "SVSR":
        last_instr = aggregate_lookup_stack_vm(StackVM_SVSR_Codes, s)
    else:
        raise SyntaxError("Unrecognized code type: '%s'" % code_type)
    rtn.append(last_instr)
    return rtn, end + int(parenth), last_instr, code_type
