from Parsing import *
import time
import sys
from LibUtilsABI import lib_utils_abi


# for (UInt64 c = 0; c < Sz; ++c) {
#   dest[c] = src[c];
# }

run_opt = 5  # for full compiler test (it compiles a demo program)
# run_opt = 1  # for c-decl parsing test
# run_opt = 0


# just a function to test where c is defined
def ghe():
    zzy = c
    print(zzy)


def main_main():
    c = 0
    Data = "FZiiizPFZiiizFZPFZiiiziiz"
    while c < len(Data):
        Type, c = from_mangle(Data, c)
        print(get_user_str_from_type(Type))


def do_test():
    print("RUNNING TEST")
    context = CompileContext("", None)
    obj = LiteralExpr()
    tokens = [DblQuoteClass('"hello world"', 0, 0), NameClass("ignore_this", 0, 13)]
    End = len(tokens)
    c = 0
    c = obj.build(tokens, c, End, context)
    print("ASSERTING TEST")
    assert c == 1
    assert obj.t_anot is not None
    pt, vt, is_ref = get_tgt_ref_type(obj.t_anot)
    assert is_ref
    assert vt.type_class_id == TYP_CLS_QUAL
    assert isinstance(vt, QualType)
    assert vt.qual_id == QualType.QUAL_ARR
    assert vt.ext_inf == 12
    print("USER_CHECK: obj.t_anot = %s" % get_user_str_from_type(obj.t_anot))
    print("FINISHED TEST")


do_test()


def add_cmd_argv_vm(vm_inst, i_end_prog, lst_args):
    """
    :param VirtualMachine vm_inst:
    :param int|long i_end_prog:
    :param list[str|unicode] lst_args:
    :rtype: VirtualMachine
    """
    argc = len(lst_args)
    lst_arg_ptrs = [0] * argc
    bytes_args = bytearray()
    for c, Arg in enumerate(lst_args):
        lst_arg_ptrs[c] = i_end_prog + len(bytes_args)
        bytes_args.extend((Arg + "\0").encode("utf-8"))
    vm_inst.set_bytes(i_end_prog, bytes_args)
    argv = i_end_prog + len(bytes_args)
    vm_inst.set_bytes(i_end_prog, bytes_args)
    ptr_cur = argv
    for Ptr in lst_arg_ptrs:
        vm_inst.set(8, ptr_cur, Ptr)
        ptr_cur += 8
    vm_inst.push(8, argv)
    vm_inst.push(4, argc, 1)
    return vm_inst


if __name__ == "__main__" and run_opt == 5:
    from os.path import abspath
    test_files_dir = abspath("./test_files").replace("\\", "/")
    print("TEST_FILES_DIR = %s" % test_files_dir)
    # with open(test_files_dir + "/main.cpp", "rb") as fl:
    #     tokens = ClsBrkLexer(fl.read())
    # tokens = filter(lambda x: x.type_id not in {CLS_WS, CLS_BLK_COMMENT, CLS_LN_COMMENT}, tokens)
    # with open(test_files_dir + "/floats_with_classes.cpp", "r") as fl:
    #    tokens = get_list_tokens(fl)
    # "/floats_and_ints.cpp"

    with open(test_files_dir + "/main_ns.cpp", "r") as fl:
       tokens = get_list_tokens(fl)
    # print tokens
    link_opts = LinkerOptions(LNK_OPT_ALL, 4096, lib_utils_abi.objects, LNK_RUN_STANDALONE)
    cmpl_opts = CompilerOptions(link_opts, True)
    LstStmnt, Global, CmplObj, DepDct = compile_lang1(tokens, cmpl_opts)
    # LstStmnt[1].decl_lst[0].InitArgs[0].stmnts[0].expr.Fn.t_anot
    print("BEGIN CODEGEN RESULTS")
    Links = get_dict_links(CmplObj)
    source_links = get_dict_link_src(CmplObj)
    End = CmplObj.code_segment_end
    print("  " + disassemble(CmplObj.memory, None, End, Links, "  0x%04X: %s", source_links).replace("\n", "\n  "))
    print("END CODEGEN RESULTS")
    print("code_segment_end, data_segment_start = %u, %u" % (CmplObj.code_segment_end, CmplObj.data_segment_start))
    print("len(CmplObj.memory) = %u" % len(CmplObj.memory))
    MyStackVM = VM()
    print("INIT_STATE: ip = %u, bp = %u, sp = %u, len(memory) = %u" % (
        MyStackVM.ip, MyStackVM.bp, MyStackVM.sp, len(MyStackVM.memory)))
    MyStackVM.load_program(CmplObj.memory, 0)
    EndProg = len(CmplObj.memory)
    CmdArgs = ["Hello.exe"]
    MyStackVM.push(4, 0) # return value allocation
    add_cmd_argv_vm(MyStackVM, EndProg, CmdArgs)
    MyDbg = Debugger(MyStackVM, 0, End, Links)
    Tmp0Obj = CmplObj.objects.get("?FyPcyzStrFromNumber", None)
    if Tmp0Obj is not None:
        Tmp0Lnk = CmplObj.linkages["?FyPcyzStrFromNumber"]
        Tmp0Start = Tmp0Lnk.src
        Tmp0Size = len(Tmp0Obj.memory)
        Tmp0End = Tmp0Start + Tmp0Size
        print("len(?FyPcyzStrFromNumber) = 0x%04X (%u)" % (Tmp0Size, Tmp0Size))
        print("  Start: ?FyPcyzStrFromNumber = 0x%04X (%u)" % (Tmp0Start, Tmp0Start))
        print("  EndOf: ?FyPcyzStrFromNumber = 0x%04X (%u)" % (Tmp0End, Tmp0End))
        Tmp0Lvl, Tmp0LOC = MyDbg.calc_loc_from_ip(Tmp0Start)
        assert Tmp0Lvl == 0, "Tmp0Lvl = %u, must be zero for no errors" % Tmp0Lvl
        # MyDbg.AddBrkPoint(Tmp0LOC)
    MyDbg.debug()
    #  print "START(0): STACK_TRACE"
    #  MyStackVM.PrintStackTrace()
    #  print "END: STACK_TRACE"
    #MyDbg.PrintStep()
    #MyDbg.Debug()
    #print "START(0): STACK_TRACE"
    #MyStackVM.PrintStackTrace()
    #print "END: STACK_TRACE"
    '''LstStates = []
    CurBP = MyStackVM.bp
    sp = MyStackVM.sp
    MyStackVM.EnableWatch()
    FuncBP = CurBP
    while MyDbg.Step() != -1:
        Data = None
        DoTB = MyStackVM.bp != CurBP
        Data = MyDbg.GetStateDataWatched(DoTB)
        if DoTB:
            CurBP = MyStackVM.bp
            if CurBP > FuncBP:
                MyStackVM.DisableWatch()
                break
        sp = MyStackVM.sp
        LstStates.append(Data)
    MyDbg.Debug()'''
    # use
    # print "\n".join([MyDbg.GetExtStateEntryStr(x) for x in LstStates])
    # print "\n".join([MyDbg.GetStateEntryWatchedStr(x) for x in LstStates])
    '''print "RUNNING"
    MyStackVM.Exec()'''
    print("\n" + "STOPPED".center(96, "="))
elif __name__ == "__main__" and run_opt == 4:
    toks = cls_brk_lexer("void IdAllocator(void *ArrRanges, unsigned long long LenArr, unsigned long long Min, unsigned long long Max);")
    toks1 = list(filter(lambda x: x.type_id not in {CLS_WS, CLS_BLK_COMMENT, CLS_LN_COMMENT}, toks))
    tmp_global = CompileContext("", None)
    tmp_local = tmp_global.new_scope(LocalScope("MAIN"))
    tmp_res, tmp_c = proc_typed_decl(toks1, 0, len(toks1), tmp_local)
    assert tmp_res is not None
    # TestObj.stmnts[-1].decl_lst[0]
    # TestObj.stmnts[-1].decl_lst[0].TypeName.ToMangleStr()
elif __name__ == "__main__" and run_opt == 3:
    main_main()
elif __name__ == "__main__" and run_opt == 2:
    # TODO: implement external linking
    tokens = cls_brk_lexer("""\
//extern int printf(char *str, ...);
//extern void *malloc(unsigned long long nBytes);
extern int print(char *str);
int main(int argc, char **argv) {
    print("hello world");
}
""")
elif __name__ == "__main__" and run_opt == 1:
    Tests = [
        "const unsigned long long a;",
        "const unsigned long long a = 0;",
        "int main(int argc, char **argv);",
        "const int main(int argc, char **argv);",
        "const int main(int argc, char *argv[]);",
        "const int (*main)(int argc, char **argv);",
        "const int (*main)(int argc, char *argv[]);",
        "const int (*main[12])(int argc, char **argv);",
        "const int (*main[12])(int argc, char *argv[]);",
        "int (*p)[3]",
        "int * const * p[3]",
        "const int *(main)(int argc, char **argv);",
        # FIXME: DONE it interprets this as
        # FIXME: main is a pointer to (function (argc is a int, argv is a pointer to pointer to char) -> const int)
        # FIXME: it should be
        # FIXME: main is a (function (argc is a int, argv is a pointer to pointer to char) -> pointer to const int)
        "void *memset(void * ptr, unsigned char value, unsigned long long num);",
        "void *memmove(void *dest, void *src, unsigned long long num);",
        "double pow(double base, int exponent);",
        "struct Surface initVideo(int width, int height);",
        "struct Rect blit(struct Surface tgtSurf, struct Surface srcSurf, struct Rect blitRect);",
        "struct Rect drawRect(struct Surface surf, struct Color color, struct Rect, rect, int width);",
        "struct Rect initVideo(int width, int height);",
    ]
    Global = CompileContext("", None)
    Local = Global.new_scope(LocalScope("MAIN"))
    for Str in Tests:
        print(Str)
        tokens = list(filter(lambda x: x.type_id not in {CLS_WS, CLS_BLK_COMMENT, CLS_LN_COMMENT}, cls_brk_lexer(Str)))
        c = 0
        Res = None
        # noinspection PyBroadException
        try:
            Res, c = proc_typed_decl(tokens, c, len(tokens), Local)
            assert Res is not None
        except:
            sys.stderr.write(traceback.format_exc())
        else:
            print("  MANGLE: " + mangle_decl(Res.name, Res.typ, False))
            print("  " + get_user_str_from_type(Res))
            print("  " + format_pretty(Res).replace("\n", "\n  "))
        del c
elif __name__ == "__main__" and run_opt == 0:
    print("Attempt Compile Started")
    tokens = list(filter(lambda x: x.type_id not in {CLS_WS, CLS_BLK_COMMENT, CLS_LN_COMMENT}, cls_brk_lexer("""\
{
int aba = 1;
sys_out("%p", &aba);
struct MyType;
class Thing {
    MyType *obj;
};
struct MyType {
    int xVal;
    int yVal;
} aVar;
enum Hello {
    HELLO_A = 0,
    HELLO_B = 1
};
unsigned long a = 0;
unsigned long b = 12;
int c = (int) sys_out("%ul", a * 2 + b * 2);
int x = 0, *p_x = &x, y = 12, *p_y = &y;
int *&r_p_x = p_x;
sys_out("");
sys_out("%i %p %i %p", x, p_x, y, p_y);
unsigned long count = 5;
while (count-->0) {
    sys_out("%ul", count);
    sys_out("%p", p_x); // this is a FnCallExpr
    sys_out("%i", *p_x); // why does this become a CastOpExpr
}
sys_out("It's the FINAL COUNTDOWN");
sys_out("%i", x + y);
int zz = (c + x);
zz = (a + b);
for (int c1 = 0; c1 < 2; ++c1) {
    sys_out("something");
/*    if (!(c1 == 0)) {
        sys_out("if #0 is satisfied");
    }*/
    if (c1 == 0) {
        sys_out("if is satisfied");
    }
    else if (c1 == 1) {
        sys_out("'if else' is satisfied");
    }
    else if (c1 >= 2 && !(c1 == 3 || c1 == 5)) {
        sys_out("'if else' #2 is satisfied");
    }
    else
    {
        sys_out("else is satisfied");
    }
}
int main(int argc, char *argv[]) {
    for (int c2 = 0; argv[c2] != 0; ++c2) {
        sys_out("argv[%i] = %s", c2, argv[c2]);
    }
}
}""")))
    print("tokens:\n  " + "\n  ".join(map(lambda x: "%u: %r" % x, enumerate(tokens))))
    time.sleep(0.2)
    test_obj, Global = compile_lang(tokens)
    print("Attempt Compile Finished")
    print("Printing Pretty:")
    print(test_obj.format_pretty())
    print("GLOBAL")
    assert isinstance(Global, CompileContext)
    print("Global.Types=%r" % Global.types)
    print("Global.Vars=%r" % Global.vars)
    print("Global.NameSpaces=%r" % Global.namespaces)
    print("Global.Scopes=%r" % Global.scopes)
    main_scope = Global.scopes[0]
    assert isinstance(main_scope, LocalScope)
    print("MAIN.Types=%s" % format_pretty(main_scope.types))
    print("MAIN.Vars=%s" % format_pretty(main_scope.vars))
    print("MAIN.NameSpaces=%r" % main_scope.namespaces)
    print("MAIN.Scopes=%r" % main_scope.scopes)
    time.sleep(.2)
    is_in_idle = True
    print(get_user_str_from_type(test_obj.stmnts[-1].decl_lst[0].type_name))
    mangled = test_obj.stmnts[-1].decl_lst[0].type_name.to_mangle_str()
    print("MANGLED: '%s'" % mangled)
    un_mangled, c = from_mangle(mangled, 0)
    print("UNMANGLED:\n  " + format_pretty(un_mangled, "  "))
    print("UNMANGLED USER: '%s'" % get_user_str_from_type(un_mangled))
    if not is_in_idle:
        import TermHelperMin
        TermHelperMin.repl_shell(TermHelperMin.CmdTerm(), globals(), locals(), ">>> ", "... ")
    # TODO: add type decl processing like struct Type { int a; int b;};
    # TODO: add missing Get to Compile Context