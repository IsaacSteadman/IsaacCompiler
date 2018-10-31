from CompilingUtils import Compilation


SAVE_STRING_TABLE = 1
SAVE_GLOBAL_TABLE = 2
SAVE_LOCAL_TABLE = 4
# references to a symbol
SAVE_REF_STRING = 8
SAVE_REF_GLOBAL = 16
SAVE_REF_LOCAL = 32

REF_TYPE_UNDEFINED = 0
REF_TYPE_REL_BP = 1
REF_TYPE_REL_IP = 2
REF_TYPE_ABS = 3

# TODO: record data-segment start
# TODO:   see TODO of CompileLang1

from DataPacking import DataStruct, DataVarBytes, DataInt, DataArray, DataKeyValue


sym_tgt_packer = DataStruct([
    DataInt(1),  # options
    DataInt(8),  # location
    DataInt(8)  # offset
])


string_pool_sym_tbl_packer = DataKeyValue(
    DataVarBytes(8, 0, True),
    DataInt(8),
    8, 0, True
)
string_pool_sym_tgt_packer = DataKeyValue(
    DataVarBytes(8, 0, True),
    DataArray(sym_tgt_packer, 8, 0, True),
    8, 0, True
)


global_sym_tbl_packer = DataKeyValue(
    DataVarBytes(8, 0, True),
    DataInt(8),
    8, 0, True
)
global_sym_tgt_packer = DataKeyValue(
    DataVarBytes(8, 0, True),
    DataArray(sym_tgt_packer, 8, 0, True),
    8, 0, True
)


local_sym_tbl_packer = DataKeyValue(
    DataVarBytes(8, 0, True),
    DataInt(8),
    8, 0, True
)
local_sym_tgt_packer = DataKeyValue(
    DataVarBytes(8, 0, True),
    DataArray(sym_tgt_packer, 8, 0, True),
    8, 0, True
)


def save_compilation(cmpl_obj, fl, opts=SAVE_GLOBAL_TABLE | SAVE_STRING_TABLE):
    """
    :param Compilation cmpl_obj:
    :param file fl:
    :param opts:
    """
    del cmpl_obj
    fl.write(b"\x00\x00")  # version tag
    fl.write(chr(opts))
    if opts & SAVE_STRING_TABLE:
        x = [(k,cmpl_obj.string_pool[k]) for k in cmpl_obj.string_pool]
    if opts & SAVE_GLOBAL_TABLE:
        pass
    if opts & SAVE_LOCAL_TABLE:
        pass
    # write header
    # write local_symbols
    c1 = cmpl_obj.objects[""]
    # c1.local_links
