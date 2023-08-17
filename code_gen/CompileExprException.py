from typing import Any, Dict


class CompileExprException(Exception):
    def __init__(self, vars: Dict[str, Any]):
        self.vars = vars

    def __str__(self):
        return "CompileExprException(%s)" % ", ".join("%s = %r" % (k, v) for k, v in self.vars.items())