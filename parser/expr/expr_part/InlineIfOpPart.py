from .BaseOpPart import BaseOpPart


class InlineIfOpPart(BaseOpPart):
    infix_lvl = 15

    def __init__(self, expr):
        super(InlineIfOpPart, self).__init__()
        self.expr = expr

    def build(self, operands, fixness):
        assert len(operands) == 2
        assert fixness == 3
        return InlineIfExpr(operands[0], self.expr, operands[1])


from ..InlineIfExpr import InlineIfExpr