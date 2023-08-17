from ...PrettyRepr import PrettyRepr, get_pretty_repr


class IdentifiedQualType(PrettyRepr):
    def __init__(self, name, typ):
        self.name = name
        self.typ = typ
        self.is_op_fn = False

    def add_qual_type(self, qual_id, ext_inf=None):
        self.typ = QualType(qual_id, self.typ, ext_inf)

    def to_mangle_str(self):
        return self.typ.to_mangle_str()

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.name, self.typ))

    def to_user_str(self):
        return self.name + " is a " + get_user_str_from_type(self.typ)


from .QualType import QualType
from .get_user_str_from_type import get_user_str_from_type