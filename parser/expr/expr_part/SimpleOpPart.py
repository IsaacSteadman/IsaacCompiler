from .BaseOpPart import BaseOpPart


class SimpleOpPart(BaseOpPart):
    def __init__(self, tok):
        """
        :param Token tok:
        """
        self.txt = tok.str
        self.special = False
        if self.txt in DCT_FIXES:
            self.prefix_lvl, self.infix_lvl, self.postfix_lvl = DCT_FIXES[self.txt]
        elif self.txt.startswith("."):
            self.prefix_lvl, self.infix_lvl, self.postfix_lvl = None, None, DCT_FIXES["."][1]
            self.special = True
        elif self.txt.startswith("->"):
            self.prefix_lvl, self.infix_lvl, self.postfix_lvl = None, None, DCT_FIXES["->"][1]
            self.special = True
        else:
            raise ValueError("cannot accept '%s'" % self.txt)
        super(SimpleOpPart, self).__init__()
        # self.is_op = tok.type_id in [TokenType.BRK_OP, TokenType.OPERATOR]
        self.is_expr = not any([self.can_prefix, self.can_infix, self.can_postfix])

    def __repr__(self):
        return "%s(<Token>(%r))" % (self.__class__.__name__, self.txt)

    def build(self, operands, fixness):
        if self.special:
            if self.txt.startswith("->"):
                return SpecialPtrMemberExpr(operands[0], self.txt[2:])
            elif self.txt.startswith("."):
                return SpecialDotExpr(operands[0], self.txt[1:])
        elif fixness == 3:
            return BinaryOpExpr(DCT_INFIX_OP_NAME[self.txt], operands[0], operands[1])
        elif fixness == 1:
            return UnaryOpExpr(DCT_PREFIX_OP_NAME[self.txt], operands[0])
        elif fixness == 2:
            return UnaryOpExpr(DCT_POSTFIX_OP_NAME[self.txt], operands[0])
        else:
            raise ValueError("unexpected fixness or operator name: operands = %r, fixness = %r" % (operands, fixness))


from ..SpecialDotExpr import SpecialDotExpr
from ..SpecialPtrMemberExpr import SpecialPtrMemberExpr
from ..UnaryOpExpr import UnaryOpExpr, DCT_POSTFIX_OP_NAME, DCT_PREFIX_OP_NAME
from ..BinaryOpExpr import BinaryOpExpr, DCT_INFIX_OP_NAME
from ...constants import DCT_FIXES