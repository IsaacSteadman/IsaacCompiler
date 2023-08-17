from .BaseOpPart import BaseOpPart


class SParenthOpPart(BaseOpPart):
    postfix_lvl = 2

    def __init__(self, expr):
        super(SParenthOpPart, self).__init__()
        self.expr = expr

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.expr)

    def build(self, operands, fixness):
        assert len(operands) == 1
        assert fixness == 2
        return SParenthExpr(operands[0], self.expr)


from ..SParenthExpr import SParenthExpr