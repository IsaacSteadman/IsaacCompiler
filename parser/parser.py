from Lexing import *
from PrettyRepr import *
from CompilingUtils import *
from typing import List


# TODO: fix function overloading (CodeGen and Parse-time resolution)


operators = """\
append '_g' to the operator name to get the
    global operator name
__bin_ops__
+ add
- sub
* mul
/ div
% mod
^ xor
& and
| or
= asgn
< lt
> gt
+= iadd
-= isub
*= imul
/= idiv
%= imod
^= ixor
&= iand
|= ior
<< shl
>> shr
>>= ishr
<<= ishl
== eq
!= ne
<= le
>= ge
, comma
->* ptrm
&& ssand
|| ssor
_sort_of [] index
__pre_unary_ops__
~ bnot
! lnot
++ inc
-- dec
* deref
& adrof
(typename) cast[Mangled Typename]
__post_unary_ops__
++ pinc
-- pdec
-> gattr
() fcall
"""


def compile_lang(tokens):
    """
    :param list[Token] tokens:
    """
    end = len(tokens)
    if end < 2:
        raise SyntaxError("Not Enough tokens")
    elif tokens[0].str != "{" or tokens[-1].str != "}":
        raise SyntaxError("Source Code must start with '{' and end with '}'")
    start = c = 0
    global_ctx = CompileContext("", None)
    # int sys_out(const char *FmtStr, ...);
    global_ctx.new_var(
        "sys_out",
        ContextVariable(
            "sys_out",
            QualType(
                QualType.QUAL_FN,
                PrimitiveType.from_str_name(["int"]),
                [
                    QualType(
                        QualType.QUAL_PTR,
                        QualType(
                            QualType.QUAL_CONST, PrimitiveType.from_str_name(["char"])
                        ),
                    ),
                    PrimitiveType.from_str_name(["void"]),
                ],
            ),
        ),
    )
    rtn = CurlyStmnt(None, "MAIN")
    c = rtn.build(tokens, c, end, global_ctx)
    if c == start:
        raise SyntaxError(
            "Source Code must have semi-colons (';') in the top-level scope"
        )
    return rtn, global_ctx


parsing_vars = {}


"""
Thought process of CompileExpr for post-fix '--' and '++'
--------------eval (T &) expr
8-byte ptr
--------------duplicate
8-byte ptr
8-byte ptr
--------------load value
8-byte ptr
n-byte val
--------------swap
n-byte val
8-byte ptr
--------------duplicate
n-byte val
8-byte ptr
8-byte ptr
--------------load value
n-byte val
8-byte ptr
n-byte val
--------------push (incBy)
n-byte val
8-byte ptr
n-byte val
n-byte incBy
--------------add/sub
n-byte val
8-byte ptr
n-byte val+-incBy
--------------swap
n-byte val
n-byte val+-incBy
8-byte ptr
--------------store
n-byte val
"""


def get_lst_stmnts(tokens, ctx: Optional[CompileContext] = None):
    lst_stmnt = []
    c = 0
    end = len(tokens)
    global_ctx = ctx if ctx is not None else CompileContext("", None)
    while c < end:
        stmnt, c = get_stmnt(tokens, c, end, global_ctx)
        lst_stmnt.append(stmnt)
    return lst_stmnt, global_ctx


# TODO: add support for DataSegment alignment to pages so that the code can be shared
# TODO:   page-wise while data is private to each process
def compile_lang1(tokens: List["Token"], cmpl_opts: "CompilerOptions"):
    merge_and_link = cmpl_opts.merge_and_link
    link_opts = cmpl_opts.link_opts
    extern_deps = link_opts.extern_deps
    end = len(tokens)
    global_ctx = CompileContext("", None)
    c = 0
    lst_stmnt = []
    cmpl_obj = Compilation(cmpl_opts.keep_local_syms)
    run_method = link_opts.run_method
    if run_method == LNK_RUN_STANDALONE:
        main_fn = cmpl_obj.get_link("?FiPPczmain")
        emit_load_i_const(cmpl_obj.memory, 1, True, 2)
        main_fn.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_CALL, BC_HLT])
    while c < end:
        stmnt, c = get_stmnt(tokens, c, end, global_ctx)
        try:
            compile_stmnt(cmpl_obj, stmnt, global_ctx, None)
        except Exception as exc:
            del exc
            print(get_user_str_parse_pos(tokens, c))
            raise
        lst_stmnt.append(stmnt)
    dep_tree = [("", sorted(cmpl_obj.linkages))]
    for k in cmpl_obj.objects:
        cur = cmpl_obj.objects[k]
        dep_tree.append((k, sorted(cur.linkages)))
    if extern_deps is not None:
        for k in extern_deps:
            cur = extern_deps[k]
            dep_tree.append((k, sorted(cur.linkages)))
    dep_dct = dict(dep_tree)
    used_deps = flatify_dep_desc(dep_dct, "?FiPPczmain")
    def_deps = set([k for k, Lst in dep_tree if k != ""])
    unused_deps = def_deps - used_deps
    if len(unused_deps):
        print("UNUSED: " + ", ".join(sorted(unused_deps)))
    if merge_and_link:
        excl = None
        if link_opts.optimize == LNK_OPT_ALL:
            """OldDeps = ExternDeps
            if OldDeps is not None:
                Requires = set()
                for k in sorted(cmpl_obj.Objects):
                    cur = cmpl_obj.Objects[k]
                    assert isinstance(cur, CompileObject)
                    Requires.update(cur.linkages)
                ExternDeps = {}
                for k in sorted(Requires):
                    Obj = OldDeps.get(k, None)
                    if Obj is not None:
                        ExternDeps[k] = Obj
                OldDepsSet = set(OldDeps) | set(cmpl_obj.Objects)
                Missing = Requires - OldDepsSet
                Unused = OldDepsSet - Requires
                if len(Unused): print "PRE-WARN: Unused symbols\n  " + "\n  ".join(sorted(Unused))
                if len(Missing): print "PRE-WARN: Missing symbols\n  " + "\n  ".join(sorted(Missing))
            """
            excl = unused_deps
        cmpl_obj.merge_all(link_opts, extern_deps, excl)
        cmpl_obj.link_all()
    return lst_stmnt, global_ctx, cmpl_obj, dep_dct


mangle_maps = {}


def _check_mangle_captures():
    global mangle_maps
    for Cls in [PrimitiveType, QualType, StructType, ClassType, UnionType, EnumType]:
        for k in Cls.mangle_captures:
            if k in mangle_maps:
                print(
                    "CONFLICT: %s and %s at k = %r"
                    % (Cls.__name__, mangle_maps[k].__name__, k)
                )
            mangle_maps[k] = Cls
    """for k in sorted(MangleMaps):
        Cls = MangleMaps[k]
        print "ALLOC: %s to class %s" % (k, Cls.__name__)"""


_check_mangle_captures()
