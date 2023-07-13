from os.path import dirname, abspath, join
import tiktoken


file_dir = dirname(abspath(__file__))


files = [
    "./CompilingUtils.py",
    "./Filing.py",
    "./Lexing.py",
    "./Parsing.py",
    "./PrettyRepr.py",
    "./ParseConstants.py",
    "./StackVM/PyStackVM.py",
    "./StackVM/Documentation/stack_vm.md"
]


files1 = [
    (f_name, join(file_dir, f_name))
    for f_name in files
]


def readfile(f_name: str) -> str:
    with open(f_name, "r") as fl:
        return fl.read()


files2 = [
    (f_name, readfile(full_path))
    for f_name, full_path in files1
]


enc = tiktoken.get_encoding("p50k_base")


files3 = [
    (f_name, len(enc.encode(file_content)))
    for f_name, file_content in files2
]


print("\n".join(map("%s: %u".__mod__, files3)))
print("sum", sum(map(lambda x: x[1], files3)))