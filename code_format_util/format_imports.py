import pyperclip
from typing import List, Tuple, Union, Set, Dict
import re


from_import_re = re.compile(r"^from\b\s*([\.\w]+)\s*\bimport\b\s*(\w.*)$")
import_re = re.compile(r"^import\b\s*(\w.*)$")


def format_imports():
    MAX_LINE_LEN = 80
    import_set: Set[tuple] = set()
    from_import_dict: Dict[tuple, Set[str]] = {}
    for line in pyperclip.paste().replace("\\\n", "").split("\n"):
        line = line.strip()
        match = from_import_re.match(line)
        if match:
            module_str = match.group(1)
            imports = set(map(str.strip, match.group(2).split(",")))
            module_key = tuple(module_str.split("."))
            total_imports = from_import_dict.get(module_key)
            if total_imports is None:
                from_import_dict[module_key] = imports
            else:
                total_imports |= imports
            continue
        match = import_re.match(line)
        assert match, "failed to match line: %r" % line
        modules = list(map(str.strip, match.group(1).split(",")))
        for module in modules:
            import_set.add(tuple(module.split(".")))
    output_entries: List[Union[Tuple[List[str]], Tuple[List[str], List[str]]]] = []
    for entry in import_set:
        output_entries.append((list(entry),))
    for module, imports in from_import_dict.items():
        output_entries.append((list(module), sorted(imports)))
    output_entries.sort(key=lambda x: (len(x[0]), x[0]))
    output_lines: List[str] = []
    for entry in output_entries:
        if len(entry) == 1:
            output_lines.append("import %s" % ".".join(entry[0]))
        elif len(entry[1]):
            module_str = ".".join(entry[0])
            imports = entry[1]
            local_output_lines = [f"from {module_str} import {imports[0]}"]
            for i, import_entry in enumerate(imports[1:], start=1):
                try_output_line = f", {import_entry}"
                if i + 1 < len(imports):
                    if len(local_output_lines[-1]) + len(try_output_line) + 2 > MAX_LINE_LEN:
                        local_output_lines[-1] += ",\\"
                        local_output_lines.append(f"    {import_entry}")
                    else:
                        local_output_lines[-1] += try_output_line
                elif len(local_output_lines[-1]) + len(try_output_line) > MAX_LINE_LEN:
                    local_output_lines[-1] += ",\\"
                    local_output_lines.append(f"    {import_entry}")
                else:
                    local_output_lines[-1] += try_output_line
            output_lines.append("\n".join(local_output_lines))
    pyperclip.copy("\n".join(output_lines))


if __name__ == "__main__":
    format_imports()




