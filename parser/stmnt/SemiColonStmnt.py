


class SemiColonStmnt(BaseStmnt):
    stmnt_type = StmntType.SEMI_COLON
    # init-args added for __repr__

    def __init__(self, expr: Optional[BaseExpr] = None):
        self.expr = expr
        if self.expr is not None:
            self.expr.init_temps(None)

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.expr) + [")"]

    def build(self, tokens: List[Token], c: int, end: int, context: "CompileContext") -> int:
        self.expr, c = get_expr(tokens, c, ";", end, context)
        if self.expr is not None:
            self.expr.init_temps(None)
        else:
            print("WARN: expr is None: " + get_user_str_parse_pos(tokens, c))
        c += 1
        return c