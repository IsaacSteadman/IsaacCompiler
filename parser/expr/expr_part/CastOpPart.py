from .BaseOpPart import BaseOpPart


class CastOpPart(BaseOpPart):
    prefix_lvl = 3

    def __init__(self, type_name):
        super(CastOpPart, self).__init__()
        self.type_name = type_name

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.type_name)

    def build(self, operands, fixness):
        assert fixness == 1, "cast must be used as prefix"
        res = get_standard_conv_expr(operands[0], self.type_name)
        if res is not None:
            return CastOpExpr(self.type_name, res[0])
        else:
            # TODO: may cause issues
            print(
                "WARN: cast from (%s) to (%s) is not going through standard_conv_expr"
                % (
                    get_user_str_from_type(operands[0].t_anot),
                    get_user_str_from_type(self.type_name),
                )
            )
            pt, vt, is_ref = get_tgt_ref_type(operands[0].t_anot)
            res = operands[0]
            if is_ref:
                res = CastOpExpr(vt, res)
            return CastOpExpr(self.type_name, res)
        # raise TypeError("Could not cast")


from ..CastOpExpr import CastOpExpr
from ...type.types import get_tgt_ref_type
from ...type.get_user_str_from_type import get_user_str_from_type
from ..get_standard_conv_expr import get_standard_conv_expr
