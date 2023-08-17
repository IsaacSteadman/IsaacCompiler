


class BaseOpPart(object):
    txt = "<UNNAMED>"
    special = False
    prefix_lvl = None
    infix_lvl = None
    postfix_lvl = None
    can_nofix = False
    is_expr = False

    def __init__(self):
        self.can_infix = self.infix_lvl is not None
        self.can_postfix = self.postfix_lvl is not None
        self.can_prefix = self.prefix_lvl is not None

    def build(self, operands, fixness):
        raise NotImplementedError("Cannot call 'build' on Abstract class BaseOpPart")