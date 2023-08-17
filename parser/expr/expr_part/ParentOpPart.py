from .BaseOpPart import BaseOpPart


class ParenthOpPart(BaseOpPart):
    postfix_lvl = 2

    def __init__(self, lst_expr):
        self.can_nofix = True
        super(ParenthOpPart, self).__init__()
        self.lst_expr = lst_expr

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.lst_expr)

    def build(self, operands, fixness):
        if fixness == 0:
            assert len(operands) == 0
            return ParenthExpr(self.lst_expr)
        else:
            assert fixness == 2
            assert len(operands) == 1
            return FnCallExpr(operands[0], self.lst_expr)


from ..ParenthExpr import ParenthExpr
from ..FnCallExpr import FnCallExpr
