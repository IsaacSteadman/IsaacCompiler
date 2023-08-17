

def remove_comment_asm(line: str) -> str:
    pos = line.find(";")
    if pos != -1:
        line = line[:pos]
    return line