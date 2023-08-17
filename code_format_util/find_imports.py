import json
from os import listdir
import re
from typing import Dict, List, Set, Tuple, TypedDict
from os.path import abspath, dirname, join, is_dir, is_file


class SymbolTableFileEntry(TypedDict):
    files_to_symbols: Dict[Tuple[str], Set[Tuple[str]]]
    symbols_to_files: Dict[str, Set[Tuple[str]]]


base_dir = dirname(dirname(abspath(__file__)))
symbol_table_path = join(base_dir, "symbol_table.json")


class_re = re.compile(r"^class\s+([a-zA-Z_]\w*)\b")
func_re = re.compile(r"^def\s+([a-zA-Z_]\w*)\b")
assign_re = re.compile(r"^([a-zA-Z_]\w*)\s*=")


def get_symbols(file_path):
    with open(file_path, "r") as fl:
        for line in fl:
            match = class_re.match(line)
            if match:
                yield match.group(1)
                continue
            match = func_re.match(line)
            if match:
                yield match.group(1)
                continue
            match = assign_re.match(line)
            if match:
                yield match.group(1)
                continue


def build_symbol_table_recursive(symbol_table: Dict[str, Set[Tuple[str]]], dir_path: str, prefix: Tuple[str]):
    for file_name in listdir(dir_path):
        file_path = join(dir_path, file_name)
        if is_file(file_path):
            if dir_path == base_dir:
                continue
            if not file_name.endswith(".py"):
                continue

        if file_name.endswith(".py"):
            for symbol in get_symbols(file_path):
                symbol_table.setdefault(symbol, set()).add(tuple(file_path.split("/")))
        elif file_name != "__pycache__":
            build_symbol_table_recursive(symbol_table, file_path)


def load_symbol_table() -> Dict[str, Set[Tuple[str]]]:
    try:
        with open(symbol_table_path, "r") as fl:
            symbol_table = json.load(fl)
    except FileNotFoundError:
        return {}
    return {
        k: set(map(tuple, v))
        for k, v in symbol_table.items()
    }


def save_symbol_table(symbol_table: Dict[str, Set[Tuple[str]]]):
    symbol_table_json = {
        k: sorted(map(list, v))
        for k, v in symbol_table.items()
    }
    with open(symbol_table_path, "w") as fl:
        json.dump(symbol_table_json, fl)


def build_symbol_table():
    symbol_table = load_symbol_table()
    try:
        build_symbol_table_recursive(symbol_table, base_dir)
    finally:
        save_symbol_table(symbol_table)