from .BaseOpPart import BaseOpPart


class ExprOpPart(BaseOpPart):
    def __init__(self, expr):
        super(ExprOpPart, self).__init__()
        self.is_expr = True
        self.expr = expr

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.expr)

    def build(self, operands, fixness):
        assert len(operands) == 0
        assert fixness == 0
        return self.expr