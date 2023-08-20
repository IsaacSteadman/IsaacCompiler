from typing import Union, List, Dict, Optional


def format_pretty(obj, indent="  "):
    rtn = get_pretty_repr(obj)
    indent_lvl = 0
    opens = {"[", "(", "{"}
    closes = {"]", ")", "}"}
    for c in range(len(rtn)):
        newline = False
        if rtn[c] == ",":
            newline = True
        elif rtn[c] in opens and (c + 1 >= len(rtn) or rtn[c + 1] not in closes):
            indent_lvl += 1
            newline = True
        elif rtn[c] in closes and (c - 1 < 0 or rtn[c - 1] not in opens):
            indent_lvl -= 1
        if newline:
            rtn[c] += "\n" + indent * indent_lvl
    return "".join(rtn)


def get_pretty_repr_enum(
    enum_data: Union[Dict[int, str], List[str]],
    num: int,
    enum_name: Optional[str] = None,
) -> List[str]:
    rtn = [enum_data[num]]
    if enum_name is not None:
        rtn[0:0] = [enum_name, "."]
    return rtn


class PrettyRepr(object):
    def pretty_repr(self):
        return [self.__class__.__name__, "(", ")"]

    def format_pretty(self, indent="  "):
        return format_pretty(self, indent)

    def __repr__(self):
        return "".join(self.pretty_repr())


def get_pretty_repr(obj):
    i = 0
    if isinstance(obj, list):
        i = 1
    elif isinstance(obj, tuple):
        i = 2
    elif isinstance(obj, set):
        i = 3
    elif isinstance(obj, dict):
        i = 4
    elif isinstance(obj, PrettyRepr):
        i = 5
    if i == 0:
        return [repr(obj)]
    elif 1 <= i <= 3:
        if i == 3 and len(obj) == 0:
            return ["set", "(", ")"]
        elif i == 2 and len(obj) == 1:
            return ["("] + get_pretty_repr(obj[0]) + [",", ")"]
        rtn = ["[({"[i - 1]]
        if len(obj) >= 1:
            rtn.extend(get_pretty_repr(obj[0]))
            for c in range(1, len(obj)):
                rtn.extend([","] + get_pretty_repr(obj[c]))
        rtn.append("])}"[i - 1])
        return rtn
    elif i == 4:
        lst = list(obj)
        rtn = ["{"]
        if len(lst) >= 1:
            rtn.extend(get_pretty_repr(lst[0]) + [":"] + get_pretty_repr(obj[lst[0]]))
            for c in range(1, len(obj)):
                rtn.extend(
                    [","]
                    + get_pretty_repr(lst[c])
                    + [":"]
                    + get_pretty_repr(obj[lst[c]])
                )
        rtn.append("}")
        return rtn
    elif i == 5:
        return obj.pretty_repr()
