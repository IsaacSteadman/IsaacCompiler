from Lexing import *
from PrettyRepr import *
from CompilingUtils import *
import traceback


def try_catch_wrapper0(fn):
    """
    :param (list[ParseClass], int, int, CompileContext) -> any, int fn:
    :rtype: (list[ParseClass], int, int, CompileContext) -> any, int
    """
    def new_fn(tokens, c, end, context):
        try:
            return fn(tokens, c, end, context)
        except Exception as exc:
            del exc
            print("%s: tokens = ..., c = %u, end = %u, context = ..." % (fn.__name__, c, end))
            raise
    new_fn.__name__ = fn.__name__ + "__wrapped"
    return new_fn


def try_catch_wrapper1(fn):
    """
    :param (list[ParseClass], int, str|None, int, CompileContext) -> any, int fn:
    :rtype: (list[ParseClass], int, str|None, int, CompileContext) -> any, int
    """
    def new_fn(tokens, c, delim, end, context):
        # noinspection PyBareException,PyPep8
        try:
            return fn(tokens, c, delim, end, context)
        except Exception as exc:
            del exc
            print("%s: tokens = ..., c = %u, Delim = %r, end = %u, context = ..." % (fn.__name__, c, delim, end))
            raise
    new_fn.__name__ = fn.__name__ + "__wrapped"
    return new_fn


class ParsingError(Exception):
    TOKEN_LOOK_OFFSET = 5

    def __init__(self, tokens, token_index, msg):
        super(ParsingError, self).__init__(tokens, token_index, msg)
        a = max(0, token_index - self.TOKEN_LOOK_OFFSET)
        b = min(len(tokens), token_index + self.TOKEN_LOOK_OFFSET)
        self.tokens = tokens[a:b]
        self.a = a
        self.token_index = token_index
        self.msg = msg

    def __str__(self):
        return "tokens around c = %u, {%s}\n  MESSAGE: %s" % (
            self.token_index,
            ", ".join([
                "%u: %r" % (self.a + x, self.tokens[x])
                for x in range(len(self.tokens))
            ]),
            self.msg
        )


'''class ParsingError(Exception):
    def __init__(self, tokens, token_index, Msg):
        super(ParsingError, self).__init__(tokens, token_index, Msg)
        self.Token = tokens[token_index]
        self.token_index = token_index
        self.Msg = Msg
    def __str__(self):
        return "tokens[%u] = %r (%s)" % (self.token_index, self.Token, self.Msg)'''


def get_user_str_parse_pos(tokens, c, off=5):
    a = max(0, c - off)
    b = min(len(tokens), c + off)
    return "c = %u, tokens around c: {%s}" % (c, ", ".join(["%u: %r" % (c1, tokens[c1]) for c1 in range(a, b)]))


def twos_comp(i, n_bits):
    sign = int(i < 0)
    if sign:
        i = abs(i)
        i -= 1
    bits = [0] * n_bits
    bits[0] = sign
    for c in range(n_bits - 1, 0, -1):
        bits[c] = (i & 1) ^ sign
        i >>= 1
    return bits


class BaseExpr(PrettyRepr):
    """
    :type t_anot: BaseType|None
    :type expr_id: int
    :type temps: list[BaseType]|None
    :type temps_off: int
    """
    t_anot = None
    expr_id = -1
    # temps is a list of the types of the temporaries owned by the parent Expression Object only (ie 'self')
    temps = None
    temps_off = 0

    def pretty_repr(self):
        return [self.__class__.__name__, "(", ")"]

    def init_temps(self, main_temps):
        """
        :param list[BaseType]|None main_temps:
        :rtype list[BaseType]|None
        """
        self.temps_off = 0 if main_temps is None else len(main_temps)
        if main_temps is None:
            main_temps = []
        if self.temps is not None:
            main_temps.extend(self.temps)
        self.temps = main_temps
        return main_temps


class BaseStmnt(PrettyRepr):
    stmnt_type = None
    position = (-1, -1)


def get_bool_expr(cond):
    if cond.t_anot is not None:
        to_type = bool_t
        res = get_implicit_conv_expr(cond, to_type)
        if res is None:
            raise TypeError("Expected boolean expression got \n  %s\n  with type: %s" % (
                format_pretty(cond).replace("\n", "\n  "), get_user_str_from_type(cond.t_anot)
            ))
        cond, rank = res
        if not compare_no_cvr(cond.t_anot, to_type):
            raise TypeError("Expected boolean expression")
    return cond


class ForLoop(BaseStmnt):
    stmnt_type = STMNT_FOR
    # init-args added for __repr__

    def __init__(self, init=None, cond=None, incr=None, stmnt=None):
        """
        :param BaseStmnt|None init:
        :param BaseExpr|None cond:
        :param BaseExpr|None incr:
        :param BaseStmnt|None stmnt:
        """
        self.init = init
        self.cond = None if cond is None else get_bool_expr(cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        self.incr = incr
        if self.incr is not None:
            self.incr.init_temps(None)
        self.stmnt = stmnt
        self.context = None

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((
            self.init, self.cond, self.incr, self.stmnt))

    def build(self, tokens, c, end, context):
        c += 1
        if tokens[c].str != "(":
            raise ParsingError(tokens, c, "Expected '(' to open for-loop")
        self.context = context.new_scope(LocalScope())
        c += 1
        # TODO: restrict self.init to be only semicolon, while still allowing 'int c = 0;'
        self.init, c = get_stmnt(tokens, c, end, self.context)
        if tokens[c - 1].str != ";":
            raise ParsingError(tokens, c, "Expected ';' to delimit [init] in for-loop")
        # c += 1 # not needed
        cond, c = get_expr(tokens, c, ";", end, self.context)
        if cond is None:
            cond = LiteralExpr(LiteralExpr.LIT_INT, "1")
        self.cond = get_bool_expr(cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' to delimit [condition] in for-loop")
        c += 1
        self.incr, c = get_expr(tokens, c, ")", end, self.context)
        if self.incr is not None:
            self.incr.init_temps(None)
        if tokens[c].str != ")":
            raise ParsingError(tokens, c, "Expected ')' to delimit [increment] in for-loop")
        c += 1
        self.stmnt, c = get_stmnt(tokens, c, end, self.context)
        if self.stmnt.stmnt_type not in {STMNT_SEMI_COLON, STMNT_CURLY_STMNT}:
            cls_name = self.stmnt.__class__.__name__
            raise ParsingError(tokens, c, "Cannot directly use '%s' as body for for-loop" % cls_name)
        return c


class WhileLoop(BaseStmnt):
    stmnt_type = STMNT_WHILE
    # init-args added for __repr__

    def __init__(self, cond=None, stmnt=None):
        """
        :param BaseExpr|None cond:
        :param BaseStmnt|None stmnt:
        """
        self.cond = None if cond is None else get_bool_expr(cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        self.stmnt = stmnt

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.cond, self.stmnt))

    def build(self, tokens, c, end, context):
        c += 1
        if tokens[c].str != "(":
            raise ParsingError(tokens, c, "Expected '(' to open while-loop")
        c += 1
        self.cond, c = get_expr(tokens, c, ")", end, context)
        self.cond = get_bool_expr(self.cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        if tokens[c].str != ")":
            raise ParsingError(tokens, c, "Expected ')' to delimit [condition] in while-loop")
        c += 1
        self.stmnt, c = get_stmnt(tokens, c, end, context)
        if self.stmnt.stmnt_type not in {STMNT_SEMI_COLON, STMNT_CURLY_STMNT}:
            cls_name = self.stmnt.__class__.__name__
            raise ParsingError(tokens, c, "Cannot directly use '%s' as body for while-loop" % cls_name)
        return c


class IfElse(BaseStmnt):
    stmnt_type = STMNT_IF
    # init-args added for __repr__

    def __init__(self, cond=None, stmnt=None, else_stmnt=None):
        """
        :param BaseExpr|None cond:
        :param BaseStmnt|None stmnt:
        :param BaseStmnt|None else_stmnt:
        """
        self.cond = None if cond is None else get_bool_expr(cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        self.stmnt = stmnt
        self.else_stmnt = else_stmnt

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.cond, self.stmnt, self.else_stmnt))

    def build(self, tokens, c, end, context):
        c += 1
        if tokens[c].str != "(":
            raise ParsingError(tokens, c, "Expected '(' to open if-statement")
        c += 1
        self.cond, c = get_expr(tokens, c, ")", end, context)
        self.cond = get_bool_expr(self.cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        if tokens[c].str != ")":
            raise ParsingError(tokens, c, "Expected ')' to delimit [condition] in while-loop")
        c += 1
        self.stmnt, c = get_stmnt(tokens, c, end, context)
        if self.stmnt.stmnt_type == STMNT_DECL:
            raise ParsingError(tokens, c, "Cannot directly use 'DeclStmnt' as body for if statement")
        if tokens[c].type_id == CLS_NAME and tokens[c].str == "else":
            c += 1
            self.else_stmnt, c = get_stmnt(tokens, c, end, context)
            if self.else_stmnt.stmnt_type == STMNT_DECL:
                raise ParsingError(tokens, c, "Cannot directly use 'DeclStmnt' as body for if statement")
        return c


class CurlyStmnt(BaseStmnt):
    stmnt_type = STMNT_CURLY_STMNT
    # init-args added for __repr__

    def __init__(self, stmnts=None, name=""):
        """
        :param list[BaseStmnt]|None stmnts:
        """
        self.stmnts = stmnts
        self.name = name
        self.context = None

    def pretty_repr(self):
        rtn = [self.__class__.__name__, "("] + get_pretty_repr(self.stmnts) + [")"]
        if self.name != "":
            rtn[-1:-1] = get_pretty_repr(self.name)
        return rtn

    def build(self, tokens, c, end, context):
        self.stmnts = []
        self.context = context.new_scope(LocalScope(self.name))
        c += 1
        while c < end and tokens[c].str != "}":
            stmnt, c = get_stmnt(tokens, c, end, self.context)
            self.stmnts.append(stmnt)
        c += 1
        return c


class ReturnStmnt(BaseStmnt):
    stmnt_type = STMNT_RTN

    def __init__(self, expr=None):
        """
        :param BaseExpr|None expr:
        """
        self.expr = expr
        if self.expr is not None:
            self.expr.init_temps(None)

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.expr) + [")"]

    def build(self, tokens, c, end, context):
        c += 1
        self.expr, c = get_expr(tokens, c, ";", end, context)
        if self.expr is not None:
            self.expr.init_temps(None)
        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' to terminate 'return' Statement")
        c += 1
        return c


class BreakStmnt(BaseStmnt):
    stmnt_type = STMNT_BRK
    # default pretty_repr
    # default __init__

    def build(self, tokens, c, end, context):
        """
        :param list[ParseClass] tokens:
        :param int c:
        :param int end:
        :param CompileContext context:
        :rtype: int
        """
        del self, end, context
        c += 1
        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' after 'break'")
        c += 1
        return c


class ContinueStmnt(BaseStmnt):
    stmnt_type = STMNT_CONTINUE

    def build(self, tokens, c, end, context):
        """
        :param list[ParseClass] tokens:
        :param int c:
        :param int end:
        :param CompileContext context:
        :rtype: int
        """
        del self, end, context
        c += 1
        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' after 'continue'")
        c += 1
        return c
    # default pretty_repr
    # default __init__


class NamespaceStmnt(BaseStmnt):
    stmnt_type = STMNT_NAMESPACE

    def __init__(self, lst_stmnts=None):
        self.lst_stmnts = [] if lst_stmnts is None else lst_stmnts
        """ :type: list[BaseStmnt|None]"""
        self.ns = None

    def build(self, tokens, c, end, context):
        """
        :param list[ParseClass] tokens:
        :param int c:
        :param int end:
        :param CompileContext context:
        :rtype: int
        """
        c += 1
        if tokens[c].type_id != CLS_NAME:
            raise ParsingError(tokens, c, "Expected name for namespace")
        name = tokens[c].str
        ns = context.namespace_strict(name)
        if ns is None:
            ns = CompileContext(name, context)
            context.namespaces[name] = ns
        self.ns = ns
        c += 1
        if tokens[c].str == ";":
            c += 1
        elif tokens[c].str == "{":
            c += 1
            lst_stmnts = self.lst_stmnts
            while tokens[c].str != "}" and c < end:
                stmnt, c = get_stmnt(tokens, c, end, ns)
                lst_stmnts.append(stmnt)
            if c >= end:
                raise ParsingError(tokens, c, "[Namespace] Unexpected end reached before closing '}'")
            c += 1
        return c
    # default pretty_repr
    # default __init__


class SemiColonStmnt(BaseStmnt):
    stmnt_type = STMNT_SEMI_COLON
    # init-args added for __repr__

    def __init__(self, expr=None):
        """
        :param BaseExpr|None expr:
        """
        self.expr = expr
        if self.expr is not None:
            self.expr.init_temps(None)

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.expr) + [")"]

    def build(self, tokens, c, end, context):
        self.expr, c = get_expr(tokens, c, ";", end, context)
        if self.expr is not None:
            self.expr.init_temps(None)
        else:
            print("WARN: expr is None: " + get_user_str_parse_pos(tokens, c))
        c += 1
        return c


class SingleVarDecl(PrettyRepr):
    def __init__(self, type_name, var_name, init_args, ext_spec, init_type=INIT_NONE):
        """
        :param BaseType type_name:
        :param str var_name:
        :param list[BaseExpr]|list[CurlyStmnt] init_args:
        :param int ext_spec:
        :param int init_type:
        """
        self.type_name = type_name
        self.var_name = var_name
        self.op_fn_type = OP_TYP_FUNCTION
        self.op_fn_data = None
        # TODO: add support for curly initialization (arrays and structs)
        if type_name.type_class_id in [TYP_CLS_QUAL, TYP_CLS_PRIM]:
            fn_types = type_name.get_ctor_fn_types()
            if len(fn_types):
                index_fn_t, lst_conv = abstract_overload_resolver(init_args, fn_types)
                if index_fn_t >= len(fn_types):
                    raise TypeError("No overloaded constructor for %s exists for argument types: (%s)" % (
                        get_user_str_from_type(type_name), ", ".join([
                            get_user_str_from_type(x.t_anot)
                            for x in init_args
                        ])))
                self.op_fn_type = OP_TYP_NATIVE
                self.op_fn_data = index_fn_t
                assert lst_conv is not None
                init_args = lst_conv
        self.init_args = init_args
        for expr in init_args:
            if isinstance(expr, BaseExpr):
                expr.init_temps(None)
        self.ext_spec = ext_spec
        self.init_type = init_type
    # TODO: Maybe put a stub build Method?

    def pretty_repr(self):
        rtn = [self.__class__.__name__] + get_pretty_repr((self.type_name, self.var_name, self.init_args, self.ext_spec))
        rtn[-1:-1] = [","] + get_pretty_repr_enum(LST_INIT_TYPES, self.init_type)
        return rtn


def is_array_type(typ):
    """
    :param BaseType typ:
    :rtype: bool
    """
    if typ.type_class_id == TYP_CLS_QUAL:
        assert isinstance(typ, QualType)
        return typ.qual_id == QualType.QUAL_ARR
    return False


class TypeDefStmnt(BaseStmnt):
    stmnt_type = STMNT_TYPEDEF

    def __init__(self, id_qual_types=None):
        """
        :param list[IdentifiedQualType]|None id_qual_types:
        """
        self.id_qual_types = id_qual_types

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.id_qual_types) + [")"]

    def build(self, tokens, c, end, context):
        """
        :param list[ParseClass] tokens:
        :param int c:
        :param int end:
        :param CompileContext context:
        :rtype: int
        """
        c += 1
        base_type, c = get_base_type(tokens, c, end, context)
        end_stmnt = c
        # TODO: remove this limitation as this would break inline struct definitions (like struct {int a; char b} var)
        # TODO: DONE
        lvl = 0
        while end_stmnt < end and (tokens[end_stmnt].str != ";" or lvl > 0):
            if tokens[end_stmnt].str in OPEN_GROUPS:
                lvl += 1
            elif tokens[end_stmnt].str in CLOSE_GROUPS:
                lvl -= 1
            end_stmnt += 1
        if base_type is None:
            raise SyntaxError("Expected Typename for DeclStmnt")
        self.id_qual_types = []
        while c < end_stmnt + 1:
            named_qual_type, c = proc_typed_decl(tokens, c, end_stmnt, context, base_type)
            if named_qual_type is None:
                raise ParsingError(tokens, c, "Expected Typename for DeclStmnt")
            assert isinstance(named_qual_type, IdentifiedQualType)
            if named_qual_type.name is None:
                raise ParsingError(tokens, c, "Expected a name for typedef")
            elif tokens[c].str == "," or tokens[c].str == ";":
                self.id_qual_types.append(named_qual_type)
                context.new_type(
                    named_qual_type.name,
                    TypeDefCtxMember(
                        named_qual_type.name,
                        context,
                        named_qual_type.typ
                    )
                )
                c += 1
                if tokens[c].str == ";":
                    break
            else:
                raise ParsingError(tokens, c, "Expected a ',' or ';' to delimit the typedef")
        return c


class DeclStmnt(BaseStmnt):
    stmnt_type = STMNT_DECL
    # decl_lst added to init-args for __repr__

    def __init__(self, decl_lst=None):
        """
        :param list[SingleVarDecl]|None decl_lst:
        """
        self.decl_lst = decl_lst

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.decl_lst) + [")"]

    def build(self, tokens, c, end, context):
        """
        :param list[ParseClass] tokens:
        :param int c:
        :param int end:
        :param CompileContext context:
        :rtype: int
        """
        ext_spec = 0
        if tokens[c].type_id == CLS_NAME:
            if tokens[c].str == "static":
                ext_spec = 1
                c += 1
            elif tokens[c].str == "extern":
                ext_spec = 2
                c += 1
        if (
                isinstance(context, BaseType) and
                context.type_class_id in [TYP_CLS_STRUCT, TYP_CLS_CLASS, TYP_CLS_UNION] and
                tokens[c].str == context.name and c + 1 < len(tokens) and tokens[c + 1].str == "("
        ):

            base_type = void_t
            # TODO: choose a value that will signal that this is a constructor
            #   or instead, don't enter the 'while c < end_stmnt + 1' loop
            named_qual_type, new_c = proc_typed_decl(tokens, c, end, context, base_type)
            assert isinstance(named_qual_type, IdentifiedQualType)
            assert isinstance(context, (StructType, ClassType, UnionType))
            typ = named_qual_type.typ
            assert isinstance(typ, BaseType)
            if named_qual_type.name == context.name and typ.type_class_id == TYP_CLS_QUAL:
                assert isinstance(typ, QualType)
                if typ.qual_id == QualType.QUAL_FN:
                    if ext_spec != 0:
                        raise ParsingError(tokens, c, "unexpected 'extern' or 'const' in Constructor declaration")
                    typ.qual_id = QualType.QUAL_CTOR
                    params = typ.ext_inf
                    assert isinstance(params, list)
                    params.insert(
                        0,
                        IdentifiedQualType(
                            "this",
                            QualType(QualType.QUAL_PTR, QualType(QualType.QUAL_CONST, context))
                        )
                    )
                    stmnt = None
                    if tokens[new_c].str == "{":
                        stmnt = CurlyStmnt()
                        fn_ctx = context.new_scope(LocalScope(named_qual_type.name))
                        for param in params:
                            assert isinstance(param, (IdentifiedQualType, BaseType))
                            if isinstance(param, IdentifiedQualType):
                                fn_ctx.new_var(
                                    param.name,
                                    ContextVariable(param.name, param.typ, None, ContextVariable.MOD_IS_ARG)
                                )
                        new_c = stmnt.build(tokens, new_c, end, fn_ctx)
                    self.decl_lst = [
                        SingleVarDecl(
                            typ,
                            named_qual_type.name,
                            [] if stmnt is None else [stmnt],
                            0,
                            INIT_CURLY
                        )
                    ]
                    return new_c
        base_type, c = get_base_type(tokens, c, end, context)
        end_stmnt = c
        lvl = 0
        # TODO: remove this limitation as this would break inline struct definitions (like struct {int a; char b} var)
        # TODO: Done
        while end_stmnt < end and (tokens[end_stmnt].str != ";" or lvl > 0):
            if tokens[end_stmnt].str in OPEN_GROUPS:
                lvl += 1
            elif tokens[end_stmnt].str in CLOSE_GROUPS:
                lvl -= 1
            end_stmnt += 1
        if base_type is None:
            raise SyntaxError("Expected Typename for DeclStmnt")
        self.decl_lst = []
        while c < end_stmnt + 1:
            is_non_semi_colon_end = False
            named_qual_type, c = proc_typed_decl(tokens, c, end_stmnt, context, base_type)
            if named_qual_type is None:
                raise ParsingError(tokens, c, "Expected Typename for DeclStmnt")
            assert isinstance(named_qual_type, IdentifiedQualType)
            cur_decl = None
            if named_qual_type.name is None:
                pass
            elif tokens[c].str == "=":
                c += 1
                expr, c = get_expr(tokens, c, ",", end_stmnt, context)
                cur_decl = SingleVarDecl(named_qual_type.typ, named_qual_type.name, [expr], ext_spec, INIT_ASSIGN)
            elif tokens[c].str == "(":
                c += 1
                lvl = 1
                c0 = c
                while lvl > 0 and c0 < end:
                    if tokens[c0].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c0].str in CLOSE_GROUPS:
                        lvl -= 1
                    c0 += 1
                end_p = c0 - 1
                if tokens[end_p].str != ")":
                    raise ParsingError(tokens, end_p, "Expected closing ')' before end of statement")
                init_args = []
                while c < end_p:
                    expr, c = get_expr(tokens, c, ",", end_p, context)
                    init_args.append(expr)
                    c += 1
                cur_decl = SingleVarDecl(named_qual_type.typ, named_qual_type.name, init_args, ext_spec, INIT_PARENTH)
            elif tokens[c].str == "{":
                init_args = []
                prim_type = get_base_prim_type(named_qual_type.typ)
                start = c
                if prim_type.type_class_id == TYP_CLS_QUAL:
                    assert isinstance(prim_type, QualType)
                    if prim_type.qual_id == QualType.QUAL_FN:
                        stmnt = CurlyStmnt()
                        init_args.append(stmnt)
                        fn_ctx = context.new_scope(LocalScope(named_qual_type.name))
                        assert prim_type.ext_inf is not None
                        assert not isinstance(prim_type.ext_inf, int)
                        params = prim_type.ext_inf
                        if prim_type.qual_id == QualType.QUAL_CL_FN:
                            assert isinstance(context, BaseType)
                            assert context.type_class_id in [TYP_CLS_STRUCT, TYP_CLS_CLASS, TYP_CLS_UNION]
                            assert isinstance(context, (StructType, ClassType, UnionType))
                            params.insert(
                                0,
                                IdentifiedQualType(
                                    "this",
                                    QualType(QualType.QUAL_PTR, QualType(QualType.QUAL_CONST, context))
                                )
                            )
                        for param in prim_type.ext_inf:
                            assert isinstance(param, (IdentifiedQualType, BaseType))
                            if isinstance(param, IdentifiedQualType):
                                fn_ctx.new_var(
                                    param.name,
                                    ContextVariable(param.name, param.typ, None, ContextVariable.MOD_IS_ARG)
                                )
                        c = stmnt.build(tokens, c, end, fn_ctx)
                        is_non_semi_colon_end = True
                if len(init_args) == 0:
                    expr = CurlyExpr()
                    init_args.append(expr)
                    c = expr.build(tokens, c, end, context)
                if start == c:
                    raise ParsingError(tokens, c, "Could not parse CurlyStmnt or CurlyExpr")
                cur_decl = SingleVarDecl(named_qual_type.typ, named_qual_type.name, init_args, ext_spec, INIT_CURLY)
            else:
                # print "else: tokens[%u] = %r" % (c, tokens[c])
                cur_decl = SingleVarDecl(named_qual_type.typ, named_qual_type.name, [], ext_spec)
            if cur_decl is not None:
                self.decl_lst.append(cur_decl)
                ctx_var = context.new_var(
                    cur_decl.var_name,
                    ContextVariable(cur_decl.var_name, cur_decl.type_name, None, ext_spec)
                )
                ctx_var.is_op_fn = named_qual_type.is_op_fn
                # NOTE the following must be true: SingleVarDecl(...).type_name is ContextVariable(...).typ
            if is_non_semi_colon_end:
                break
            elif tokens[c].str == ";":
                c += 1
                break
            elif tokens[c].str == ",":
                c += 1
        return c


# Top Of Stack uninitialized
VAR_REF_TOS_NAMED = 0  # has a name


# references a link to preallocated memory
VAR_REF_LNK_PREALLOC = 1


class VarRef(object):
    ref_type = None


class VarRefTosNamed(VarRef):
    ref_type = VAR_REF_TOS_NAMED

    def __init__(self, ctx_var):
        """
        :param ContextVariable|None ctx_var:
        """
        self.ctx_var = ctx_var


class VarRefLnkPrealloc(VarRef):
    ref_type = VAR_REF_LNK_PREALLOC

    def __init__(self, lnk):
        """
        :param BaseLink lnk:
        """
        self.lnk = lnk


def make_void_fn(arg_types):
    return QualType(QualType.QUAL_FN, void_t, arg_types)


class BaseType(PrettyRepr):
    type_class_id = None

    def to_mangle_str(self, top_decl=False):
        """
        :param bool top_decl:
        :rtype: str
        """
        raise NotImplementedError("Not Implemented")

    def to_user_str(self):
        """
        :rtype: str
        """
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        """
        :rtype: list[BaseType]
        """
        raise NotImplementedError("Not Implemented")

    def compile_var_init(self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param list[BaseExpr|CurlyStmnt] init_args:
        :param CompileContext context:
        :param VarRef ref:
        :param LocalCompileData|None cmpl_data:
        :param list[(BaseType,BaseLink)]|None temp_links:
        """
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param CompileContext context:
        :param VarRef ref:
        :param LocalCompileData|None cmpl_data:
        :rtype: int
        """
        # CompileVarDeInit is responsible for deallocating off the stack if CompileVarInit allocated on the stack
        #   CompileVarDeInit should return the size it deallocated
        #   or it should return -1/MAX_UINT if the size deallocation is all that is required
        #   this is done in-order to maintain the original code generation behavior that results in 2 instructions
        #   to deallocate all the variables in a scope all at once (if possible)
        # TODO: use CompileVarDeInit in CompileExpr/CompileStmnt/CompileLeaveScope? according the comments above
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param BaseExpr expr:
        :param CompileContext context:
        :param LocalCompileData|None cmpl_data:
        :param list[(BaseType,BaseLink)]|None temp_links:
        """
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        """
        :param BaseExpr expr:
        :rtype: BaseExpr
        """
        raise NotImplementedError("Not Implemented")


set_pt_int_mods = {"short", "long"}
dct_pt_s_type_codes = {
    "int": INT_I,
    "float": FLT_F,
    "double": FLT_D,
    "void": TYP_VOID,
    "auto": TYP_AUTO,
    "char": INT_C,
    "char16_t": INT_C16,
    "char32_t": INT_C32,
    "wchar_t": INT_WC,
    "bool": TYP_BOOL
}


def get_bc_conv_bits(typ):
    """
    :param BaseType typ:
    :rtype: int
    """
    out_bits = None
    typ = get_base_prim_type(typ)
    if typ.type_class_id == TYP_CLS_PRIM:
        assert isinstance(typ, PrimitiveType)
        sz_cls = typ.size.bit_length() - 1
        if 1 << sz_cls != typ.size or sz_cls > 3:
            raise TypeError("Bad Primitive Type Size: %u for %r" % (typ.size, typ))
        if typ.typ in INT_TYPE_CODES:
            out_bits = sz_cls << 1
            out_bits |= int(typ.sign)
        elif typ.typ in FLT_TYPE_CODES:
            sz_cls -= 1
            out_bits = sz_cls | 0x08
    elif typ.type_class_id == TYP_CLS_QUAL:
        assert isinstance(typ, QualType)
        if typ.qual_id == QualType.QUAL_PTR:
            out_bits = 3
    if out_bits is None:
        raise TypeError("Cannot cast to Type %s" % repr(typ))
    return out_bits


class PrimitiveType(BaseType):
    def get_expr_arg_type(self, expr):
        """
        :param BaseExpr expr:
        :rtype: BaseExpr
        """
        raise NotImplementedError("Not Implemented")

    type_class_id = TYP_CLS_PRIM
    # Takes lists like (does not take access specifiers
    # for LL, L, C, WC, C16, C32, S: int is optional
    #   ["unsigned", "long", "long", "int"] -> Sign=False, Size=LL_Sz
    #   ["unsigned", "long", "long"] --------> Sign=False, Size=LL_Sz
    #   ["unsigned", "long", "int"] ---------> Sign=False, Size=L_Sz
    #   ["unsigned", "char", "int"] ---------> Sign=False, Size=C_Sz
    #   ["unsigned", "char"] ----------------> Sign=False, Size=C_Sz
    #   ["unsigned", "long"] ----------------> Sign=False, Size=L_Sz
    #   ["unsigned", "int"] -----------------> Sign=False, Size=I_Sz
    #   ["signed", "long", "long", "int"] ---> Sign=True,  Size=LL_Sz
    #   ["signed", "long", "long"] ----------> Sign=True,  Size=LL_Sz
    #   ["signed", "long", "int"] -----------> Sign=True,  Size=L_Sz
    #   ["signed", "char", "int"] -----------> Sign=True,  Size=C_Sz
    #   ["signed", "char"] ------------------> Sign=True,  Size=C_Sz
    #   ["signed", "long"] ------------------> Sign=True,  Size=L_Sz
    #   ["signed", "int"] -------------------> Sign=True,  Size=I_Sz
    #   ["long", "long", "int"] -------------> Sign=True,  Size=LL_Sz
    #   ["long", "long"] --------------------> Sign=True,  Size=LL_Sz
    #   ["char", "int"] ---------------------> Sign=CSIGN, Size=C_Sz
    #   ["long", "int"] ---------------------> Sign=True,  Size=L_Sz
    #   ["char"] ----------------------------> Sign=CSIGN, Size=C_Sz
    #   ["long"] ----------------------------> Sign=True,  Size=L_Sz
    #   ["int"] -----------------------------> Sign=True,  Size=I_Sz

    @classmethod
    def get_size_l_type(cls, is_sign=False):
        return PrimitiveType.from_type_code(INT_LL, -1 if is_sign else 1)
    lst_user_str_map = [
        ["int"],  # "INT_I",
        ["long"],  # "INT_L",
        ["long", "long"],  # "INT_LL",
        ["short"],  # "INT_S",
        ["char"],  # "INT_C",
        ["char16_t"],  # "INT_C16",
        ["char32_t"],  # "INT_C32",
        ["wchar_t"],  # "INT_WC",
        ["float"],  # "FLT_F",
        ["double"],  # "FLT_D",
        ["long", "double"],  # "FLT_LD",
        ["bool"],  # "TYP_BOOL",
        ["void"],  # "TYP_VOID",
        ["auto"],  # "TYP_AUTO"
    ]
    mangle_captures = {
        "v": (TYP_VOID, 0),
        "b": (TYP_BOOL, 0),
        "w": (INT_WC, 1),  # gcc calls it plain old wchar_t
        "h": (INT_WC, -1),  # gcc calls it unsigned char
        "a": (INT_C, -1),
        "c": (INT_C, 1),  # gcc calls it plain old char
        "s": (INT_S, -1),
        "t": (INT_S, 1),
        "i": (INT_I, -1),
        "j": (INT_I, 1),
        "l": (INT_L, -1),
        "m": (INT_L, 1),
        "x": (INT_LL, -1),
        "y": (INT_LL, 1),
        # "n": ["__int128"],
        # "o": ["unsigned", "__int128"],
        # "e": ["short", "float"], # gcc __float80, but here is __float16
        "f": (FLT_F, 0),
        "d": (FLT_D, 0),
        "g": (FLT_LD, 0),  # __float128
        "D": None,
        "Ds": (INT_C16, -1),
        "Dt": (INT_C16, 1),
        "Di": (INT_C32, -1),
        "Dj": (INT_C32, 1)}
    inv_mangle_captures = {
        (INT_I, True): "i",
        (INT_I, False): "j",
        (INT_L, True): "l",
        (INT_L, False): "m",
        (INT_LL, True): "x",
        (INT_LL, False): "y",
        (INT_S, True): "s",
        (INT_S, False): "t",
        (INT_C, True): "a",
        (INT_C, False): "c",
        (INT_C16, True): "Ds",
        (INT_C16, False): "Dt",
        (INT_C32, True): "Di",
        (INT_C32, False): "Dj",
        (INT_WC, False): "w",
        (INT_WC, True): "h",
        (FLT_F, True): "f",
        (FLT_D, True): "d",
        (FLT_LD, True): "g",
        (TYP_BOOL, False): "b",
        (TYP_VOID, False): "v"}

    @classmethod
    def from_mangle(cls, s, c):
        code = ""
        while s[c].isupper() and c < len(s):
            code += s[c]
            c += 1
        code += s[c]
        c += 1
        typ, signed = cls.mangle_captures[code]
        return PrimitiveType.from_type_code(typ, signed), c

    def to_mangle_str(self, top_decl=False):
        return PrimitiveType.inv_mangle_captures[(self.typ, self.sign)]

    @classmethod
    def from_str_name(cls, str_name):
        """
        :param list[str] str_name:
        :rtype: PrimitiveType
        """
        signed = 0
        lst_int_mods = []
        typ = None
        for s in str_name:
            if s in BASE_TYPE_MODS:
                if signed == 0:
                    signed = -1 if s == "signed" else 1
                else:
                    raise SyntaxError("Cannot specify more than one signed specifier")
            elif s in dct_pt_s_type_codes:
                if typ is not None:
                    raise SyntaxError("Cannot use more than one single type: '%s' and '%s'" % (typ, s))
                typ = dct_pt_s_type_codes[s]
            elif s in set_pt_int_mods:
                lst_int_mods.append(s)
            else:
                raise SyntaxError("Unexpected Token '%s'" % s)
        if typ is None:
            typ = INT_I
        if signed != 0 and (typ == TYP_BOOL or typ not in INT_TYPE_CODES):
            raise SyntaxError("Unexpected signed specifier for %s" % LST_TYPE_CODES[typ])
        for IntMod in lst_int_mods:
            if IntMod == "long":
                if typ == INT_I:
                    typ = INT_L
                elif typ == INT_L:
                    typ = INT_LL
                elif typ == FLT_D:
                    typ = FLT_LD
                else:
                    raise SyntaxError("Unexpected int modifier '%s' for %s" % (IntMod, LST_TYPE_CODES[typ]))
            elif IntMod == "short":
                if typ == INT_I:
                    typ = INT_S
                else:
                    raise SyntaxError("Unexpected int modifier '%s' for %s" % (IntMod, LST_TYPE_CODES[typ]))
        return cls.from_type_code(typ, signed)

    @classmethod
    def from_type_code(cls, typ, signed=0):
        """
        :param int typ:
        :param int signed: -1, 0 or 1 representing the signed-ness
        :rtype: PrimitiveType
        """
        size, sign = SIZE_SIGN_MAP[typ]
        if signed != 0:
            if typ in FLT_TYPE_CODES or typ in [TYP_VOID, TYP_BOOL]:
                raise TypeError(
                    "Cannot Explicitly specify the signed-ness for Type=%s" % LST_TYPE_CODES[typ])
            sign = signed < 0
        # str_name = cls.mangle_captures[cls.inv_mangle_captures[(typ, sign)]]
        return PrimitiveType(typ, sign)

    def to_user_str(self):
        return " ".join(self.get_str_name())

    def get_ctor_fn_types(self):
        return [
            make_void_fn(x) for x in [
                [],
                [self]
            ]
        ]

    def __init__(self, typ, sign):
        """
        :param int typ:
        :param bool sign:
        """
        self.sign = sign
        self.typ = typ
        self.size = SIZE_SIGN_MAP[typ][0]

    def get_str_name(self, short=True):
        assert short
        lst = list(PrimitiveType.lst_user_str_map[self.typ])
        if self.sign != SIZE_SIGN_MAP[self.typ][1]:
            lst.insert(0, "signed" if self.sign else "unsigned")
        return lst

    def pretty_repr(self):
        return ["PrimitiveType", ".", "from_type_code", "("] + [
            LST_TYPE_CODES[self.typ],
            ",",
            "0" if SIZE_SIGN_MAP[self.typ][1] == self.sign else ("-1" if self.sign else "1"),
            ")"]

    def compile_var_init(self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param list[BaseExpr|CurlyStmnt] init_args:
        :param CompileContext context:
        :param VarRef ref:
        :param LocalCompileData|None cmpl_data:
        :param list[(BaseType,BaseLink)]|None temp_links:
        """
        # TODO: result allocation for temp links of expressions used as init_args
        # actually maybe not
        sz_var = size_of(self)
        if sz_var == 0:
            print("SizeOf(%s) == 0" % get_user_str_from_type(self))
        if ref.ref_type == VAR_REF_TOS_NAMED:
            assert isinstance(ref, VarRefTosNamed)
            ctx_var = ref.ctx_var
            name = None
            is_local = True
            if ctx_var is not None:
                assert isinstance(ctx_var, ContextVariable)
                name = ctx_var.get_link_name()
                is_local = ctx_var.parent.is_local_scope()
            if len(init_args) > 1:
                raise TypeError("Cannot instantiate primitive types with more than one argument")
            if is_local:
                assert cmpl_data is not None, "Expected cmpl_data to not be None for LOCAL"
                if len(init_args) == 0:
                    sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                    cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
                else:
                    expr = init_args[0]
                    typ = expr.t_anot
                    src_pt = get_base_prim_type(typ)
                    src_vt = get_value_type(src_pt)
                    assert compare_no_cvr(self, src_vt), "self = %s, SrvVT = %s" % (
                        get_user_str_from_type(self), get_user_str_from_type(src_vt)
                    )
                    sz = compile_expr(cmpl_obj, expr, context, cmpl_data, src_pt, temp_links)
                    if src_pt is src_vt:
                        assert sz == sz_var
                    else:
                        assert sz == 8
                        sz_cls = (sz_var.bit_length() - 1)
                        assert sz_var == (1 << sz_cls)
                        cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                if ctx_var is not None:
                    cmpl_data.put_local(ctx_var, name, sz_var, None, True)
            else:
                assert cmpl_data is None, "Expected cmpl_data to be None for GLOBAL"
                assert isinstance(cmpl_obj, Compilation)
                assert ctx_var is not None
                assert isinstance(ctx_var, ContextVariable)
                assert name is not None
                cmpl_obj1 = cmpl_obj.spawn_compile_object(CMPL_T_GLOBAL, name)
                cmpl_obj1.memory.extend([0] * sz_var)
                if len(init_args) == 1:
                    link = cmpl_obj.get_link(name)
                    src_pt = get_base_prim_type(init_args[0].t_anot)
                    src_vt = get_value_type(src_pt)
                    err0 = "Expected Expression sz == %s, but %u != %u (name = %r, linkName = '%s', expr = %r)"
                    if src_pt is src_vt:
                        sz = compile_expr(cmpl_obj, init_args[0], context, cmpl_data, src_vt, temp_links)
                        assert sz == sz_var, err0 % ("sz_var", sz, sz_var, ctx_var.name, name, init_args[0])
                    else:
                        sz = compile_expr(cmpl_obj, init_args[0], context, cmpl_data, src_pt, temp_links)
                        assert sz == 8, err0 % ("sizeof(void*)", sz, 8, ctx_var.name, name, init_args[0])
                        sz_cls = sz_var.bit_length() - 1
                        assert sz_var == 1 << sz_cls
                        cmpl_obj.memory.extend([
                            BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                    link.emit_stor(cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic)
            return sz_var
        elif ref.ref_type == VAR_REF_LNK_PREALLOC:
            assert isinstance(ref, VarRefLnkPrealloc)
            if len(init_args) == 0:
                return sz_var
            link = ref.lnk
            sz = compile_expr(
                cmpl_obj, CastOpExpr(self, init_args[0], CastOpExpr.CAST_IMPLICIT), context, cmpl_data)
            assert sz == sz_var
            link.emit_stor(cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic)
            return sz_var
        else:
            raise TypeError("Unrecognized VarRef: %s" % repr(ref))

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        return -1

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param BaseExpr expr:
        :param CompileContext context:
        :param LocalCompileData|None cmpl_data:
        :param list[(BaseType,BaseLink)]|None temp_links:
        """
        from_type = get_value_type(expr.t_anot)
        err_msg = "error with expression type and size"
        err_msg += "\n  sz = %u\n  size_of(from_type) = %u\n  expr = %s\n  from_type = %s\n  self = %s"
        sz = compile_expr(cmpl_obj, expr, context, cmpl_data, from_type, temp_links)
        assert sz == size_of(from_type), err_msg % (
            sz,
            size_of(from_type),
            format_pretty(expr).replace("\n", "\n  "),
            format_pretty(from_type).replace("\n", "\n  "),
            format_pretty(self).replace("\n", "\n  ")
        )
        sz_cls = self.size.bit_length() - 1
        if 1 << sz_cls != self.size or sz_cls > 3:
            raise TypeError("Bad Primitive Type Size: %u for %r" % (self.size, self))
        if self.typ in INT_TYPE_CODES:
            out_bits = sz_cls << 1
            out_bits |= int(self.sign)
        elif self.typ in FLT_TYPE_CODES:
            sz_cls -= 1
            out_bits = sz_cls | 0x08
        else:
            raise TypeError("Cannot cast to Type %s" % repr(self))
        if from_type.type_class_id == TYP_CLS_PRIM:
            assert isinstance(from_type, PrimitiveType)
            if from_type.typ in INT_TYPE_CODES:
                sz_cls = from_type.size.bit_length() - 1
                if 1 << sz_cls != from_type.size or sz_cls > 3:
                    raise TypeError("Bad Primitive Type Size: %u for %r" % (from_type.size, from_type))
                inp_bits = sz_cls << 1
                inp_bits |= int(from_type.sign)
            elif from_type.typ in FLT_TYPE_CODES:
                sz_cls = from_type.size.bit_length() - 2
                inp_bits = sz_cls | 0x08
            else:
                raise TypeError("Cannot cast from Type %s" % repr(from_type))
        elif from_type.type_class_id == TYP_CLS_QUAL:
            assert isinstance(from_type, QualType)
            if from_type.qual_id == QualType.QUAL_PTR:
                assert sz == 8
                inp_bits = 0x06
            else:
                raise TypeError("Cannot cast from Type %s" % repr(from_type))
        else:
            raise TypeError("Cannot cast from Type %s" % repr(from_type))

        if self.typ == TYP_BOOL:
            emit_load_i_const(cmpl_obj.memory, 0, False, 0)
            cmpl_obj.memory.extend([
                BC_CONV, (inp_bits << 4),  # input bits (for this BC_CONV, not inp_bits) are all zero
                BC_NOP,
                BC_NE0
            ])
            code = (BC_FCMP_2 if inp_bits & 0x08 else BC_CMP1) + (inp_bits & 0x7)
            assert BC_FCMP_2 <= code <= BC_FCMP_16 or BC_CMP1 <= code <= BC_CMP8S, "GOT: %u" % code
            cmpl_obj.memory[-2] = code
        else:
            cmpl_obj.memory.extend([
                BC_CONV, inp_bits | (out_bits << 4)])
        return self.size


def setup_temp_links(cmpl_obj, expr, context, cmpl_data=None):
    """
    :param BaseCmplObj cmpl_obj:
    :param BaseExpr expr:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    :rtype: list[(BaseType,BaseLink)]
    """
    if context.Optimize != OPT_CODE_GEN:
        raise ValueError("context must be in the optimal representation for Code Generation (Optimize = OPT_CODE_GEN)")
    temp_links = [] if expr.temps is None else ([None] * len(expr.temps))
    """:type: list[(BaseType,BaseLink)]"""
    assert expr.temps is not None or len(temp_links) == 0, "len(temp_links) must be 0 if expr.temps is None"
    sz_add = 0
    for c in range(len(temp_links)):
        sz_var = size_of(expr.temps[c])
        temp_links[c] = (expr.temps[c], LocalRef.from_bp_off_pre_inc(cmpl_data.bp_off, sz_var))
        sz_add += sz_var
    if sz_add == 0:
        return temp_links
    sz_cls = emit_load_i_const(cmpl_obj.memory, sz_add, False)
    cmpl_obj.memory.extend([
        BC_ADD_SP1 + sz_cls
    ])
    cmpl_data.bp_off += sz_add
    return temp_links


def tear_down_temp_links(cmpl_obj, temp_links, expr, context, cmpl_data=None):
    """
    :param BaseCmplObj cmpl_obj:
    :param list[(BaseType,BaseLink)] temp_links:
    :param BaseExpr expr:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    """
    del expr
    c = len(temp_links)
    sz_reset = 0
    while c > 0:
        c -= 1
        assert isinstance(c, int)
        typ, link = temp_links[c]
        typ.compile_var_de_init(cmpl_obj, context, VarRefLnkPrealloc(link), cmpl_data)
        sz_reset += size_of(typ)
    if sz_reset:
        sz_cls = emit_load_i_const(cmpl_obj.memory, sz_reset, False)
        cmpl_obj.memory.extend([
            BC_RST_SP1 + sz_cls
        ])


def compile_conv_general(cmpl_obj, conv_expr, context, cmpl_data=None, temp_links=None):
    """
    :param BaseCmplObj cmpl_obj:
    :param CastOpExpr conv_expr:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    :param list[(BaseType,BaseLink)]|None temp_links:
    """
    expr = conv_expr.expr
    typ = conv_expr.type_name
    src_pt, src_vt, is_src_ref = get_tgt_ref_type(expr.t_anot)
    tgt_pt, tgt_vt, is_tgt_ref = get_tgt_ref_type(typ)
    owns_temps = temp_links is None
    sz = 0
    temps_off = conv_expr.temps_off
    if owns_temps:
        temp_links = setup_temp_links(cmpl_obj, conv_expr, context, cmpl_data)
    if compare_no_cvr(src_vt, tgt_vt):
        if is_src_ref and is_tgt_ref:  # do nothing, just pass the reference along
            assert compare_no_cvr(src_vt, tgt_vt)
            sz = compile_expr(cmpl_obj, expr, context, cmpl_data, tgt_pt, temp_links)
            assert sz == 8
        elif is_tgt_ref:  # DO temporary materialization
            assert not is_src_ref
            assert len(temp_links) == len(conv_expr.temps), "temp_links = %r, ConvExpr.temps = %r" % (
                temp_links, conv_expr.temps
            )
            temp_type, temp_link = temp_links[temps_off]
            temp_type.compile_var_init(cmpl_obj, [expr], context, VarRefLnkPrealloc(temp_link), cmpl_data, temp_links)
            temp_link.emit_lea(cmpl_obj.memory)
            sz = 8
        elif is_src_ref:  # Do argument initialization given a reference
            sz = tgt_pt.compile_var_init(cmpl_obj, [expr], context, VarRefTosNamed(None), cmpl_data, temp_links)
        else:  # Do argument initialization given a value
            # for now do nothing (the source instance is the target instance)
            # TODO: maybe need to change this?
            sz = compile_expr(cmpl_obj, expr, context, cmpl_data, tgt_pt, temp_links)
    else:
        if is_src_ref and is_tgt_ref:  # do nothing, just pass the reference along
            raise TypeError("cannot do reference to reference cast")
        elif is_tgt_ref:  # DO temporary materialization
            raise TypeError("cannot do temporary materialization passing the wrong type of argument")
        elif is_src_ref:  # Do argument initialization given a reference
            if src_vt.type_class_id == TYP_CLS_QUAL and tgt_vt.type_class_id == TYP_CLS_QUAL:
                assert isinstance(src_vt, QualType)
                assert isinstance(tgt_vt, QualType)
                if tgt_vt.qual_id == QualType.QUAL_PTR:
                    if src_vt.qual_id == QualType.QUAL_ARR:
                        if src_vt.ext_inf is not None and compare_no_cvr(src_vt.tgt_type, tgt_vt.tgt_type):
                            sz = compile_expr(cmpl_obj, expr, context, cmpl_data, None, temp_links)
                            assert sz == 8
                    elif src_vt.qual_id == QualType.QUAL_FN:
                        if compare_no_cvr(src_vt, tgt_vt.tgt_type):
                            sz = compile_expr(cmpl_obj, expr, context, cmpl_data, None, temp_links)
                            assert sz == 8
            err0 = "cannot do argument initialization given a reference to a different type expr.t_anot = %s, Type = %s"
            if sz == 0:
                raise TypeError(err0 % (get_user_str_from_type(expr.t_anot), get_user_str_from_type(typ)))
        else:  # Do argument initialization given a value
            # for now do nothing (the source instance is the target instance)
            sz = typ.compile_conv(cmpl_obj, expr, context, cmpl_data, temp_links)
    if owns_temps:
        tear_down_temp_links(cmpl_obj, temp_links, conv_expr, context, cmpl_data)
    return sz


# TODO: fix function overloading (CodeGen and Parse-time resolution)


def try_get_as_name(tokens, c, end, context):
    """
    :param list[ParseClass] tokens:
    :param int c:
    :param int end:
    :param CompileContext context:
    """
    del context
    start = c
    if tokens[c].type_id != CLS_NAME and tokens[c].str != "::":
        return None, start
    c += 1
    while c < end:
        if tokens[c-1].type_id == CLS_NAME:
            if tokens[c].str != "::":
                return tokens[start:c], c
            c += 1
        elif tokens[c-1].str == "::":
            if tokens[c].type_id != CLS_NAME or tokens[c].str in KEYWORDS:
                return tokens[start:c], c
            c += 1
    return tokens[start:c], c


def flip_dct(dct):
    """
    :param dict[T,U] dct:
    :rtype: dict[U,T]
    """
    return {dct[k]: k for k in dct}


class ExprLocalVars(object):
    """
    :type bp_off: int
    :type vars: list[(LocalRef, BaseType)]
    """
    def __init__(self, cmpl_data):
        """
        :param LocalCompileData cmpl_data:
        """
        self.bp_off = cmpl_data.bp_off
        self.vars = []

    def add_local(self, typ):
        """
        :param BaseType typ:
        :rtype: int
        """
        rtn = len(self.vars)
        sz_var = size_of(typ, False)
        self.vars.append((LocalRef.from_bp_off_pre_inc(self.bp_off, sz_var), typ))
        return rtn

    def merge(self, other):
        """
        :param ExprLocalVars other:
        :rtype: (ExprLocalVars, int)
        """


class QualType(BaseType):
    type_class_id = TYP_CLS_QUAL
    QUAL_DEF = 0
    QUAL_CONST = 1
    QUAL_PTR = 2
    QUAL_VOLATILE = 3
    QUAL_REG = 4
    QUAL_REF = 5
    QUAL_ARR = 6  # basically a pointer but defines how it is allocated (right where it is declared if not an argument)
    QUAL_FN = 7
    QUAL_CL_FN = 8
    QUAL_CTOR = 9
    QUAL_DTOR = 10
    QUAL_Lst = list(map(lambda x: "QUAL_" + x, "DEF CONST PTR VOLATILE REG REF ARR FN CL_FN CTOR DTOR".split(" ")))
    QUAL_Dct = {
        "auto": QUAL_DEF,
        "const": QUAL_CONST,
        "*": QUAL_PTR,
        "volatile": QUAL_VOLATILE,
        "register": QUAL_REG,
        "&": QUAL_REF,
        "[": QUAL_ARR,
        "(": QUAL_FN
    }
    mangle_captures = {
        "C": QUAL_CONST, "P": QUAL_PTR, "V": QUAL_VOLATILE,
        "S": QUAL_REG, "R": QUAL_REF, "A": QUAL_ARR, "F": QUAL_FN,
        "N": QUAL_CTOR, "r": QUAL_DTOR, "M": QUAL_CL_FN}
    dct_qual_id_mangle = flip_dct(mangle_captures)
    mangle_captures["Z"] = QUAL_FN
    mangle_captures["z"] = QUAL_FN

    @classmethod
    def from_mangle(cls, s, c):
        qual_id = cls.mangle_captures[s[c]]
        c += 1
        if qual_id == QualType.QUAL_FN:
            tgt_type = None
            if s[c] == "Z":
                c += 1
                tgt_type, c = from_mangle(s, c)
            ext_inf = []
            while c < len(s) and s[c] != "z":
                typ, c = from_mangle(s, c)
                ext_inf.append(typ)
            if c < len(s):
                c += 1
            return QualType(qual_id, tgt_type, ext_inf), c
        else:
            tgt_type, c = from_mangle(s, c)
            return QualType(qual_id, tgt_type), c

    def get_ctor_fn_types(self):
        if self.qual_id in {QualType.QUAL_REG, QualType.QUAL_CONST, QualType.QUAL_VOLATILE, QualType.QUAL_DEF}:
            return self.tgt_type.get_ctor_fn_types()
        elif self.qual_id == QualType.QUAL_REF:
            return [
                make_void_fn(x) for x in [
                    [self]
                ]
            ]
        elif self.qual_id == QualType.QUAL_PTR:
            return [
                make_void_fn(x) for x in [
                    [],
                    [self]
                ]
            ]
        elif self.qual_id == QualType.QUAL_ARR:
            return [
                make_void_fn(x) for x in [
                    [],
                    [QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, self))],
                    [QualType(QualType.QUAL_PTR, self.tgt_type)]
                ]
            ]
        elif self.qual_id in [QualType.QUAL_FN, QualType.QUAL_CTOR, QualType.QUAL_CL_FN, QualType.QUAL_DTOR]:
            return []
        else:
            return super(QualType, self).get_ctor_fn_types()

    def __init__(self, qual_id, tgt_type, ext_inf=None):
        """
        :param int qual_id:
        :param BaseType tgt_type:
        :param None|int|list[BaseType] ext_inf:
        """
        self.qual_id = qual_id
        self.tgt_type = tgt_type
        self.ext_inf = ext_inf

    def pretty_repr(self):
        c_name = self.__class__.__name__
        rtn = [c_name, "(", c_name, ".", self.QUAL_Lst[self.qual_id], ","] + get_pretty_repr(self.tgt_type) + [")"]
        if self.ext_inf is not None:
            rtn[-1:-1] = [","] + get_pretty_repr(self.ext_inf)
        return rtn

    def to_mangle_str(self, top_decl=False):
        ch = QualType.dct_qual_id_mangle[self.qual_id]
        if self.qual_id != QualType.QUAL_FN and self.qual_id in QualType.dct_qual_id_mangle:
            return ch + self.tgt_type.to_mangle_str()
        elif self.qual_id == QualType.QUAL_FN:
            rtn = ch
            if not top_decl:
                rtn += "Z" + self.tgt_type.to_mangle_str()
            return rtn + "".join(map(lambda x: x.to_mangle_str(), self.ext_inf)) + "z"
        else:
            raise TypeError("Unrecognized qual_id = %u" % self.qual_id)

    def to_user_str(self):
        s = "<UNKNOWN %u> "
        if self.qual_id == QualType.QUAL_DEF:
            s = "auto "
        elif self.qual_id == QualType.QUAL_CONST:
            s = "const "
        elif self.qual_id == QualType.QUAL_PTR:
            s = "pointer to "
        elif self.qual_id == QualType.QUAL_VOLATILE:
            s = "volatile "
        elif self.qual_id == QualType.QUAL_REG:
            s = "register "
        elif self.qual_id == QualType.QUAL_REF:
            s = "reference to "
        elif self.qual_id == QualType.QUAL_ARR:
            s = "array of "
            if self.ext_inf is not None:
                s += "%u " % self.ext_inf
        elif self.qual_id == QualType.QUAL_FN:
            s = "function (%s) -> " % ", ".join(map(get_user_str_from_type, self.ext_inf))
        else:
            s %= self.qual_id
        s += get_user_str_from_type(self.tgt_type)
        if self.qual_id == QualType.QUAL_FN:
            s = "(" + s + ")"
        return s

    def get_expr_arg_type(self, expr):
        """
        :param BaseExpr expr:
        :rtype: BaseExpr
        """
        if expr.t_anot is None:
            raise TypeError("Expected Expression to have a type")
        if self.qual_id == QualType.QUAL_REF:
            if expr.t_anot.type_class_id != TYP_CLS_QUAL:
                pass
            if not compare_no_cvr(self.tgt_type, get_value_type(expr.t_anot)):
                raise TypeError("Bad Reference: %r, %r" % (self, expr.t_anot))

        else:
            if not compare_no_cvr(self, get_value_type(expr.t_anot)):
                raise TypeError("Bad Type: %r, %r" % (self, expr.t_anot))
        return CastOpExpr(self, expr, CastOpExpr.CAST_IMPLICIT)

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param BaseExpr expr:
        :param CompileContext context:
        :param LocalCompileData|None cmpl_data:
        :param list[(BaseType,BaseLink)]|None temp_links:
        """
        from_type = expr.t_anot
        if from_type.type_class_id == TYP_CLS_PRIM:
            assert isinstance(from_type, PrimitiveType)
            if from_type.typ in INT_TYPE_CODES:
                sz_cls = from_type.size.bit_length() - 1
                if 1 << sz_cls != from_type.size or sz_cls > 3:
                    raise TypeError("Bad Primitive Type Size: %u for %r" % (from_type.size, self))
                inp_bits = sz_cls << 1
                inp_bits |= int(from_type.sign)
            elif from_type.typ in FLT_TYPE_CODES:
                sz_cls = from_type.size.bit_length() - 2
                inp_bits = sz_cls | 0x08
            else:
                raise TypeError("Cannot cast from Type %s" % repr(self))
            if self.qual_id == QualType.QUAL_PTR:
                out_bits = 3
            else:
                raise TypeError("Cannot cast from Type %r to %r" % (from_type, self))
            if inp_bits != out_bits:
                cmpl_obj.memory.extend([
                    BC_CONV, inp_bits | (out_bits << 4)
                ])
            return 8
        elif from_type.type_class_id == TYP_CLS_QUAL:
            assert isinstance(from_type, QualType)
            from_vt = from_type.tgt_type if from_type.qual_id == QualType.QUAL_REF else from_type
            if self.qual_id == QualType.QUAL_REF and from_type.qual_id == QualType.QUAL_REF:
                return compile_expr(cmpl_obj, expr, context, cmpl_data, from_type, temp_links)
            elif self.qual_id == QualType.QUAL_PTR:
                if from_vt.qual_id == QualType.QUAL_PTR:
                    return compile_expr(cmpl_obj, expr, context, cmpl_data, from_vt, temp_links)
                elif from_vt.qual_id == QualType.QUAL_ARR:
                    # TODO: maybe type_coerce = from_type (the reference)
                    return compile_expr(cmpl_obj, expr, context, cmpl_data, self, temp_links)
                elif from_type.qual_id == QualType.QUAL_REF and is_fn_type(from_vt):
                    # assert CompareNoCVR(from_type.tgt_type, self.tgt_type)
                    return compile_expr(cmpl_obj, expr, context, cmpl_data, from_type, temp_links)
        raise ValueError("Unhandled Cast Type: %r to %r" % (from_type, self))

    def compile_var_init(self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param list[BaseExpr|CurlyStmnt] init_args:
        :param CompileContext context:
        :param VarRef ref:
        :param LocalCompileData|None cmpl_data:
        :param list[(BaseType,BaseLink)]|None temp_links:
        """
        if len(init_args) > 1:
            raise SyntaxError("Invalid number of arguments for initialization of %s" % get_user_str_from_type(self))
        if len(init_args) == 0 and self.qual_id == QualType.QUAL_REF:
            raise ValueError("Cannot declare a reference without instantiating it")
        sz_var = size_of(self)
        ctx_var = None
        link = None
        name = None
        is_local = True
        cmpl_obj1 = None
        # Verification and Setup stage (for compilation)
        if ref.ref_type == VAR_REF_TOS_NAMED:
            assert isinstance(ref, VarRefTosNamed)
            ctx_var = ref.ctx_var
            if ctx_var is not None:
                assert isinstance(ctx_var, ContextVariable)
                if ctx_var.typ.type_class_id == TYP_CLS_MULTI:
                    assert isinstance(ctx_var, OverloadedCtxVar)
                    assert ctx_var.specific_ctx_vars is not None
                    for var in ctx_var.specific_ctx_vars:
                        if var.typ is self:
                            ctx_var = var
                            break
                    else:
                        raise NameError("Could not resolve overloaded variable '%s'" % ctx_var.name)
                    ref = VarRefTosNamed(ctx_var)
                assert isinstance(ctx_var, ContextVariable)
                name = ctx_var.get_link_name()
                is_local = ctx_var.parent.is_local_scope()
                if not is_local:
                    link = cmpl_obj.get_link(name)
            if self.qual_id == QualType.QUAL_FN:
                if is_local:
                    raise TypeError("Functions must be GLOBAL")
                assert isinstance(cmpl_obj, Compilation)
                if len(init_args) == 0:
                    return 0
                err0 = "Redefinition of function %s is not allowed"
                err1 = "Function %s cannot be defined with %s (only CurlyStmnt for now)"
                if name in cmpl_obj.objects:
                    raise ValueError(err0 % name)
                elif not isinstance(init_args[0], CurlyStmnt):
                    raise SyntaxError(err1 % (name, init_args[0].__class__.__name__))
                cmpl_obj1 = cmpl_obj.spawn_compile_object(CMPL_T_FUNCTION, name)
            elif not is_local:
                assert isinstance(cmpl_obj, Compilation)
                if ctx_var.mods != ContextVariable.MOD_EXTERN:
                    cmpl_obj1 = cmpl_obj.spawn_compile_object(CMPL_T_GLOBAL, name)
        elif ref.ref_type == VAR_REF_LNK_PREALLOC:
            assert isinstance(ref, VarRefLnkPrealloc)
            link = ref.lnk
            is_local = False
            if self.qual_id == QualType.QUAL_FN:
                raise TypeError("Functions must be NAMED")
        else:
            raise ValueError("Unrecognized VarRef (ref = %s)" % repr(ref))
        # Creation stage (in program)
        if self.qual_id in [QualType.QUAL_DEF, QualType.QUAL_CONST, QualType.QUAL_VOLATILE, QualType.QUAL_REG]:
            return self.tgt_type.compile_var_init(cmpl_obj, init_args, context, ref, cmpl_data, temp_links)
        elif self.qual_id in [QualType.QUAL_PTR, QualType.QUAL_REF, QualType.QUAL_ARR]:
            if len(init_args) == 1:
                expr = init_args[0]
                # assert CompareNoCVR(self, expr.t_anot), "self = %s, expr.t_anot = %s" % (
                #     GetUserStrFromType(self), GetUserStrFromType(expr.t_anot)
                # )
                sz = compile_expr(cmpl_obj, expr, context, cmpl_data, self, temp_links)
                assert sz == sz_var, "sz = %u, sz_var = %u, type_name = %r, expr = %r" % (sz, sz_var, self, expr)
            elif is_local:
                sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
        elif self.qual_id == QualType.QUAL_FN:
            assert cmpl_obj1 is not None
            the_arg = init_args[0]
            assert isinstance(the_arg, CurlyStmnt)
            cmpl_data1 = LocalCompileData()
            variadic = False
            off = -16
            fn_ctx = the_arg.context.parent
            assert isinstance(fn_ctx, LocalScope)
            assert not isinstance(self.ext_inf, int)
            assert self.ext_inf is not None
            res_link = None
            res_type = self.tgt_type
            if variadic:
                sz1 = 8  # sizeof(T*)
                res_link = IndirectLink(LocalRef.from_bp_off_post_inc(off, sz1))
                off -= 8
            for Param in self.ext_inf:
                assert isinstance(Param, (IdentifiedQualType, BaseType))
                sz1 = size_of(Param)
                if isinstance(Param, IdentifiedQualType):
                    ctx_var = fn_ctx.var_name_strict(Param.name)
                    assert isinstance(ctx_var, ContextVariable)
                    cmpl_data1.setitem(ctx_var.get_link_name(), (ctx_var, LocalRef.from_bp_off_post_inc(off, sz1)))
                off -= sz1
            if not variadic:
                sz1 = size_of(res_type)
                res_link = LocalRef.from_bp_off_post_inc(off, sz1)
                off -= sz1
            assert res_link is not None
            cmpl_data1.res_data = (res_type, res_link)
            compile_curly(cmpl_obj1, init_args[0], fn_ctx, cmpl_data1)
            cmpl_obj1.memory.extend([BC_RET])
            return len(cmpl_obj1.memory)
        else:
            raise TypeError("Unrecognized type: %s" % get_user_str_from_type(self))
        # storage stage (GLOBAL:in program/LOCAL: compiler)
        if is_local:
            assert cmpl_data is not None, "Expected cmpl_data to not be None for LOCAL"
            assert isinstance(cmpl_data, LocalCompileData)
            if ctx_var is not None:
                cmpl_data.put_local(ctx_var, name, sz_var, None, True)
        else:
            if ref.ref_type == VAR_REF_TOS_NAMED:
                assert cmpl_data is None, "Expected cmpl_data to be None for GLOBAL"
                assert isinstance(cmpl_obj, Compilation)
                assert cmpl_obj1 is not None
                assert ctx_var is not None
                cmpl_obj1.memory.extend([0] * sz_var)
            if len(init_args) == 1:
                assert link is not None
                link.emit_stor(cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic)
        return sz_var

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param CompileContext context:
        :param VarRef ref:
        :param LocalCompileData|None cmpl_data:
        :rtype: int
        """
        if self.qual_id in [QualType.QUAL_CONST, QualType.QUAL_REG, QualType.QUAL_DEF, QualType.QUAL_VOLATILE]:
            return self.tgt_type.compile_var_de_init(cmpl_obj, context, ref, cmpl_data)
        elif self.qual_id == QualType.QUAL_ARR:
            # if self.ext_inf is None: return -1
            # if ref.ref_type == VAR_REF_TOS_NAMED:
            return -1
        elif self.qual_id == QualType.QUAL_FN:
            raise TypeError("cannot destroy a function")
        # QUAL_REF, QUAL_PTR, QUAL_FN
        return -1


def get_value_type(typ, do_arr_to_ptr_decay=False):
    if isinstance(typ, (PrimitiveType, UnionType, ClassType, StructType)):
        return typ
    elif isinstance(typ, QualType):
        if typ.qual_id in [QualType.QUAL_CONST, QualType.QUAL_REG, QualType.QUAL_VOLATILE, QualType.QUAL_DEF]:
            return get_value_type(typ.tgt_type)
        elif typ.qual_id == QualType.QUAL_ARR:
            if do_arr_to_ptr_decay:
                return QualType(QualType.QUAL_PTR, typ.tgt_type)
            else:
                return typ
        elif typ.qual_id in [QualType.QUAL_FN, QualType.QUAL_PTR]:
            return typ
        elif typ.qual_id == QualType.QUAL_REF:
            return get_value_type(typ.tgt_type)
        else:
            raise ValueError("Unrecognized qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return get_value_type(typ.typ)
    else:
        raise TypeError("Unrecognized Type: %s" % repr(typ))


def get_user_str_from_type(typ):
    """
    :param BaseType|IdentifiedQualType typ:
    :rtype: str
    """
    return typ.to_user_str()


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


def get_base_type(tokens, c, end, context):
    """
    :param list[ParseClass] tokens:
    :param int c:
    :param int end:
    :param CompileContext context:
    :rtype (BaseType|None, int)
    """
    main_start = c
    str_name = []
    base_type = None
    is_prim = False
    while c < end:
        if tokens[c].type_id == CLS_NAME and tokens[c].str in KEYWORDS:
            meta_type_type = -1
            try:
                meta_type_type = META_TYPE_LST.index(tokens[c].str)
            except ValueError:
                pass
            if meta_type_type != -1:
                c += 1
                cls = MetaTypeCtors[meta_type_type](context)
                c = cls.build(tokens, c, end, context)
                cls = merge_type_context(cls, context)
                assert cls is not None, "ISSUE with MergeType_Context"
                if base_type is None and not is_prim:
                    base_type = cls
                else:
                    # raise ParsingError(tokens, c, "Cannot specify different typenames as one type")
                    return None, main_start
            elif tokens[c].str == "typename":
                c += 1
                base_name, c = try_get_as_name(tokens, c, end, context)
                if base_name is None:
                    raise ParsingError(tokens, c, "Expected name after 'typename'")
                name = "".join(map(tok_to_str, base_name))
                cls = context.scoped_get(name)
                if not cls.is_type():
                    raise ParsingError(tokens, c, "Expected a typename to follow 'typename', got %s" % name)
                if base_type is None and not is_prim:
                    base_type = cls.get_underlying_type()
                else:
                    raise ParsingError(tokens, c, "Cannot specify different typenames as one type")
            elif tokens[c].str in PRIM_TYPE_WORDS:
                str_name.append(tokens[c].str)
                is_prim = True
                c += 1
            elif tokens[c].str in MODIFIERS:
                str_name.append(tokens[c].str)
                c += 1
            else:
                # raise ParsingError(tokens, c, "Keyword not allowed in declaration")
                return None, main_start
        else:
            start = c
            base_name, c = try_get_as_name(tokens, c, end, context)
            if base_name is None and base_type is None and not is_prim:
                # raise ParsingError(tokens, c, "Expected name after 'typename'")
                return None, main_start
            elif base_name is None:
                break
            elif is_prim or base_type is not None:
                # v = context.ScopedGet_Strict("".join(map(TokToStr, base_name)))
                # if v is not None: raise ParsingError(tokens, c, "??Redefinition ?")
                c = start  # Do something about the name
                break
            elif not is_prim and base_type is None:
                v = context.scoped_get("".join(map(tok_to_str, base_name)))
                if v is None:
                    raise ParsingError(tokens, c, "Undefined Identifier")
                elif v.is_type():
                    base_type = v.get_underlying_type()
                else:
                    return None, main_start
            else:
                raise ParsingError(tokens, c, "Unrecognized if path")
    if is_prim:
        str_name.sort(key=lambda k: (
            2 if k in SINGLE_TYPES1 else (
                0 if k in BASE_TYPE_MODS else (
                    1 if k in INT_TYPES1 else 3))))
        c0 = len(str_name)
        while c0 > 0:
            c0 -= 1
            if str_name[c0] in PRIM_TYPE_WORDS:
                c0 += 1
                break
        base_type = PrimitiveType.from_str_name(str_name[:c0])
        # assert c0 == len(str_name), "expected c0 = len(str_name), c0=%u, str_name=%r" % (c0, str_name)
        str_name = str_name[c0:]
    if base_type is None:
        print("BASE_TYPE NONE:", tokens[c - 2])
    assert isinstance(base_type, BaseType), "type = %s" % base_type.__class__.__name__
    for s in str_name:
        base_type = QualType(QualType.QUAL_Dct[s], base_type)
    return base_type, c


def from_mangle(s, c):
    """
    :param str s:
    :param int c:
    :rtype: (BaseType, int)
    """
    if s[c] in QualType.mangle_captures:
        return QualType.from_mangle(s, c)
    elif s[c] in PrimitiveType.mangle_captures:
        return PrimitiveType.from_mangle(s, c)
    elif s[c] in ClassType.mangle_captures:
        return ClassType.from_mangle(s, c)
    elif s[c] in StructType.mangle_captures:
        return StructType.from_mangle(s, c)
    elif s[c] in UnionType.mangle_captures:
        return UnionType.from_mangle(s, c)
    elif s[c] in EnumType.mangle_captures:
        return EnumType.from_mangle(s, c)
    else:
        raise ValueError("Unrecognized mangle capture: '%s' at c = %u in %r" % (s[c], c, s))


def proc_typed_decl(tokens, c, end, context, base_type=None):
    # process the 'base' type before any parentheses, '*', '&', 'const', or 'volatile'
    if base_type is None:
        base_type, c = get_base_type(tokens, c, end, context)
        if base_type is None:
            return None, c
    rtn = base_type
    if not isinstance(rtn, IdentifiedQualType):
        rtn = IdentifiedQualType(None, rtn)
    s_start = c
    s_end = end
    i_type = 0  # inner type, 0: None, 1: '(' and ')', 2: name
    i_start = 0
    i_end = 0
    is_operator = False
    # collect tokens before the 'identifier' and place them in the pseudo-stack
    while c < end:
        if tokens[c].type_id == CLS_BRK_OP:
            if tokens[c].str == "(":
                s_end = c
                c += 1
                lvl = 1
                i_start = c
                while c < end and lvl > 0:
                    if tokens[c].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c].str in CLOSE_GROUPS:
                        lvl -= 1
                    c += 1
                i_end = c - 1
                i_type = 1
                break
        elif (
                (tokens[c].type_id == CLS_NAME and tokens[c].str not in {"const", "auto", "volatile", "register"}) or
                tokens[c].str == "::"):
            i_type = 2
            i_start = c
            s_end = c
            c += 1
            while c < end:
                if tokens[c - 1].type_id == CLS_NAME:
                    if tokens[c - 1].str == "operator":
                        if tokens[c].type_id == CLS_OPERATOR:
                            c += 1
                        elif tokens[c].type_id == CLS_BRK_OP:
                            if tokens[c].str == ",":
                                c += 1
                            elif tokens[c].str == "(":
                                c += 1
                                if tokens[c].str != ")":
                                    raise ParsingError(tokens, c, "Expected ')' for 'operator('")
                                c += 1
                            elif tokens[c].str == "[":
                                c += 1
                                if tokens[c].str != "]":
                                    raise ParsingError(tokens, c, "Expected ']' for 'operator['")
                                c += 1
                            else:
                                raise ParsingError(tokens, c, "Unrecognized operator found after operator keyword")
                        is_operator = True
                        break
                    elif tokens[c].str != "::":
                        break
                elif tokens[c - 1].str == "::":
                    if tokens[c].type_id != CLS_NAME:
                        raise ParsingError(tokens, c, "Expected name to follow '::'")
                    elif tokens[c].str in KEYWORDS:
                        raise ParsingError(tokens, c, "Unexpected keyword following '::'")
                c += 1
            i_end = c
            break
        c += 1
    # process items before the identifier starting from the higher index (like popping the pseudo-stack)
    c0 = s_end
    while c0 > s_start:
        c0 -= 1
        if tokens[c0].str in QualType.QUAL_Dct:
            rtn.add_qual_type(QualType.QUAL_Dct[tokens[c0].str])
        else:
            raise ParsingError(tokens, c0, "Unexpected token")
    # process items after the identifier by creating QualType instances
    while c < end:
        if tokens[c].type_id == CLS_BRK_OP:
            if tokens[c].str == "(":
                cancel = False
                lvl = 1
                ext_inf = []
                c += 1
                n_start = c
                if tokens[c].str == ")":
                    lvl = 0
                    c += 1
                elif tokens[c].str == "void" and tokens[c + 1].str == ")":
                    lvl = 0
                    c += 2
                while c < end and lvl > 0:
                    if tokens[c].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c].str in CLOSE_GROUPS:
                        lvl -= 1
                    if (lvl == 1 and tokens[c].str == ",") or lvl == 0:
                        n_end = c
                        c = n_start
                        n_decl, c = proc_typed_decl(tokens, c, n_end, context)
                        if n_decl is None:
                            cancel = True
                            break
                        if c != n_end:
                            # raise SyntaxError("incomplete type at tokens[%u].str = %r and tokens[%u].str = %r" % (
                            #     c, tokens[c].str, n_end, tokens[n_end].str))
                            raise ParsingError(tokens, c, "Incomplete Type")
                        ext_inf.append(n_decl)
                        n_start = n_end + 1
                    c += 1
                if not cancel:
                    rtn.add_qual_type(QualType.QUAL_FN, ext_inf)
                else:
                    c = n_start - 1
                    break
            elif tokens[c].str == "[":
                c += 1
                ext_inf = None
                if tokens[c].str != "]":
                    expr, c = get_expr(tokens, c, "]", end, context)
                    if not isinstance(expr, LiteralExpr):
                        raise ParsingError(tokens, c, "Expected Literal Integer for bounds of array")
                    else:
                        assert isinstance(expr, LiteralExpr)
                        if expr.t_lit != LiteralExpr.LIT_INT:
                            raise ParsingError(tokens, c, "Expected Literal Integer for bounds of array")
                        else:
                            radix = 10
                            if len(expr.v_lit) > 1 and expr.v_lit.startswith("0"):
                                ch = expr.v_lit[1].lower()
                                if ch.isdigit() or ch == 'o':
                                    radix = 8
                                elif ch == 'x':
                                    radix = 16
                                elif ch == 'b':
                                    radix = 2
                            ext_inf = int(expr.v_lit, radix)
                c += 1
                rtn.add_qual_type(QualType.QUAL_ARR, ext_inf)
            elif tokens[c].str == "," or tokens[c].str == ";" or tokens[c].str == "{":
                break
            else:
                raise ParsingError(tokens, c, "Unsupported Breaking operator")
        elif tokens[c].type_id == CLS_OPERATOR and tokens[c].str == "=":
            break
        else:
            raise ParsingError(tokens, c, "Unexpected token")
    if i_type == 1:
        c0 = c
        c = i_start
        rtn, c = proc_typed_decl(tokens, c, i_end, context, rtn)
        if c != i_end:
            # raise SyntaxError("incomplete type at tokens[%u].str = %r and tokens[%u].str = %r" % (
            #     c, tokens[c].str, i_end, tokens[i_end].str))
            raise ParsingError(tokens, c, "Incomplete Type")
        c = c0
    elif i_type == 2:
        rtn.name = "".join(map(tok_to_str, tokens[i_start:i_end]))
        rtn.is_op_fn = is_operator
    return rtn, c
# TODO: Things to think about
# TODO:   Typenames -> struct Pt {int x; int y;}; ...function {Pt a = {0, 12}; return 0;}
# TODO:     Figure out that 'Pt a = {0, 12};' is a declaration


class AsmStmnt(BaseStmnt):
    stmnt_type = STMNT_ASM

    def __init__(self, inner_asm=None):
        """
        :param list[str] inner_asm:
        """
        self.inner_asm = [] if inner_asm is None else inner_asm
        self.condition = None

    def build(self, tokens, c, end, context):
        """
        :param list[ParseClass] tokens:
        :param int c:
        :param int end:
        :param CompileContext context:
        :rtype: int
        """
        assert tokens[c].str == "asm"
        c += 1
        if tokens[c].str == "(":
            self.condition = {}
            c += 1
            while tokens[c].str != ")":
                tok_key = tokens[c]
                tok_eq = tokens[c + 1]
                tok_val = tokens[c + 2]
                assert tok_key.type_id == CLS_NAME and tok_eq.str == "=" and LiteralExpr.is_literal_token(tok_val), "expected syntax <name>=<literal>\n got %r, %r, %r" % (tok_key, tok_eq, tok_val)
                self.condition[tok_key.str] = LiteralExpr.literal_to_value(tok_val)
                c += 3
                if tokens[c].str == ",":
                    c += 1
            c += 1
        print(self.condition)
        assert tokens[c].str == "{", tokens[c].str
        c += 1
        while c < end:
            assert tokens[c].type_id == CLS_DBL_QUOTE, tokens[c]
            self.inner_asm.append(LiteralExpr.literal_to_value(tokens[c]))
            c += 1
            tok = tokens[c]
            if tok.str == ",":
                c += 1
                continue
            elif tok.str == "}":
                c += 1
                break
        assert tokens[c - 1].str == "}", tokens[c-2:c+2]
        return c

@try_catch_wrapper0
def get_stmnt(tokens, c, end, context):
    """
    :param list[ParseClass] tokens:
    :param int c:
    :param int end:
    :param CompileContext context:
    :rtype: (BaseStmnt, int)
    """
    start = c
    position = tokens[c].line, tokens[c].col
    pos = len(LST_STMNT_NAMES)
    if tokens[c].type_id == CLS_NAME and is_type_name_part(tokens[c].str, context):
        pos = STMNT_DECL
    if pos == len(LST_STMNT_NAMES):
        try:
            pos = LST_STMNT_NAMES.index(tokens[c].str)
        except ValueError:
            pass
    rtn = None
    if pos == STMNT_CURLY_STMNT:
        rtn = CurlyStmnt()
        c = rtn.build(tokens, c, end, context)
        if start == c:
            rtn = SemiColonStmnt()
            pos = len(LST_STMNT_NAMES)
            c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_IF:
        rtn = IfElse()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_WHILE:
        rtn = WhileLoop()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_FOR:
        rtn = ForLoop()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_RTN:
        rtn = ReturnStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_BRK:
        rtn = BreakStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_CONTINUE:
        rtn = ContinueStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_NAMESPACE:
        rtn = NamespaceStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_TYPEDEF:
        rtn = TypeDefStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_DECL:
        rtn = DeclStmnt()
        # print "Before c = %u, end = %u, STMNT_DECL" % (c, end)
        c = rtn.build(tokens, c, end, context)
        # print "After c = %u, end = %u, STMNT_DECL" % (c, end)
    elif pos == STMNT_ASM:
        rtn = AsmStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == STMNT_SEMI_COLON:
        # NOTE: Make sure that DeclStmnt would not work here
        rtn = SemiColonStmnt()
        # print "Before c = %u, end = %u, STMNT_SEMI_COLON" % (c, end)
        c = rtn.build(tokens, c, end, context)
        # print "After c = %u, end = %u, STMNT_SEMI_COLON" % (c, end)
    if rtn is None:
        raise LookupError("statement id: %u unaccounted for" % pos)
    rtn.position = position
    return rtn, c


class CurlyExpr(BaseExpr):
    expr_id = EXPR_CURLY

    def __init__(self, lst_expr=None):
        """
        :param list[BaseExpr]|None lst_expr:
        """
        self.lst_expr = lst_expr

    def init_temps(self, main_temps):
        main_temps = super(CurlyExpr, self).init_temps(main_temps)
        assert self.lst_expr is not None
        for expr in self.lst_expr:
            main_temps = expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.lst_expr) + [")"]

    def build(self, tokens, c, end, context):
        lvl = 1
        start = c
        c += 1
        comma_count = 0
        while c < end and lvl > 0:
            s = tokens[c].str
            if s in OPEN_GROUPS:
                lvl += 1
            elif s in CLOSE_GROUPS:
                lvl -= 1
            elif s == ",":
                comma_count += 1
            c += 1
        self.lst_expr = [None] * (comma_count + 1)
        n_expr = 0
        end_t = c
        end_p = end_t - 1
        c = start + 1
        while c < end_p and n_expr < len(self.lst_expr):
            self.lst_expr[n_expr], c = get_expr(tokens, c, ",", end_p, context)
            n_expr += 1
            c += 1
        for i in range(c - 5, c + 5):
            print("%03u: %s" % (i, tokens[i].str))
        assert c == end_t, "You need to verify this code, c = %u, end_t = %u" % (c, end_t)
        return c


def get_name_from_tokens(tokens, c):
    name = ""
    if tokens[c].type_id == CLS_NAME:
        name += tokens[c].str
        c += 1
    while tokens[c].str == "::":
        name += "::"
        c += 1
        if tokens[c].type_id == CLS_NAME:
            name += tokens[c].str
            if tokens[c].str == "operator":
                c += 1
                if tokens[c].type_id == CLS_OPERATOR:
                    name += tokens[c].str
                elif tokens[c].type_id == CLS_BRK_OP and tokens[c].str in ["[", "("]:
                    name += tokens[c].str
                    c += 1
                    if tokens[c].str not in ["[", "("]:
                        raise ParsingError(
                            tokens, c, "expected closing ')' or ']' after '%s'" % name.rsplit("::", 1)[-1]
                        )
                    name += tokens[c].str
        else:
            raise ParsingError(tokens, c, "Expected identifier after '::'")
        c += 1
    return name, c


class NameRefExpr(BaseExpr):
    expr_id = EXPR_NAME
    # init-args added for __repr__

    def __init__(self, name=None):
        """
        :param str|ContextVariable|None name:
        """
        self.is_op_fn = False
        if name is None:
            self.name = None
            self.ctx_var = None
        elif isinstance(name, str):
            self.name = name
            self.ctx_var = None
        else:
            assert isinstance(name, ContextVariable)
            self.name = name.name
            self.ctx_var = name
            self.is_op_fn = name.is_op_fn

    def build(self, tokens, c, end, context):
        assert c < end
        if tokens[c].type_id != CLS_NAME:
            raise ParsingError(tokens, c, "Expected a name")
        self.name, c = get_name_from_tokens(tokens, c)
        if self.name.rsplit("::", 1)[-1].startswith("operator"):
            self.is_op_fn = True
        ctx_var = context.scoped_get(self.name)
        if ctx_var is None:
            raise ParsingError(tokens, c, "Undefined Identifier '%s'" % self.name)
        if not isinstance(ctx_var, ContextVariable):
            raise ParsingError(tokens, c, "Expected Variable")
        self.ctx_var = ctx_var
        if ctx_var.typ.type_class_id != TYP_CLS_MULTI:
            self.t_anot = QualType(QualType.QUAL_REF, get_value_type(ctx_var.typ))
        return c

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.name) + [")"]


class LiteralExpr(BaseExpr):
    expr_id = EXPR_LITERAL
    LIT_INT = 0
    LIT_FLOAT = 1
    LIT_CHR = 2
    LIT_STR = 3
    LIT_BOOL = 4
    LIT_lst = ["LIT_INT", "LIT_FLOAT", "LIT_CHR", "LIT_STR", "LIT_BOOL"]

    @classmethod
    def is_literal_token(cls, tok):
        """
        :param ParseClass tok:
        :rtype: bool
        """
        return tok.type_id in LITERAL_TYPES or (tok.type_id == CLS_NAME and (tok.str == "true" or tok.str == "false"))

    @classmethod
    def literal_to_value(cls, tok):
        """
        :param ParseClass tok:
        :rtype: str|int|float
        """
        s = tok.str
        if tok.type_id == CLS_DBL_QUOTE:
            vals, uni_spec = cls.parse_str_lit(s)
            return "".join(map(chr, vals))
        elif tok.type_id == CLS_UNI_QUOTE:
            uni_spec = 0
            if s.startswith("u"):
                uni_spec = 2
            elif s.startswith("U"):
                uni_spec = 3
            elif s.startswith("b"):
                uni_spec = 1
            elif not s.startswith("'"):
                raise ValueError("Unrecognized literal prefix")
            s_q = s.find('\'') + 1
            e_q = s.rfind('\'')
            lst_res, c1 = cls.parse_char_part(s_q, s, uni_spec)
            if len(lst_res) != 1 or c1 < e_q:
                raise ValueError("Expected only one char")
            return lst_res[0]
        elif tok.type_id == CLS_BIN_INT:
            assert s.startswith("0b") or s.startswith("0B")
            return int(s[2:], 2)
        elif tok.type_id == CLS_DEC_INT:
            return int(s)
        elif tok.type_id == CLS_OCT_INT:
            assert s.startswith("0o") or s.startswith("0O") or s.startswith("0")
            return int(s[2:], 8)
        elif tok.type_id == CLS_HEX_INT:
            assert s.startswith("0x") or s.startswith("0X")
            return int(s[2:], 16)
        elif tok.type_id == CLS_FLOAT:
            return float(s)
        elif tok.type_id == CLS_NAME:
            if s == "true":
                return True
            elif s == "false":
                return False
            else:
                raise ValueError("Expected boolean")

    @classmethod
    def parse_char_part(cls, c, v_lit, uni_spec=0, backslash_strict=True):
        if uni_spec == 0:
            uni_spec = 1
        lst_res = []
        if v_lit[c] == '\\':
            c += 1
            pos = "btnvfr".find(v_lit[c])
            if pos != -1:
                lst_res.append(8 + pos)
                c += 1
            elif v_lit[c] in "\"\'\\":
                lst_res.append(ord(v_lit[c]))
                c += 1
            elif v_lit[c].lower() == 'x':
                c += 1
                res = StrToInt(v_lit[c: c + 2], 16)
                if isinstance(res, str):
                    raise SyntaxError("Expected 2-digit hex: %s" % res)
                assert isinstance(res, int)
                lst_res.append(res)
                c += 2
            elif v_lit[c] == 'u' and uni_spec >= 2:
                c += 1
                res = StrToInt(v_lit[c: c + 4], 16)
                if isinstance(res, str):
                    raise SyntaxError("Expected 4-digit hex: %s" % res)
                assert isinstance(res, int)
                lst_res.append(res)
                c += 4
            elif v_lit[c] == 'U' and uni_spec >= 3:
                c += 1
                res = StrToInt(v_lit[c: c + 8], 16)
                if isinstance(res, str):
                    raise SyntaxError("Expected 8-digit hex: %s" % res)
                assert isinstance(res, int)
                lst_res.append(res)
                c += 8
            else:
                v = ord(v_lit[c]) - ord('0')
                if 0 <= v <= 7:
                    c += 1
                    res = 0
                    n = 1
                    while 0 <= v <= 7 and n < 3:
                        res <<= 3
                        res |= v
                        v = ord(v_lit[c]) - ord('0')
                        c += 1
                        n += 1
                    lst_res.append(res)
                elif backslash_strict:
                    raise ValueError("invalid string escape %s" % v_lit[c - 1: c + 1])
                else:
                    lst_res.extend([ord(v_lit[c - 1]), ord(v_lit[c])])
                    c += 1
        else:
            lst_res.append(ord(v_lit[c]))
            c += 1
        return lst_res, c

    @classmethod
    def parse_str_lit(cls, v_lit, backslash_strict=True):
        s_q = v_lit.find('"')
        e_q = v_lit.rfind('"')
        uni_spec = 0
        is_raw = False
        uni_specs = ['B', 'b', 'u', 'U']
        for c in range(s_q):
            if v_lit[c] in uni_specs:
                if uni_spec != 0:
                    raise SyntaxError("cannot specify more than one string type specifier")
                uni_spec = uni_specs.index(v_lit[c])
                if uni_spec == 0:
                    uni_spec = 1
            elif v_lit[c].lower() == 'r':
                if is_raw:
                    raise SyntaxError("cannot specify 'r' more than once in string type specifier")
                is_raw = True
        lst_res = []
        c = s_q + 1
        while c < e_q:
            cur_res, c = cls.parse_char_part(c, v_lit, uni_spec, backslash_strict)
            lst_res.extend(cur_res)
        return lst_res, uni_spec

    # init-args added for __repr__
    def __init__(self, t_lit=None, v_lit=None):
        """
        :param int t_lit:
        :param str v_lit:
        """
        self.t_lit = t_lit
        self.v_lit = v_lit
        self.l_val = None

    def pretty_repr(self):
        c_name = self.__class__.__name__
        rtn = [c_name, "("]
        if isinstance(self.t_lit, int) and 0 <= self.t_lit < len(self.LIT_lst):
            rtn.extend([c_name, ".", self.LIT_lst[self.t_lit]])
        else:
            rtn.extend(get_pretty_repr(self.t_lit))
        rtn.extend([","] + get_pretty_repr(self.v_lit) + [")"])
        return rtn

    def build(self, tokens, c, end, context):
        del end
        del context
        s = tokens[c].str
        if not self.is_literal_token(tokens[c]):
            raise ParsingError(tokens, c, "Expected literal")
        if tokens[c].type_id in {CLS_DEC_INT, CLS_HEX_INT, CLS_BIN_INT, CLS_OCT_INT}:
            self.t_lit = LiteralExpr.LIT_INT
            end_pos = len(s)
            for c0 in range(len(s) - 1, -1, -1):
                if s[c0].isdigit() or ('a' <= s[c0].lower() <= 'f'):
                    end_pos = c0 + 1
                    break
            c0 = end_pos
            i_lvl = 0
            unsign = 0
            while c0 < len(s):
                if c0 + 1 < len(s) and s[c0:c0 + 2].lower() == "ll":
                    if i_lvl != 0:
                        raise ParsingError(tokens, c, "cannot specify 'll' or 'l' more than once")
                    i_lvl = 2
                    c0 += 1
                elif s[c0].lower() == 'u':
                    unsign = 1
                elif s[c0].lower() == 'l':
                    if i_lvl != 0:
                        raise ParsingError(tokens, c, "cannot specify 'll' or 'l' more than once")
                    i_lvl = 1
                else:
                    raise ParsingError(tokens, c, "Invalid suffix")
                c0 += 1
            assert 0 <= i_lvl <= 2
            data = None
            int_base_type = tokens[c].type_id
            if int_base_type == CLS_DEC_INT:
                data = int(s[:end_pos])
            elif int_base_type == CLS_HEX_INT:
                data = int(s[2:end_pos], 16)
            elif int_base_type == CLS_BIN_INT:
                data = int(s[2:end_pos], 2)
            elif int_base_type == CLS_OCT_INT:
                if s.startswith('0o'):
                    data = int(s[2:end_pos], 8)
                else:
                    data = int(s[1:end_pos], 8)
            assert data is not None
            self.l_val = data
            lst_opts = (
                [(INT_I, unsign), (INT_L, unsign), (INT_LL, unsign)][i_lvl:]
                if int_base_type == CLS_DEC_INT or unsign else
                [(INT_I, 0), (INT_I, 1), (INT_L, 0), (INT_L, 1), (INT_LL, 0), (INT_LL, 1)][2 * i_lvl:]
            )
            """ :type: list[(int, int)] """
            typ = None
            for TypeCode, Unsigned in lst_opts:
                typ = PrimitiveType.from_type_code(TypeCode, 1 if Unsigned else -1)
                minim = 0
                maxim = 1 << (size_of(typ) * 8)
                if not Unsigned:
                    off = maxim >> 1
                    minim -= off
                    maxim -= off
                if minim <= data < maxim:
                    break
                else:
                    typ = None
            if typ is None:
                raise ParsingError(tokens, c, "Integer too large, Opts = %r" % lst_opts)
            self.t_anot = typ
        elif tokens[c].type_id == CLS_FLOAT:
            self.t_lit = LiteralExpr.LIT_FLOAT
            end_pos = len(s)
            ch = s[-1].lower()
            if ch == 'f':
                ch1 = s[-2].lower()
                if ch1 == 's':
                    ch = ch1
                    end_pos -= 1
            elif ch == 'd':
                ch1 = s[-2].lower()
                if ch1 == 'l':
                    ch = ch1
                    end_pos -= 1
            if ch == 'f':
                end_pos -= 1
                self.t_anot = PrimitiveType.from_type_code(FLT_F)
            elif ch == 's':
                end_pos -= 1
                self.t_anot = PrimitiveType.from_str_name(["short", "float"])
            elif ch == 'd':
                end_pos -= 1
                self.t_anot = PrimitiveType.from_type_code(FLT_D)
            if ch == 'l':
                end_pos -= 1
                self.t_anot = PrimitiveType.from_type_code(FLT_LD)
            else:
                self.t_anot = PrimitiveType.from_type_code(FLT_D)
            self.l_val = float(s[:end_pos])
        elif tokens[c].type_id == CLS_UNI_QUOTE:
            self.t_lit = LiteralExpr.LIT_CHR
            uni_spec = 0
            if s.startswith("u"):
                uni_spec = 2
            elif s.startswith("U"):
                uni_spec = 3
            elif s.startswith("b"):
                uni_spec = 1
            elif not s.startswith("'"):
                raise ParsingError(tokens, c, "Unrecognized literal prefix")
            ch_type = None
            if uni_spec == 1:
                ch_type = PrimitiveType.from_type_code(INT_C)
            elif uni_spec == 2:
                ch_type = PrimitiveType.from_type_code(INT_C16)
            elif uni_spec == 3:
                ch_type = PrimitiveType.from_type_code(INT_C32)
            if ch_type is None:
                ch_type = PrimitiveType.from_type_code(INT_C)
            s_q = s.find('\'') + 1
            e_q = s.rfind('\'')
            lst_res, c1 = LiteralExpr.parse_char_part(s_q, s, uni_spec)
            if len(lst_res) != 1:
                raise ParsingError(
                    tokens, c,
                    "Expected one character in character literal: s_q = %u, e_q = %u, c1 = %u, lst_res = %r" % (
                        s_q, e_q, c1, lst_res
                    )
                )
            self.l_val = lst_res[0]
            self.t_anot = QualType(QualType.QUAL_CONST, ch_type)
        elif tokens[c].type_id == CLS_DBL_QUOTE:
            self.t_lit = LiteralExpr.LIT_STR
            lst_vals, uni_spec = LiteralExpr.parse_str_lit(s)
            self.l_val = lst_vals
            ch_type = None
            if uni_spec == 1:
                ch_type = PrimitiveType.from_type_code(INT_C)
            elif uni_spec == 2:
                ch_type = PrimitiveType.from_type_code(INT_C16)
            elif uni_spec == 3:
                ch_type = PrimitiveType.from_type_code(INT_C32)
            if ch_type is None:
                ch_type = PrimitiveType.from_type_code(INT_C)
            self.t_anot = QualType(QualType.QUAL_REF, QualType(
                QualType.QUAL_ARR,
                QualType(QualType.QUAL_CONST, ch_type),
                len(lst_vals) + 1  # plus 1 for null terminator
            ))
        elif tokens[c].type_id == CLS_NAME:
            self.t_lit = LiteralExpr.LIT_BOOL
            if s == "true":
                self.l_val = True
            elif s == "false":
                self.l_val = False
            else:
                raise ParsingError(
                    tokens, c,
                    "Expected a boolean literal (true or false)"
                )
            self.t_anot = PrimitiveType.from_type_code(TYP_BOOL)
        self.v_lit = s
        c += 1
        return c


def get_actual_type(typ):
    """
    :param BaseType|IdentifiedQualType typ:
    :rtype: BaseType
    """
    return typ.typ if isinstance(typ, IdentifiedQualType) else typ


def get_tgt_ref_type(typ):
    """
    returns pt, vt, is_ref
    :param BaseType typ:
    :rtype: (BaseType, BaseType, bool)
    """
    vt = pt = get_base_prim_type(typ)
    is_ref = False
    if pt.type_class_id == TYP_CLS_QUAL:
        assert isinstance(pt, QualType)
        if pt.qual_id == QualType.QUAL_REF:
            is_ref = True
            vt = get_base_prim_type(pt.tgt_type)
    return pt, vt, is_ref


def get_base_prim_type(typ):
    """
    :param BaseType|IdentifiedQualType typ:
    :rtype: BaseType
    """
    assert typ is not None
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    base_comp_types = {QualType.QUAL_FN, QualType.QUAL_PTR, QualType.QUAL_ARR, QualType.QUAL_REF}
    pass_thru_types = {
        QualType.QUAL_REG, QualType.QUAL_CONST, QualType.QUAL_DEF, QualType.QUAL_VOLATILE}
    if typ.type_class_id == TYP_CLS_PRIM:
        assert isinstance(typ, PrimitiveType)
        return typ
    elif typ.type_class_id == TYP_CLS_QUAL:
        assert isinstance(typ, QualType)
        if typ.qual_id in base_comp_types:
            return typ
        elif typ.qual_id in pass_thru_types:
            return get_base_prim_type(typ.tgt_type)
        else:
            raise ValueError("Bad qual_id = %u" % typ.qual_id)
    elif typ.type_class_id == TYP_CLS_ENUM:
        assert isinstance(typ, EnumType)
        return typ.the_base_type
    elif typ.type_class_id in [TYP_CLS_CLASS, TYP_CLS_STRUCT, TYP_CLS_UNION]:
        assert isinstance(typ, (ClassType, StructType, UnionType))
        return typ
    else:
        raise ValueError("Unrecognized Type: " + repr(typ))


def get_asgn_fn_type(typ, is_const_ref=False):
    """
    :param BaseType typ:
    :param bool is_const_ref:
    :rtype: QualType
    """
    arg_t = typ
    if is_const_ref:
        arg_t = QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, arg_t))
    lvalue_type = QualType(QualType.QUAL_REF, typ)
    return QualType(QualType.QUAL_FN, lvalue_type, [lvalue_type, arg_t])


def get_asgn_sh_fn_type(typ, is_const_ref=False):
    arg_t = PrimitiveType.from_type_code(INT_C, 1)
    if is_const_ref:
        arg_t = QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, arg_t))
    lvalue_type = QualType(QualType.QUAL_REF, typ)
    return QualType(QualType.QUAL_FN, lvalue_type, [lvalue_type, arg_t])


def get_uni_op_fn_type(typ, is_ref=True, is_const=False, res_ref=True):
    """
    :param BaseType typ:
    :param bool is_ref:
    :param bool is_const:
    :param bool res_ref:
    :rtype: QualType
    """
    arg_t = typ
    res_t = typ
    if is_const:
        arg_t = QualType(QualType.QUAL_CONST, arg_t)
    if is_ref:
        arg_t = QualType(QualType.QUAL_REF, arg_t)
    if res_ref:
        res_t = QualType(QualType.QUAL_REF, res_t)
    return QualType(QualType.QUAL_FN, res_t, [arg_t])


def get_uni_op_fn_type_r__r(typ):
    return get_uni_op_fn_type(typ, True, False, True)


def get_uni_op_fn_type_r__v(typ):
    return get_uni_op_fn_type(typ, True, False, False)


def get_uni_op_fn_type_c_r__v(typ):
    return get_uni_op_fn_type(typ, True, True, False)


def get_uni_op_fn_type_v__v(typ):
    return get_uni_op_fn_type(typ, False, False, False)


def get_arithmetic_op_fn_type(typ, is_const_ref=False):
    arg_t = typ
    if is_const_ref:
        arg_t = QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, arg_t))
    return QualType(QualType.QUAL_FN, typ, [arg_t, arg_t])


def get_sh_fn_type(typ):
    return QualType(QualType.QUAL_FN, typ, [typ, PrimitiveType.from_type_code(INT_C, 1)])


def get_cmp_op_fn_type(typ, is_const_ref=False):
    arg_t = typ
    if is_const_ref:
        arg_t = QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, arg_t))
    return QualType(QualType.QUAL_FN, bool_t, [arg_t, arg_t])


void_t = PrimitiveType.from_type_code(TYP_VOID)
int_types = [PrimitiveType.from_str_name(x) for x in [
    ["unsigned", "char"],
    ["signed", "char"],
    ["unsigned", "short"],
    ["signed", "short"],
    ["unsigned", "char16_t"],
    ["signed", "char16_t"],
    ["unsigned", "int"],
    ["signed", "int"],
    ["unsigned", "char32_t"],
    ["signed", "char32_t"],
    ["unsigned", "wchar_t"],
    ["signed", "wchar_t"],
    ["unsigned", "long"],
    ["signed", "long"],
    ["unsigned", "long", "long"],
    ["signed", "long", "long"],
    ["bool"]
]]
signed_num_types = [PrimitiveType.from_str_name(x) for x in [
    ["signed", "char"],
    ["signed", "short"],
    ["signed", "char16_t"],
    ["signed", "int"],
    ["signed", "char32_t"],
    ["signed", "wchar_t"],
    ["signed", "long"],
    ["signed", "long", "long"],
    ["float"],
    ["double"],
    ["long", "double"]
]]
bool_t = int_types[-1]
prim_types = int_types + [PrimitiveType.from_str_name(x) for x in [
    ["float"],
    ["double"],
    ["long", "double"]
]]
size_l_t = PrimitiveType.get_size_l_type()
snz_l_t = PrimitiveType.get_size_l_type(True)

OP_TYP_NATIVE = 0
OP_TYP_FUNCTION = 1
OP_TYP_PTR_GENERIC = 2
OP_TYP_GENERIC = 3


class UnaryOpExpr(BaseExpr):
    expr_id = EXPR_UNI_OP
    lst_prim_fns = [
        # "UNARY_BOOL_NOT",
        [get_uni_op_fn_type_v__v(bool_t)],
        # "UNARY_PRE_DEC",
        list(map(get_uni_op_fn_type_r__r, prim_types)),
        # "UNARY_POST_DEC",
        list(map(get_uni_op_fn_type_r__v, prim_types)),
        # "UNARY_PRE_INC",
        list(map(get_uni_op_fn_type_r__r, prim_types)),
        # "UNARY_POST_INC",
        list(map(get_uni_op_fn_type_r__v, prim_types)),
        # "UNARY_BIT_NOT",
        list(map(get_uni_op_fn_type_v__v, int_types)),
        # "UNARY_STAR",
        None,
        # "UNARY_REFERENCE",
        None,
        # "UNARY_MINUS",
        list(map(get_uni_op_fn_type_v__v, signed_num_types)),
        # "UNARY_PLUS",
        list(map(get_uni_op_fn_type_v__v, prim_types))
    ]

    def __init__(self, type_id, a):
        """
        :param int type_id:
        :param BaseExpr a:
        """
        self.type_id = type_id
        self.op_fn_type = OP_TYP_NATIVE
        self.op_fn_data = None
        assert a.t_anot is not None
        if UnaryOpExpr.lst_prim_fns[type_id] is not None:
            fn_types = UnaryOpExpr.lst_prim_fns[type_id]
            index_fn_t, lst_conv = abstract_overload_resolver([a], fn_types)
            if index_fn_t >= len(fn_types):
                tgt_type = None
                src_vt = None
                if type_id in [UNARY_PRE_DEC, UNARY_POST_DEC, UNARY_PRE_INC, UNARY_POST_INC]:
                    src_pt, src_vt, is_src_ref = get_tgt_ref_type(a.t_anot)
                    if src_vt.type_class_id == TYP_CLS_QUAL:
                        assert isinstance(src_vt, QualType)
                        if src_vt.qual_id == QualType.QUAL_PTR and is_src_ref:
                            tgt_type = src_vt.tgt_type
                if tgt_type is None:
                    raise TypeError("No overloaded operator function for %s exists for type: %s" % (
                        LST_BIN_OP_ID_MAP[type_id], get_user_str_from_type(a.t_anot)))
                assert isinstance(src_vt, QualType)
                if type_id in [UNARY_PRE_DEC, UNARY_PRE_INC]:
                    self.t_anot = a.t_anot
                else:
                    self.t_anot = src_vt
                self.op_fn_type = OP_TYP_PTR_GENERIC
                self.op_fn_data = size_of(tgt_type)
            else:
                self.op_fn_data = index_fn_t
                a = lst_conv[0]
                self.t_anot = fn_types[index_fn_t].tgt_type
        elif type_id == UNARY_REFERENCE:
            src_pt, src_vt, is_src_ref = get_tgt_ref_type(a.t_anot)
            if not is_src_ref:
                raise TypeError("Cannot get the pointer to a non-reference type %s" % get_user_str_from_type(a.t_anot))
            self.t_anot = QualType(QualType.QUAL_PTR, src_vt)
        elif type_id == UNARY_STAR:
            src_pt, src_vt, is_src_ref = get_tgt_ref_type(a.t_anot)
            tgt_type = None
            if src_vt.type_class_id == TYP_CLS_QUAL:
                assert isinstance(src_vt, QualType)
                if src_vt.qual_id == QualType.QUAL_PTR:
                    tgt_type = src_vt.tgt_type
            if tgt_type is None:
                err_fmt = "\n".join([
                    "Expected a pointer type for UNARY_STAR, given complete type %s,",
                    "  obtained prim_type = %s",
                    "  val_type = %s"
                ])
                raise TypeError(
                    err_fmt % (
                        get_user_str_from_type(a.t_anot),
                        get_user_str_from_type(src_pt),
                        get_user_str_from_type(src_vt)
                    )
                )
            if is_src_ref:
                a = CastOpExpr(src_vt, a, CastOpExpr.CAST_IMPLICIT)
            self.t_anot = QualType(QualType.QUAL_REF, src_vt.tgt_type)
        else:
            raise NotImplementedError("type_id = %s, is not implemented" % LST_UNI_OP_ID_MAP[type_id])
        self.a = a

    def init_temps(self, main_temps):
        main_temps = super(UnaryOpExpr, self).init_temps(main_temps)
        return self.a.init_temps(main_temps)

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on operator expressions")

    def pretty_repr(self):
        type_id = self.type_id
        if 0 <= type_id < len(LST_UNI_OP_ID_MAP):
            type_id = LST_UNI_OP_ID_MAP[type_id]
        else:
            type_id = repr(type_id)
        return [self.__class__.__name__, "(", type_id, ","] + get_pretty_repr(self.a) + [")"]


class BinaryOpExpr(BaseExpr):
    expr_id = EXPR_BIN_OP
    lst_prim_fns = [
        # "BINARY_ASSGN",
        list(map(get_asgn_fn_type, prim_types)),
        # "BINARY_ASSGN_MOD",
        list(map(get_asgn_fn_type, prim_types)),
        # "BINARY_ASSGN_DIV",
        list(map(get_asgn_fn_type, prim_types)),
        # "BINARY_ASSGN_MUL",
        list(map(get_asgn_fn_type, prim_types)),
        # "BINARY_ASSGN_MINUS",
        list(map(get_asgn_fn_type, prim_types)),
        # "BINARY_ASSGN_PLUS",
        list(map(get_asgn_fn_type, prim_types)),
        # "BINARY_ASSGN_AND",
        list(map(get_asgn_fn_type, int_types)),
        # "BINARY_ASSGN_OR",
        list(map(get_asgn_fn_type, int_types)),
        # "BINARY_ASSGN_XOR",
        list(map(get_asgn_fn_type, int_types)),
        # "BINARY_ASSGN_RSHIFT",
        list(map(get_asgn_sh_fn_type, int_types)),
        # "BINARY_ASSGN_LSHIFT",
        list(map(get_asgn_sh_fn_type, int_types)),
        # "BINARY_MUL",
        list(map(get_arithmetic_op_fn_type, prim_types)),
        # "BINARY_DIV",
        list(map(get_arithmetic_op_fn_type, prim_types)),
        # "BINARY_MOD",
        list(map(get_arithmetic_op_fn_type, prim_types)),
        # "BINARY_MINUS",
        list(map(get_arithmetic_op_fn_type, prim_types)),
        # "BINARY_PLUS",
        list(map(get_arithmetic_op_fn_type, prim_types)),
        # "BINARY_LT",
        list(map(get_cmp_op_fn_type, prim_types)),
        # "BINARY_GT",
        list(map(get_cmp_op_fn_type, prim_types)),
        # "BINARY_LE",
        list(map(get_cmp_op_fn_type, prim_types)),
        # "BINARY_GE",
        list(map(get_cmp_op_fn_type, prim_types)),
        # "BINARY_NE",
        list(map(get_cmp_op_fn_type, prim_types)),
        # "BINARY_EQ",
        list(map(get_cmp_op_fn_type, prim_types)),
        # "BINARY_AND",
        list(map(get_arithmetic_op_fn_type, int_types)),
        # "BINARY_OR",
        list(map(get_arithmetic_op_fn_type, int_types)),
        # "BINARY_XOR",
        list(map(get_arithmetic_op_fn_type, int_types)),
        # "BINARY_RSHIFT",
        list(map(get_sh_fn_type, int_types)),
        # "BINARY_LSHIFT",
        list(map(get_sh_fn_type, int_types)),
        # "BINARY_SS_AND", #SPECIAL
        [get_cmp_op_fn_type(bool_t)],
        # "BINARY_SS_OR", #SPECIAL
        [get_cmp_op_fn_type(bool_t)],
    ]

    def __init__(self, type_id, a, b):
        """
        :param int type_id:
        :param BaseExpr a:
        :param BaseExpr b:
        """
        self.type_id = type_id
        self.op_fn_type = OP_TYP_NATIVE
        self.op_fn_data = None  # should be int for native or ctx_var for function
        if a.t_anot is None or b.t_anot is None:
            self.t_anot = None
            self.op_fn_type = OP_TYP_FUNCTION
            print("WARN: could not get type: a = %r, b = %r" % (a, b))
        else:
            fn_types = BinaryOpExpr.lst_prim_fns[type_id]
            index_fn_t, lst_conv = abstract_overload_resolver([a, b], fn_types)
            if index_fn_t >= len(fn_types):
                ok = False
                tgt_pt, tgt_vt, is_tgt_ref = get_tgt_ref_type(a.t_anot)
                if tgt_vt.type_class_id == TYP_CLS_QUAL:
                    assert isinstance(tgt_vt, QualType)
                    if tgt_vt.qual_id == QualType.QUAL_PTR:
                        ok = True
                if not ok:
                    raise TypeError("No overloaded operator function for %s exists for types: %s and %s" % (
                        LST_BIN_OP_ID_MAP[type_id], get_user_str_from_type(a.t_anot), get_user_str_from_type(b.t_anot)))
                self.op_fn_type = OP_TYP_PTR_GENERIC
                # fn_types = []  # pycharm says this is unused
                self.op_fn_data = 0
                if type_id == BINARY_ASSGN:
                    ref_type = QualType(QualType.QUAL_REF, tgt_vt)
                    a = get_implicit_conv_expr(a, ref_type)[0]
                    b = get_implicit_conv_expr(b, tgt_vt)[0]
                    self.t_anot = ref_type
                    ok = True
                elif type_id in [BINARY_ASSGN_MINUS, BINARY_ASSGN_PLUS]:
                    ref_type = QualType(QualType.QUAL_REF, tgt_vt)
                    a = get_implicit_conv_expr(a, ref_type)[0]
                    res = get_implicit_conv_expr(b, snz_l_t)
                    if res is None or res[1] == 0:
                        res = get_implicit_conv_expr(b, size_l_t)
                    else:
                        self.op_fn_data = 1
                    assert res is not None and res[1] != 0, "Expected resolution of overloaded pointer arithmetic"
                    b = res[0]
                    self.t_anot = ref_type
                    ok = True
                elif type_id == BINARY_PLUS:
                    a = get_implicit_conv_expr(a, tgt_vt)[0]
                    res = get_implicit_conv_expr(b, snz_l_t)
                    if res is None or res[1] == 0:
                        res = get_implicit_conv_expr(b, size_l_t)
                    else:
                        self.op_fn_data = 1
                    assert res is not None and res[1] != 0, "Expected resolution of overloaded pointer arithmetic"
                    b = res[0]
                    self.t_anot = tgt_vt
                    ok = True
                elif type_id == BINARY_MINUS:
                    lst_try = [
                        size_l_t,
                        snz_l_t,
                        tgt_vt
                    ]
                    lst_try = list(map(lambda to_type: get_implicit_conv_expr(b, to_type), lst_try))
                    best = None
                    best_c = 0
                    for c, res in enumerate(lst_try):
                        if res is None or res[1] == 0:
                            continue
                        elif best is None or best[1] > res[1]:
                            best = res
                            best_c = c
                        elif best[1] == res[1]:
                            if best_c == 0 and c == 1:
                                best = res
                                best_c = c
                            else:
                                raise TypeError(
                                    "resolution of overloaded pointer subtraction is ambiguous a = %r, b = %r" % (a, b))
                    if best is not None:
                        self.op_fn_data = best_c
                        if best_c >= 2:
                            assert best_c == 2
                            self.t_anot = snz_l_t
                        else:
                            self.t_anot = tgt_vt
                        b = best[0]
                        a = get_implicit_conv_expr(a, tgt_vt)[0]
                        ok = True
                if not ok and type_id == BINARY_ASSGN:
                    self.op_fn_type = OP_TYP_GENERIC
                if not ok:
                    raise TypeError("No overloaded operator function for %s exists for types: %s and %s" % (
                        LST_BIN_OP_ID_MAP[type_id], get_user_str_from_type(a.t_anot), get_user_str_from_type(b.t_anot)))
            else:
                self.op_fn_data = index_fn_t
                a = lst_conv[0]
                b = lst_conv[1]
                self.t_anot = fn_types[index_fn_t].tgt_type
        self.a = a
        self.b = b

    def init_temps(self, main_temps):
        main_temps = super(BinaryOpExpr, self).init_temps(main_temps)
        return self.a.init_temps(self.b.init_temps(main_temps))

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on operator expressions")

    def pretty_repr(self):
        type_id = self.type_id
        if 0 <= type_id < len(LST_BIN_OP_ID_MAP):
            type_id = LST_BIN_OP_ID_MAP[type_id]
        else:
            type_id = repr(type_id)
        rtn = [self.__class__.__name__, "(", type_id]
        for inst in (self.a, self.b):
            rtn.extend([","] + get_pretty_repr(inst))
        rtn.append(")")
        return rtn


class SpecialPtrMemberExpr(BaseExpr):
    expr_id = EXPR_PTR_MEMBER

    def __init__(self, obj, attr):
        """
        :param BaseExpr obj:
        :param str attr:
        """
        self.obj = obj
        self.attr = attr
        if self.obj.t_anot is None:
            return
        src_ptr_pt, src_ptr_vt, is_src_ptr_ref = get_tgt_ref_type(self.obj.t_anot)
        if src_ptr_vt.type_class_id != TYP_CLS_QUAL:
            raise TypeError("Expected Pointer type for '->' operator")
        assert isinstance(src_ptr_vt, QualType)
        if src_ptr_vt.qual_id != QualType.QUAL_PTR:
            raise TypeError("Expected Pointer type for '->' operator")
        if is_src_ptr_ref:
            self.obj = CastOpExpr(src_ptr_vt, obj)
        src_vt = get_base_prim_type(src_ptr_vt.tgt_type)
        if src_vt.type_class_id not in [TYP_CLS_STRUCT, TYP_CLS_UNION, TYP_CLS_CLASS]:
            raise TypeError("Cannot use '->' operator on non-class/struct/union pointer types")
        assert isinstance(src_vt, (StructType, UnionType, ClassType))
        ctx_var = None
        if src_vt.type_class_id == TYP_CLS_UNION:
            assert isinstance(src_vt, UnionType)
            ctx_var = src_vt.definition.get(attr, ctx_var)
        else:
            assert isinstance(src_vt, (StructType, ClassType))
            var_index = src_vt.definition.get(attr, -1)
            if var_index != -1:
                ctx_var = src_vt.var_order[var_index]
        if ctx_var is None:
            raise AttributeError("Instance of union/class/struct '%s' has no member '%s'" % (src_vt.name, attr))
        attr_pt, attr_vt, is_attr_ref = get_tgt_ref_type(ctx_var.typ)
        if is_attr_ref:
            self.do_deref = True
            self.t_anot = attr_pt
        else:
            self.t_anot = QualType(QualType.QUAL_REF, attr_pt)

    def init_temps(self, main_temps):
        main_temps = super(SpecialPtrMemberExpr, self).init_temps(main_temps)
        return self.obj.init_temps(main_temps)

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on operator expressions")

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.obj, self.attr))


class SpecialDotExpr(BaseExpr):
    expr_id = EXPR_DOT

    def __init__(self, obj, attr):
        """
        :param BaseExpr obj:
        :param str attr:
        """
        self.obj = obj
        self.attr = attr
        self.do_deref = False
        if self.obj.t_anot is None:
            return
        src_pt, src_vt, is_src_ref = get_tgt_ref_type(self.obj.t_anot)
        if src_vt.type_class_id not in [TYP_CLS_STRUCT, TYP_CLS_UNION, TYP_CLS_CLASS]:
            raise TypeError("Cannot use '.' operator on non-class/struct/union types, got src_vt = %s, obj = %s" % (get_user_str_from_type(src_vt), obj))
        assert isinstance(src_vt, (StructType, UnionType, ClassType))
        ctx_var = None
        if src_vt.type_class_id == TYP_CLS_UNION:
            assert isinstance(src_vt, UnionType)
            ctx_var = src_vt.definition.get(attr, ctx_var)
        else:
            assert isinstance(src_vt, (StructType, ClassType))
            var_index = src_vt.definition.get(attr, -1)
            if var_index != -1:
                ctx_var = src_vt.var_order[var_index]
        if ctx_var is None:
            raise AttributeError("Instance of union/class/struct '%s' has no member '%s'" % (src_vt.name, attr))
        attr_pt, attr_vt, is_attr_ref = get_tgt_ref_type(ctx_var.typ)
        if is_src_ref and not is_attr_ref:
            self.t_anot = QualType(QualType.QUAL_REF, attr_pt)
        else:
            if is_attr_ref:
                self.do_deref = True
            self.t_anot = attr_pt

    def init_temps(self, main_temps):
        main_temps = super(SpecialDotExpr, self).init_temps(main_temps)
        return self.obj.init_temps(main_temps)

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on operator expressions")

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.obj, self.attr))


class CastOpExpr(BaseExpr):
    expr_id = EXPR_CAST
    CAST_PROMOTION = 0
    CAST_IMPLICIT = 1
    CAST_EXPLICIT = 2

    def __init__(self, type_name, expr, cast_type=2):
        """
        :param BaseType type_name:
        :param BaseExpr expr:
        :param int cast_type:
        """
        assert expr.t_anot is not None, repr(expr)
        src_pt, src_vt, is_src_ref = get_tgt_ref_type(expr.t_anot)
        tgt_pt, tgt_vt, is_tgt_ref = get_tgt_ref_type(type_name)
        self.type_name = type_name
        self.expr = expr
        if compare_no_cvr(src_vt, tgt_vt) and (not is_src_ref) and is_tgt_ref:
            self.temps = [tgt_vt]
        self.cast_type = cast_type
        self.t_anot = type_name

    def init_temps(self, main_temps):
        # NOTE: figure out why temp_links is inconsistent between compile-time and parse-time
        main_temps = super(CastOpExpr, self).init_temps(main_temps)
        res = self.expr.init_temps(main_temps)
        assert self.temps is self.expr.temps, "self.temps = %r, self.expr.temps = %r" % (self.temps, self.expr.temps)
        return res

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on C-Style Cast operator")

    def pretty_repr(self):
        rtn = [self.__class__.__name__] + get_pretty_repr((self.type_name, self.expr))
        if self.cast_type != 2:
            const_name = ["PROMOTION", "IMPLICIT", "EXPLICIT"]
            rtn[-1:-1] = [",", rtn[0], ".", "CAST_%s" % const_name[self.cast_type]]
        return rtn


class FnCallExpr(BaseExpr):
    expr_id = EXPR_FN_CALL

    def __init__(self, fn, lst_args):
        """
        :param BaseExpr fn:
        :param list[BaseExpr] lst_args:
        """
        self.fn = fn
        self.lst_args = lst_args
        resolve_overloaded_fn(self)
        fn_vt = get_value_type(self.fn.t_anot)
        assert fn_vt.type_class_id == TYP_CLS_QUAL
        assert isinstance(fn_vt, QualType)
        assert fn_vt.qual_id == QualType.QUAL_FN
        self.t_anot = fn_vt.tgt_type

    def init_temps(self, main_temps):
        main_temps = super(FnCallExpr, self).init_temps(main_temps)
        main_temps = self.fn.init_temps(main_temps)
        for expr in self.lst_args:
            main_temps = expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.fn, self.lst_args))

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on FnCallExpr")


class ParenthExpr(BaseExpr):
    expr_id = EXPR_PARENTH

    def __init__(self, lst_expr):
        """
        :param list[BaseExpr] lst_expr:
        """
        self.lst_expr = lst_expr
        if len(self.lst_expr):
            self.t_anot = self.lst_expr[-1].t_anot

    def init_temps(self, main_temps):
        main_temps = super(ParenthExpr, self).init_temps(main_temps)
        for expr in self.lst_expr:
            main_temps = expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.lst_expr) + [")"]

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on ParenthExpr")


# SParenth means '[' (Square)
class SParenthExpr(BaseExpr):
    expr_id = EXPR_SPARENTH

    def __init__(self, left_expr, inner_expr):
        """
        :param BaseExpr left_expr:
        :param BaseExpr inner_expr:
        """
        if left_expr.t_anot is not None and inner_expr.t_anot is not None:
            p_t, l_t, is_l_ref = get_tgt_ref_type(left_expr.t_anot)
            if l_t.type_class_id == TYP_CLS_QUAL:
                assert isinstance(l_t, QualType)
                if l_t.qual_id == QualType.QUAL_PTR or (l_t.qual_id == QualType.QUAL_ARR and is_l_ref):
                    if l_t.qual_id == QualType.QUAL_PTR and is_l_ref:
                        left_expr = CastOpExpr(l_t, left_expr, CastOpExpr.CAST_IMPLICIT)
                    self.t_anot = QualType(QualType.QUAL_REF, l_t.tgt_type)
                    res = get_implicit_conv_expr(inner_expr, size_l_t)
                    if res is None:
                        res = get_implicit_conv_expr(inner_expr, snz_l_t)
                    # print "RESULT of SParenthExpr(%r, %r) : res = %r" % (LeftExpr, InnerExpr, res)
                    if res is None:
                        raise TypeError("Could not convert %r to %s" % (inner_expr, get_user_str_from_type(size_l_t)))
                    b, code = res
                    if code == 0:
                        raise TypeError("Could not convert %r to %s" % (inner_expr, get_user_str_from_type(size_l_t)))
                    inner_expr = b
                else:
                    raise TypeError(
                        "Unsupported type %s (wanted array reference or pointer) for '[]' operator" %
                        get_user_str_from_type(left_expr.t_anot)
                    )
            if self.t_anot is None:
                raise TypeError("Unsupported type %s for '[]' operator" % get_user_str_from_type(left_expr.t_anot))
        else:
            raise TypeError(
                "Required type annotation for SParenthExpr, LeftExpr = %r, InnerExpr = %r" % (
                    left_expr, inner_expr
                )
            )
        if self.t_anot is None:
            raise TypeError("ESCAPED Unsupported type %s for '[]' operator" % get_user_str_from_type(left_expr.t_anot))
        self.left_expr = left_expr
        self.inner_expr = inner_expr

    def init_temps(self, main_temps):
        main_temps = super(SParenthExpr, self).init_temps(main_temps)
        return self.inner_expr.init_temps(self.left_expr.init_temps(main_temps))

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.left_expr, self.inner_expr))

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on SParenthExpr")


class InlineIfExpr(BaseExpr):
    expr_id = EXPR_INLINE_IF

    def __init__(self, cond, if_true, if_false):
        """
        :param BaseExpr cond:
        :param BaseExpr if_true:
        :param BaseExpr if_false:
        """
        self.cond = cond
        self.if_true = if_true
        self.if_false = if_false

    def init_temps(self, main_temps):
        main_temps = super(InlineIfExpr, self).init_temps(main_temps)
        main_temps = self.cond.init_temps(main_temps)
        main_temps = self.if_true.init_temps(main_temps)
        main_temps = self.if_false.init_temps(main_temps)
        return main_temps

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.cond, self.if_true, self.if_false))

    def build(self, tokens, c, end, context):
        raise NotImplementedError("Cannot call 'build' on InlineIfExpr")


def take_prev(op_tuple):
    return op_tuple[0] > 0 and bool(op_tuple[3] & 0x02)


def take_next(op_tuple):
    return op_tuple[0] > 0 and bool(op_tuple[3] & 0x01)


def take_both(op_tuple):
    return op_tuple[0] >= 2 and (op_tuple[3] & 0x03) == 0x03
# Ternary/special operator format:
#   k, v = begin token, tuple of stuff
#   v[0] = operator precedence
#   v[1] = end token
#   v[2] = tuple of possible fixes: <bitwise or> of
#     0x01 is prefix<meaning ()b>, 0x02 is postfix<meaning a()>


class BaseOpPart(object):
    txt = "<UNNAMED>"
    special = False
    prefix_lvl = None
    infix_lvl = None
    postfix_lvl = None
    can_nofix = False
    is_expr = False

    def __init__(self):
        self.can_infix = self.infix_lvl is not None
        self.can_postfix = self.postfix_lvl is not None
        self.can_prefix = self.prefix_lvl is not None

    def build(self, operands, fixness):
        raise NotImplementedError("Cannot call 'build' on Abstract class BaseOpPart")


class ExprOpPart(BaseOpPart):
    def __init__(self, expr):
        super(ExprOpPart, self).__init__()
        self.is_expr = True
        self.expr = expr

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.expr)

    def build(self, operands, fixness):
        assert len(operands) == 0
        assert fixness == 0
        return self.expr


class SimpleOpPart(BaseOpPart):
    def __init__(self, tok):
        """
        :param ParseClass tok:
        """
        self.txt = tok.str
        self.special = False
        if self.txt in DCT_FIXES:
            self.prefix_lvl, self.infix_lvl, self.postfix_lvl = DCT_FIXES[self.txt]
        elif self.txt.startswith("."):
            self.prefix_lvl, self.infix_lvl, self.postfix_lvl = None, None, DCT_FIXES["."][1]
            self.special = True
        elif self.txt.startswith("->"):
            self.prefix_lvl, self.infix_lvl, self.postfix_lvl = None, None, DCT_FIXES["->"][1]
            self.special = True
        else:
            raise ValueError("cannot accept '%s'" % self.txt)
        super(SimpleOpPart, self).__init__()
        # self.is_op = tok.type_id in [CLS_BRK_OP, CLS_OPERATOR]
        self.is_expr = not any([self.can_prefix, self.can_infix, self.can_postfix])

    def __repr__(self):
        return "%s(<ParseClass>(%r))" % (self.__class__.__name__, self.txt)

    def build(self, operands, fixness):
        if self.special:
            if self.txt.startswith("->"):
                return SpecialPtrMemberExpr(operands[0], self.txt[2:])
            elif self.txt.startswith("."):
                return SpecialDotExpr(operands[0], self.txt[1:])
        elif fixness == 3:
            return BinaryOpExpr(DCT_INFIX_OP_NAME[self.txt], operands[0], operands[1])
        elif fixness == 1:
            return UnaryOpExpr(DCT_PREFIX_OP_NAME[self.txt], operands[0])
        elif fixness == 2:
            return UnaryOpExpr(DCT_POSTFIX_OP_NAME[self.txt], operands[0])
        else:
            raise ValueError("unexpected fixness or operator name: operands = %r, fixness = %r" % (operands, fixness))


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
            print("WARN: cast from (%s) to (%s) is not going through standard_conv_expr" % (
                get_user_str_from_type(operands[0].t_anot),
                get_user_str_from_type(self.type_name)
            ))
            pt, vt, is_ref = get_tgt_ref_type(operands[0].t_anot)
            res = operands[0]
            if is_ref:
                res = CastOpExpr(vt, res)
            return CastOpExpr(self.type_name, res)
        # raise TypeError("Could not cast")


class ParenthOpPart(BaseOpPart):
    postfix_lvl = 2

    def __init__(self, lst_expr):
        self.can_nofix = True
        super(ParenthOpPart, self).__init__()
        self.lst_expr = lst_expr

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.lst_expr)

    def build(self, operands, fixness):
        if fixness == 0:
            assert len(operands) == 0
            return ParenthExpr(self.lst_expr)
        else:
            assert fixness == 2
            assert len(operands) == 1
            return FnCallExpr(operands[0], self.lst_expr)


class SParenthOpPart(BaseOpPart):
    postfix_lvl = 2

    def __init__(self, expr):
        super(SParenthOpPart, self).__init__()
        self.expr = expr

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.expr)

    def build(self, operands, fixness):
        assert len(operands) == 1
        assert fixness == 2
        return SParenthExpr(operands[0], self.expr)


class InlineIfOpPart(BaseOpPart):
    infix_lvl = 15

    def __init__(self, expr):
        super(InlineIfOpPart, self).__init__()
        self.expr = expr

    def build(self, operands, fixness):
        assert len(operands) == 2
        assert fixness == 3
        return InlineIfExpr(operands[0], self.expr, operands[1])
# OnlyTN means assume Only type_name


def is_type_name_part(s, context, only_tn=False):
    """
    :param str s:
    :param CompileContext context:
    :param bool only_tn:
    :rtype: bool
    """
    if s in TYPE_WORDS or s in META_TYPE_WORDS:
        return True
    elif only_tn:
        return context.type_name(s) is not None
    else:
        x = context.get(s)
        if x is None:
            return False
        return x.is_type()


class ContextMember(object):
    def __init__(self, name, parent):
        """
        :param str name:
        :param CompileContext|None parent:
        """
        self.name = name
        self.parent = parent

    def get_full_name(self):
        if self.parent is None:
            return self.name
        return "%s::%s" % (self.parent.get_full_name(), self.name)

    def get_scope_name(self):
        if self.parent is None or not self.parent.is_local_scope():
            return self.name
        return "%s::%s" % (self.parent.get_scope_name(), self.name)

    def is_var(self):
        return not (self.is_type() or self.is_scopeable() or self.is_local_scope())

    def is_scopeable(self):
        return self.is_namespace() or self.is_class()

    def is_type(self): return False

    def is_class(self): return False

    def is_namespace(self): return False

    def is_local_scope(self): return False

    def get_underlying_type(self):
        # TODO: fix this so that structs/unions/classes will directly handle this (important)
        if isinstance(self, BaseType):
            return self
        return None


class TypeDefCtxMember(ContextMember):
    def __init__(self, name, parent, typ):
        """

        :param str name:
        :param CompileContext|None parent:
        :param BaseType typ:
        """
        super(TypeDefCtxMember, self).__init__(name, parent)
        self.typ = typ

    def is_type(self):
        return True

    def get_underlying_type(self):
        return self.typ


def mangle_decl(name, typ, is_local, is_op_fn=False):
    """
    :param is_op_fn:
    :param str name:
    :param BaseType typ:
    :param bool is_local:
    :rtype: str
    """
    name = name.rsplit("::", 1)
    if is_local:
        lst_rtn, name = ([], name[0]) if len(name) <= 1 else (list(map(int, name[0].split("::"))), name[1])
        return "$" + "?".join(map(str, lst_rtn)) + "?" + typ.to_mangle_str(False) + name
    else:
        lst_rtn, name = ([], name[0]) if len(name) <= 1 else (name[0].split("::"), name[1])
        if is_op_fn:
            raise NotImplementedError("Operater mangling is not implemented")
            # TODO replace `OP_MANGLE` with a mapping from operator name and type to its mangled name
            # return "@".join(lst_rtn) + "$" + self.typ.ToMangleStr(True) + `OP_MANGLE` + "_g"
        else:
            return "@".join(lst_rtn) + "?" + typ.to_mangle_str(True) + name


class ContextVariable(ContextMember, PrettyRepr):
    MOD_DEFAULT = 0
    MOD_STATIC = 1
    MOD_EXTERN = 2
    MOD_IS_ARG = 3

    def __init__(self, name, typ, init_expr=None, mods=0):
        """
        :param str name:
        :param BaseType typ:
        :param init_expr:
        :param mods:
        """
        super(ContextVariable, self).__init__(name, None)
        # self.Size = SizeOf(typ, Mods == ContextVariable.MOD_IS_ARG)
        self.init_expr = init_expr
        self.is_op_fn = False
        self.typ = typ
        self.mods = mods

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.name, self.typ, self.init_expr, self.mods))

    def get_link_name(self):
        if self.parent.is_local_scope():
            assert isinstance(self.parent, LocalScope)
            scope = self.parent
            lst_rtn = [0] * scope.lvl
            c = 0
            while scope.is_local_scope():
                assert isinstance(scope, LocalScope)
                if c >= len(lst_rtn):
                    lst_rtn.append(0)
                lst_rtn[c] = scope.scope_index
                scope = scope.parent
            return "$" + "?".join(map(str, lst_rtn)) + "?" + self.typ.to_mangle_str(False) + self.name
        else:
            ns = self.parent
            lst_rtn = [""]
            while ns.parent is not None:
                lst_rtn.append(ns.name)
                ns = ns.parent
            if self.is_op_fn:
                pass
                # TODO replace `OP_MANGLE` with a mapping from operator name and type to its mangled name
                # return "@".join(lst_rtn) + "$" + self.typ.ToMangleStr(True) + `OP_MANGLE` + "_g"
            else:
                return "@".join(lst_rtn) + "?" + self.typ.to_mangle_str(True) + self.name

    def const_init(self, expr):
        self.init_expr = expr
        if not isinstance(self.typ, QualType) or self.typ.qual_id != QualType.QUAL_CONST:
            self.typ = QualType(QualType.QUAL_CONST, self.typ)
        return self


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


def is_prim_type_id(typ, type_id):
    """
    :param BaseType typ:
    :param int type_id:
    :rtype: bool
    """
    if typ.type_class_id == TYP_CLS_PRIM:
        assert isinstance(typ, PrimitiveType)
        return typ.typ == type_id
    return False


def is_default(typ):
    """
    :param BaseType typ:
    """
    del typ
    return False


class MultiType(BaseType):
    type_class_id = TYP_CLS_MULTI


def get_ellipses_conv_expr(expr):
    """
    :param BaseExpr expr:
    :rtype: (BaseExpr, int)|None
    """
    src_pt = get_base_prim_type(expr.t_anot)
    to_type = expr.t_anot
    src_vt = src_pt
    if src_pt.type_class_id == TYP_CLS_QUAL:
        assert isinstance(src_pt, QualType)
        if src_pt.qual_id == QualType.QUAL_REF:
            src_vt = src_pt.tgt_type
    if src_vt.type_class_id == TYP_CLS_QUAL:
        assert isinstance(src_vt, QualType)
        if src_vt.qual_id == QualType.QUAL_FN:
            to_type = QualType(QualType.QUAL_PTR, src_vt)
    elif src_vt.type_class_id == TYP_CLS_PRIM:
        assert isinstance(src_vt, PrimitiveType)
        if src_vt.typ in INT_TYPE_CODES:
            if src_vt.size < SIZE_SIGN_MAP[INT_I][0]:
                to_type = PrimitiveType.from_type_code(INT_I, -1 if src_vt.sign else 1)
        elif src_vt.typ in FLT_TYPE_CODES:
            if src_vt.size < SIZE_SIGN_MAP[FLT_D][0]:
                to_type = PrimitiveType.from_type_code(FLT_D)
        else:
            raise ValueError("Unexpected Primitive Type = %r" % src_vt)
    else:
        raise ValueError("Unexpected Type = %r" % src_vt)
    rtn = expr
    if to_type is not expr.t_anot:
        rtn = CastOpExpr(to_type, expr, CastOpExpr.CAST_IMPLICIT)
    return rtn, 6


OVERLOAD_VERBOSE = False
OVERLOAD_BAN_ARR_VAL = True
# TODO: Add a new priority of promotion (maybe conversion too) to distinguish signed from unsigned


def get_implicit_conv_expr(expr, to_type):
    """
    Rating is
      0 if conversion could not be done
      1 if no conversion necessary
      2 if exact match rank done
      3 if promotion rank done
      4 if conversion rank done
      5 if conversion is user defined
      6 if conversion is ellipses
    :param BaseExpr expr:
    :param BaseType to_type:
    :rtype: (BaseExpr, int)|None
    """
    res1 = get_standard_conv_expr(expr, to_type)
    if res1 is None:
        if OVERLOAD_VERBOSE:
            print("First Conversion failed")
        return None
    expr1, rate1 = res1
    res2 = get_user_def_conv_expr(expr1, to_type)
    if res2 is None:
        if OVERLOAD_VERBOSE:
            print("Middle Conversion failed")
        return None
    expr2, rate2 = res2
    res3 = get_standard_conv_expr(expr2, to_type)
    if res3 is None:
        if OVERLOAD_VERBOSE:
            print("Last Conversion failed")
        return None
    expr3, rate3 = res3
    if rate3 == 0:
        if OVERLOAD_VERBOSE:
            print("Last Conversion failed id")
        return None
    if expr3.t_anot is not to_type and not compare_no_cvr(expr3.t_anot, to_type):
        if OVERLOAD_VERBOSE:
            print("Conversion attempt failed, got expr3.t_anot = %s\n  to_type = %s" % (repr(expr3.t_anot), repr(to_type)))
        return None
    return expr3, max([rate1, rate2, rate3])


def get_user_def_conv_expr(expr, to_type):
    """
    :param BaseExpr expr:
    :param BaseType to_type:
    :rtype: (BaseExpr, int)|None
    """
    src_pt = get_base_prim_type(expr.t_anot)
    tgt_pt = get_base_prim_type(to_type)
    if tgt_pt.type_class_id in [TYP_CLS_CLASS, TYP_CLS_STRUCT, TYP_CLS_UNION]:
        assert isinstance(tgt_pt, (StructType, ClassType, UnionType))
        raise NotImplementedError("Not Implemented")
    elif src_pt.type_class_id in [TYP_CLS_CLASS, TYP_CLS_STRUCT, TYP_CLS_UNION]:
        assert isinstance(src_pt, (StructType, ClassType, UnionType))
        raise NotImplementedError("Not Implemented")
    elif tgt_pt.type_class_id == TYP_CLS_QUAL:
        assert isinstance(tgt_pt, QualType)
        if tgt_pt.qual_id == QualType.QUAL_REF:
            tgt_pt1 = tgt_pt.tgt_type
            if tgt_pt1.type_class_id in [TYP_CLS_CLASS, TYP_CLS_STRUCT, TYP_CLS_UNION]:
                assert isinstance(tgt_pt1, (StructType, ClassType, UnionType))
                if not compare_no_cvr(src_pt, tgt_pt):
                    raise NotImplementedError("Not Implemented: %s -> %s" % (get_user_str_from_type(expr.t_anot), get_user_str_from_type(to_type)))
    elif src_pt.type_class_id == TYP_CLS_QUAL:
        assert isinstance(src_pt, QualType)
        if src_pt.qual_id == QualType.QUAL_REF:
            src_pt1 = src_pt.tgt_type
            if src_pt1.type_class_id in [TYP_CLS_CLASS, TYP_CLS_STRUCT, TYP_CLS_UNION]:
                assert isinstance(src_pt1, (StructType, ClassType, UnionType))
                raise NotImplementedError("Not Implemented")
    return expr, 1


# MyExpr = GetImplicitConvExpr(
#     DeclVarExpr(
#         QualType(
#             QualType.QUAL_REF,
#             QualType(
#                 QualType.QUAL_PTR,
#                 PrimitiveType.from_str_name(["char"])
#             )
#         )
#     ),
#     QualType(
#         QualType.QUAL_PTR,
#         Void_T
#     )
# )


class DeclVarExpr(BaseExpr):
    expr_id = EXPR_DECL_VAR

    def __init__(self, typ):
        self.t_anot = typ

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.t_anot) + [")"]


def is_prim_or_ptr(typ):
    """
    :param BaseType typ:
    :rtype: bool
    """
    if typ.type_class_id == TYP_CLS_PRIM:
        return True
    elif typ != TYP_CLS_QUAL:
        return False
    assert isinstance(typ, QualType)
    return typ.qual_id == QualType.QUAL_PTR


def get_standard_conv_expr(expr, to_type):
    """
    returns None if conversion invalid
    returns (expr, 0) if conversion could not be done
    returns (expr, 1) if no conversion necessary
    returns (new expr, 2) if exact match rank done
    returns (new expr, 3) if promotion rank done
    returns (new expr, 4) if conversion rank done
    :param BaseExpr expr:
    :param BaseType to_type:
    :rtype: (BaseExpr, int)|None
    """
    src_pt, src_vt, is_src_ref = get_tgt_ref_type(expr.t_anot)
    tgt_pt, tgt_vt, is_tgt_ref = get_tgt_ref_type(to_type)
    if compare_no_cvr(src_vt, tgt_vt):
        if is_tgt_ref ^ is_src_ref:
            return CastOpExpr(to_type, expr, CastOpExpr.CAST_IMPLICIT), 2
        return expr, 1
    elif is_src_ref and not is_tgt_ref and is_prim_or_ptr(src_vt):
        return CastOpExpr(src_vt, expr, CastOpExpr.CAST_IMPLICIT), 4
    if src_vt.type_class_id == TYP_CLS_PRIM and tgt_vt.type_class_id == TYP_CLS_PRIM:
        assert isinstance(src_vt, PrimitiveType)
        assert isinstance(tgt_vt, PrimitiveType)
        if src_vt.typ != tgt_vt.typ:
            if is_src_ref:
                return CastOpExpr(src_vt, expr, CastOpExpr.CAST_IMPLICIT), 2
            rtn = CastOpExpr(tgt_vt, expr, CastOpExpr.CAST_IMPLICIT)
            if tgt_vt.size > src_vt.size:
                if tgt_vt.typ in INT_TYPE_CODES and src_vt.typ in INT_TYPE_CODES:
                    if tgt_vt.typ == INT_I:
                        return rtn, 3
                elif tgt_vt.typ in FLT_TYPE_CODES and src_vt.typ in FLT_TYPE_CODES:
                    if tgt_vt.typ == FLT_D:
                        return rtn, 3
            return rtn, 4
        return expr, 1
    if src_vt.type_class_id == TYP_CLS_QUAL and tgt_vt.type_class_id == TYP_CLS_QUAL:
        assert isinstance(src_vt, QualType)
        assert isinstance(tgt_vt, QualType)
        if tgt_vt.qual_id == QualType.QUAL_PTR:
            if (
                    src_vt.qual_id == QualType.QUAL_PTR or
                    (OVERLOAD_BAN_ARR_VAL and src_vt.qual_id == QualType.QUAL_ARR and src_vt.ext_inf is None)):
                if is_src_ref and is_tgt_ref:
                    return None
                elif is_src_ref:
                    return CastOpExpr(src_vt, expr, CastOpExpr.CAST_IMPLICIT), 2
                if compare_no_cvr(src_vt.tgt_type, tgt_vt.tgt_type):
                    if compare_no_cvr(src_vt, tgt_vt):
                        return expr, 1
                    else:
                        return CastOpExpr(tgt_vt, expr, CastOpExpr.CAST_IMPLICIT), 2
                elif is_prim_type_id(tgt_vt.tgt_type, TYP_VOID):
                    return CastOpExpr(tgt_vt, expr, CastOpExpr.CAST_IMPLICIT), 4
                if OVERLOAD_VERBOSE:
                    print("REASON: src_vt Pointer General")
                return None
            elif src_vt.qual_id == QualType.QUAL_FN:
                if not is_src_ref:
                    if OVERLOAD_VERBOSE:
                        print("REASON: Cannot cast function value")
                    return None
                if is_prim_type_id(tgt_vt.tgt_type, TYP_VOID):
                    return CastOpExpr(QualType(QualType.QUAL_PTR, src_vt), expr, CastOpExpr.CAST_IMPLICIT), 2
                elif compare_no_cvr(src_vt, tgt_vt.tgt_type):
                    return CastOpExpr(tgt_vt, expr, CastOpExpr.CAST_IMPLICIT), 2
                if OVERLOAD_VERBOSE:
                    print("REASON: src_vt Function General")
                return None
            elif src_vt.qual_id == QualType.QUAL_ARR:
                if OVERLOAD_BAN_ARR_VAL and not is_src_ref:
                    if OVERLOAD_VERBOSE:
                        print("REASON: src_pt is not a reference to array")
                    return None
                if compare_no_cvr(src_vt.tgt_type, tgt_vt.tgt_type):
                    return CastOpExpr(tgt_vt, expr, CastOpExpr.CAST_IMPLICIT), 2
                elif is_prim_type_id(tgt_vt.tgt_type, TYP_VOID):
                    return CastOpExpr(QualType(QualType.QUAL_PTR, src_vt.tgt_type), expr, CastOpExpr.CAST_IMPLICIT), 2
                if OVERLOAD_VERBOSE:
                    print("REASON: src_vt Array General")
                return None
            if OVERLOAD_VERBOSE:
                print("REASON: tgt_vt Pointer General")
        return None
    if OVERLOAD_VERBOSE:
        print("REASON: Unhandled Type conversion encountered %r -> %r" % (expr.t_anot, to_type))
    return None


def abstract_overload_resolver(lst_args, fn_types):
    """
    :param list[BaseExpr] lst_args:
    :param list[BaseType] fn_types:
    :rtype: (int, list[BaseExpr]|None)
    """
    n_args = len(lst_args)
    lst_viable = [None] * len(fn_types)
    """ :type: list[(BaseType, list[(BaseExpr, int)])|None] """
    for c, typ in enumerate(fn_types):
        assert typ.type_class_id == TYP_CLS_QUAL
        assert isinstance(typ, QualType)
        assert typ.qual_id == QualType.QUAL_FN
        variadic = False
        assert typ.ext_inf is not None
        assert not isinstance(typ.ext_inf, int)
        n_type = len(typ.ext_inf)
        viable = False
        if n_type == n_args:
            viable = True
        elif n_type < n_args and variadic:
            viable = True
        elif n_type > n_args:
            c1 = n_args
            while c1 < n_type:
                if not is_default(typ.ext_inf[c1]):
                    break
                c1 += 1
            if c1 >= n_type:
                viable = True
        if not viable:
            continue
        c1 = 0
        lst_conv = [None] * n_args
        """ :type: list[(BaseExpr, int)|None] """
        while c1 < n_type:
            conv_expr = get_implicit_conv_expr(lst_args[c1], get_actual_type(typ.ext_inf[c1]))
            if conv_expr is None:
                break
            lst_conv[c1] = conv_expr
            c1 += 1
        if c1 < n_type:
            if OVERLOAD_VERBOSE:
                print("NOT_VIABLE: %r, %r" % (typ, lst_conv))
            continue
        while c1 < n_args:
            conv_expr = get_ellipses_conv_expr(lst_args[c1])
            if conv_expr is None:
                break
            lst_conv[c1] = conv_expr
            c1 += 1
        if c1 >= n_args:
            lst_viable[c] = (typ, lst_conv)
        else:
            if OVERLOAD_VERBOSE:
                print("NOT_VIABLE: %r, %r" % (typ, lst_conv))
    if OVERLOAD_VERBOSE:
        print("OVERLOAD-RESOLUTION: lst_viable = %r" % lst_viable)
    best_entry = None
    """ :type: (int, list[(BaseExpr, int)])|None """
    last_ambiguous = None
    for c, Entry in enumerate(lst_viable):
        if Entry is None:
            continue
        if best_entry is None:
            best_entry = c, Entry[1]
            continue
        best_c, best_lst_conv = best_entry
        cur_fn, lst_conv = Entry
        if len(lst_conv) != len(best_lst_conv):
            raise ValueError(
                "Inconsistent length %u and %u for lst_conv = %r, best_lst_conv = %r" % (
                    len(lst_conv), len(best_lst_conv), lst_conv, best_lst_conv))
        status = 0  # 0 is ambiguous, 1 is eliminated, 2 is promoted
        for c1 in range(len(lst_conv)):
            a = lst_conv[c1]
            b = best_lst_conv[c1]
            if a[1] < b[1]:
                status = 2
                break
            elif a[1] > b[1]:
                status = 1
                break
        if status == 0:
            last_ambiguous = (c, Entry[1])
        elif status == 2:
            last_ambiguous = None
            best_entry = c, Entry[1]
    if last_ambiguous is not None:
        raise ValueError(
            "Resolution of Overloaded function is Ambiguous: %r AND %r" % (best_entry, last_ambiguous))
    if best_entry is None:
        return len(fn_types), None  # TODO: find better error code
    else:
        return best_entry[0], [expr for expr, priority in best_entry[1]]


def resolve_overloaded_fn(call_expr):
    """
    :param FnCallExpr call_expr:
    """
    fn = call_expr.fn
    if fn.expr_id != EXPR_NAME:
        raise ValueError("Only named functions are directly referable")
    assert isinstance(fn, NameRefExpr)
    lst_args = call_expr.lst_args
    n_args = len(lst_args)
    ctx_var = fn.ctx_var
    lst_fns = [ctx_var]
    """ :type: list[ContextVariable] """
    if ctx_var.typ.type_class_id == TYP_CLS_MULTI:
        assert isinstance(ctx_var, OverloadedCtxVar)
        lst_fns = ctx_var.specific_ctx_vars
    lst_viable = [None] * len(lst_fns)
    """ :type: list[(ContextVariable, list[(BaseExpr, int)])|None] """
    for c, TryFn in enumerate(lst_fns):
        typ = TryFn.typ
        assert typ.type_class_id == TYP_CLS_QUAL
        assert isinstance(typ, QualType)
        assert typ.qual_id == QualType.QUAL_FN
        variadic = False
        assert typ.ext_inf is not None
        assert not isinstance(typ.ext_inf, int)
        n_type = len(typ.ext_inf)
        viable = False
        if n_type == n_args:
            viable = True
        elif n_type < n_args and variadic:
            viable = True
        elif n_type > n_args:
            c1 = n_args
            while c1 < n_type:
                if not is_default(typ.ext_inf[c1]):
                    break
                c1 += 1
            if c1 >= n_type:
                viable = True
        if not viable:
            continue
        c1 = 0
        lst_conv = [None] * n_args
        """ :type: list[(BaseExpr, int)|None] """
        while c1 < n_type:
            conv_expr = get_implicit_conv_expr(lst_args[c1], get_actual_type(typ.ext_inf[c1]))
            if conv_expr is None:
                break
            lst_conv[c1] = conv_expr
            c1 += 1
        if c1 < n_type:
            if OVERLOAD_VERBOSE:
                print("NOT_VIABLE: %r, %r" % (TryFn, lst_conv))
            continue
        while c1 < n_args:
            conv_expr = get_ellipses_conv_expr(lst_args[c1])
            if conv_expr is None:
                break
            lst_conv[c1] = conv_expr
            c1 += 1
        if c1 >= n_args:
            lst_viable[c] = (TryFn, lst_conv)
        else:
            if OVERLOAD_VERBOSE:
                print("NOT_VIABLE: %r, %r" % (TryFn, lst_conv))
    best_entry = None
    """ :type: (ContextVariable, list[(BaseExpr, int)])|None """
    if OVERLOAD_VERBOSE:
        print("OVERLOAD-RESOLUTION: lst_viable = %r" % lst_viable)
    last_ambiguous = None
    for c, Entry in enumerate(lst_viable):
        if Entry is None:
            continue
        if best_entry is None:
            best_entry = Entry
            continue
        best_fn, best_lst_conv = best_entry
        cur_fn, lst_conv = Entry
        if len(lst_conv) != len(best_lst_conv):
            raise ValueError(
                "Inconsistent length %u and %u for lst_conv = %r, best_lst_conv = %r" % (
                    len(lst_conv), len(best_lst_conv), lst_conv, best_lst_conv))
        status = 0  # 0 is ambiguous, 1 is eliminated, 2 is promoted
        for c1 in range(len(lst_conv)):
            a = lst_conv[c1]
            b = best_lst_conv[c1]
            if a[1] < b[1]:
                status = 2
                break
            elif a[1] > b[1]:
                status = 1
                break
        if status == 0:
            last_ambiguous = Entry
        elif status == 2:
            best_entry = Entry
            last_ambiguous = None
    if last_ambiguous is not None:
        raise ValueError("Resolution of Overloaded function '%s' is Ambiguous: %r AND %r" % (
            fn.name, best_entry, last_ambiguous))
    if best_entry is None:
        raise ValueError("Could not resolve overloaded function call: %r" % call_expr)
    fn_var, lst_conv = best_entry
    new_lst_args = [None] * len(lst_conv)
    """ :type: list[BaseExpr] """
    for c in range(len(lst_conv)):
        new_lst_args[c] = lst_conv[c][0]
    call_expr.lst_args = new_lst_args
    fn.ctx_var = fn_var
    fn.t_anot = QualType(QualType.QUAL_REF, fn.ctx_var.typ)
# TODO: add code to deal with this type of context variable


class OverloadedCtxVar(ContextVariable):
    def __init__(self, name, specific_ctx_vars=None):
        """

        :param str name:
        :param list[ContextVariable]|None specific_ctx_vars:
        """
        super(OverloadedCtxVar, self).__init__(name, MultiType())
        self.specific_ctx_vars = [] if specific_ctx_vars is None else specific_ctx_vars

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.name, self.specific_ctx_vars))

    def add_ctx_var(self, inst):
        """
        :param ContextVariable inst:
        """
        self.specific_ctx_vars.append(inst)


def is_fn_type(typ):
    """
    :param BaseType typ:
    :rtype: bool
    """
    v_type = get_base_prim_type(typ)
    if v_type.type_class_id == TYP_CLS_QUAL:
        assert isinstance(v_type, QualType)
        if v_type.qual_id == QualType.QUAL_FN:
            return True
    return False


OPT_USER_INSPECT = 0
OPT_CODE_GEN = 1


class CompileContext(ContextMember):
    # Optimize tells the rest of the code to optimize (very slightly and not runtime performance-wise)
    #   the representation for the code generator
    Optimize = OPT_CODE_GEN

    def __init__(self, name, parent=None):
        """
        :param str name:
        :param None|CompileContext parent:
        """
        super(CompileContext, self).__init__(name, parent)
        self.scopes = []
        self.types = {}
        self.namespaces = {}
        self.vars = {}

    def is_namespace(self):
        return True

    def merge_to(self, other):
        """
        :param CompileContext other:
        """
        keys = list(self.types)
        other.types.update(self.types)
        for k in keys:
            typ = other.types[k]
            assert isinstance(typ, ContextMember)
            typ.parent = other
        keys = list(self.namespaces)
        other.namespaces.update(self.namespaces)
        for k in keys:
            namespace = other.namespaces[k]
            assert isinstance(namespace, ContextMember)
            namespace.parent = other
        keys = list(self.vars)
        other.vars.update(self.vars)
        for k in keys:
            var = other.vars[k]
            assert isinstance(var, ContextVariable)
            var.parent = other
        pre_len = len(other.scopes)
        other.scopes.extend(self.scopes)
        for c in range(pre_len, len(other.scopes)):
            scope = other.scopes[c]
            assert isinstance(scope, LocalScope)
            scope.set_parent(other, c)

    def has_type(self, t):
        """
        :param str t:
        :rtype: bool
        """
        return t in self.types or (self.parent is not None and self.parent.has_type(t))

    def has_var(self, v):
        """
        :param str v:
        :rtype: bool
        """
        return v in self.vars or (self.parent is not None and self.parent.has_var(v))

    def has_ns(self, ns):
        """
        :param str ns:
        :rtype: bool
        """
        return ns in self.namespaces or (self.parent is not None and self.parent.has_ns(ns))

    def has_type_strict(self, t):
        """
        :param str t:
        :rtype: bool
        """
        return t in self.types

    def has_var_strict(self, v):
        """
        :param str v:
        :rtype: bool
        """
        return v in self.vars

    def has_ns_strict(self, ns):
        """
        :param str ns:
        :rtype: bool
        """
        return ns in self.namespaces

    def new_type(self, t, inst):
        """
        :param str t:
        :param ContextMember inst:
        :rtype: ContextMember
        """
        self.types[t] = inst
        inst.parent = self
        return inst

    def new_var(self, v, inst):
        """
        :param str v:
        :param ContextVariable inst:
        :rtype: ContextVariable
        """
        inst.parent = self
        var = self.vars.get(v, None)
        """ :type: ContextVariable|None """
        if var is None:
            self.vars[v] = inst
            # print "AbsScopeGet(%r).NewVar(%r, %r)" % (self.GetFullName(), V, inst)
        else:
            if not is_fn_type(inst.typ):
                # raise NameError("Cannot have a function share the same name as a variable")
                return var
            if var.typ.type_class_id == TYP_CLS_MULTI:
                assert isinstance(var, OverloadedCtxVar)
                var.add_ctx_var(inst)
                # print "AbsScopeGet(%r).NewVar(%r, %r) # OVERLOAD" % (self.GetFullName(), V, inst)
            else:
                if not is_fn_type(var.typ):
                    raise NameError("Cannot have a variable share the same name as a function")
                var = OverloadedCtxVar(v, [var, inst])
                var.parent = self
                self.vars[v] = var
                # print "AbsScopeGet(%r).NewVar(%r, %r) # OVERLOAD" % (self.GetFullName(), V, inst)
        inst.parent = self
        return inst

    def new_ns(self, ns, inst):
        """
        :param str ns:
        :param CompileContext inst:
        :rtype: CompileContext
        """
        self.namespaces[ns] = inst
        # TODO: change to using set_parent like `new_scope` defined below
        inst.parent = self
        return inst

    def new_scope(self, inst):
        """
        :param LocalScope inst:
        :rtype: LocalScope
        """
        self.scopes.append(inst)
        inst.set_parent(self, len(self.scopes) - 1)
        return inst

    def type_name(self, t):
        """
        :param str t:
        :rtype: ContextMember|None
        """
        rtn = self.type_name_strict(t)
        if rtn is None and self.parent is not None:
            return self.parent.type_name(t)
        return rtn

    def var_name(self, v):
        """
        :param str v:
        :rtype: ContextVariable|None
        """
        rtn = self.var_name_strict(v)
        if rtn is None and self.parent is not None:
            return self.parent.var_name(v)
        return rtn

    def namespace(self, ns):
        """
        :param str ns:
        :rtype: CompileContext|None
        """
        rtn = self.namespace_strict(ns)
        if rtn is None and self.parent is not None:
            return self.parent.namespace(ns)
        return rtn

    def type_name_strict(self, t):
        """
        :param str t:
        :rtype: ContextMember|None
        """
        return self.types.get(t, None)

    def var_name_strict(self, v):
        """
        :param str v:
        :rtype: ContextVariable|None
        """
        return self.vars.get(v, None)

    def namespace_strict(self, ns):
        """
        :param str ns:
        :rtype: CompileContext|None
        """
        return self.namespaces.get(ns, None)

    def get_strict(self, k):
        """
        :param str k:
        :rtype: ContextMember|None
        """
        rtn = self.vars.get(k, None)
        if rtn is not None:
            return rtn
        rtn = self.types.get(k, None)
        if rtn is not None:
            return rtn
        rtn = self.namespaces.get(k, None)
        return rtn

    def __getitem__(self, k):
        rtn = self.get(k)
        if rtn is None:
            raise KeyError("name '%s' was not found" % k)
        return rtn

    def get(self, k):
        """
        :param str k:
        :rtype: ContextMember|None
        """
        rtn = self.get_strict(k)
        if rtn is None and self.parent is not None:
            rtn = self.parent.get(k)
        return rtn

    def scoped_get(self, k0):
        """
        :param str k0:
        :rtype: ContextMember|None
        """
        return self.scoped_get_lst(k0.split("::"))

    def scoped_get_strict(self, k0):
        """
        :param str k0:
        :rtype: ContextMember|None
        """
        return self.scoped_get_lst_strict(k0.split("::"))

    def scoped_get_lst(self, lst_scope):
        """
        :param list[str] lst_scope:
        :rtype: ContextMember|None
        """
        # TODO: make the resolver resolve only absolute (no parent-inheritance), deferred to ScopedGetLst_Strict
        cur = self
        c = 0
        assert len(lst_scope) > 0
        if lst_scope[c] == "":
            while cur.parent is not None:
                cur = cur.parent
            c += 1
            if c >= len(lst_scope):
                return None
                # raise SyntaxError("bad global scope reference: '%s'" % "::".join(LstScope))
        end = len(lst_scope) - 1
        while c < end:
            cur = cur.namespace(lst_scope[c])
            if cur is None:
                return None
                # raise NameError("Bad name Resolution: '%s' is not in '%s'" % (LstScope[c], "::".join(LstScope[:c])))
            c += 1
        cur = cur[lst_scope[c]]
        if cur is None:
            return None
            # raise NameError("Bad name Resolution: '%s' is not in '%s'" % (LstScope[c], "::".join(LstScope[:c])))
        return cur

    def scoped_get_lst_strict(self, lst_scope):
        """
        :param list[str] lst_scope:
        :rtype: ContextMember|None
        """
        cur = self
        c = 0
        if lst_scope[c] == "":
            while cur.parent is not None:
                cur = cur.parent
            c += 1
            if c >= len(lst_scope):
                return None
                # raise SyntaxError("bad global scope reference: '%s'" % "::".join(LstScope))
        end = len(lst_scope) - 1
        while c < end:
            cur = cur.namespace_strict(lst_scope[c])
            if cur is None:
                return None
                # raise NameError("Bad name Resolution: '%s' is not in '%s'" % (LstScope[c], "::".join(LstScope[:c])))
            c += 1
        cur = cur.get_strict(lst_scope[c])
        if cur is None:
            return None
            # raise NameError("Bad name Resolution: '%s' is not in '%s'" % (LstScope[c], "::".join(LstScope[:c])))
        return cur

    def __contains__(self, k):
        """
        :param str k:
        :rtype: bool
        """
        return self.has_var(k) or self.has_type(k) or self.has_ns(k)

    def has_strict(self, k):
        """
        :param str k:
        :rtype: bool
        """
        return self.get_strict(k) is not None

    def which(self, k):
        """
        :param str k:
        :rtype: str
        """
        member = self.get(k)
        if member is None:
            return ""
        return member.get_full_name()
    # def __setitem__(self, k, v): raise NotImplementedError("NOT IMPLEMENTED")


class LocalScope(CompileContext):

    def __init__(self, name=""):
        super(LocalScope, self).__init__(name, None)
        self.host_scopeable = None
        self.lvl = 0
        self.scope_index = None
        # self.parent_decl = None
        # """ :type: (DeclStmnt, int)|None """
        # self.parent_loop = None
        # """ :type: ForLoop|WhileLoop|None """

    def set_parent(self, parent, index=None):
        """
        :param CompileContext parent:
        :param int index:
        """
        if self.parent is not parent:
            self.parent = parent
            lvl = 0
            self.host_scopeable = parent
            if parent.is_local_scope():
                assert isinstance(parent, LocalScope)
                self.host_scopeable = parent.host_scopeable
                lvl = parent.lvl + 1
            if lvl == 0 and len(self.name) == 0:
                raise SyntaxError("cannot create anonymous function scopes yes")
            for c, scope in enumerate(self.scopes):
                assert isinstance(scope, LocalScope)
                scope.set_parent(self, c)
        self.scope_index = index

    def is_local_scope(self):
        return True

    def new_var(self, v, inst):
        """
        :param str v:
        :param ContextVariable inst:
        :rtype: ContextVariable
        """
        vt = get_value_type(inst.typ)
        if vt.type_class_id == TYP_CLS_QUAL:
            assert isinstance(vt, QualType)
            if vt.qual_id == QualType.QUAL_FN:
                raise ValueError("Cannot define functions in LocalScope (attempt to define '%s')" % v)
        var = self.vars.get(v, None)
        if var is not None:
            raise NameError("Redefinition of Variable '%s' not allowed in LocalScope" % v)
        self.vars[v] = inst
        inst.parent = self
        return inst

    def has_ns(self, ns):
        return self.host_scopeable.has_ns(ns)

    def has_ns_strict(self, ns):
        return False

    def new_ns(self, ns, inst):
        raise ValueError("cannot create NameSpace in LocalScope")

    def namespace(self, ns):
        return self.host_scopeable.namespace(ns)

    def namespace_strict(self, ns):
        return None


def merge_type_context(typ, context):
    """
    :param EnumType|ClassType1|UnionType|StructType typ:
    :param CompileContext context:
    :rtype: CompileContext
    """
    other = context.type_name_strict(typ.name)
    assert other is None or isinstance(other, (ClassType, StructType, UnionType, EnumType)), (
            "Issue: %s is not a Composite Type" % repr(other)
    )
    # TODO: account for other = typedef
    if other is None:
        if typ.defined:
            other = context.new_type(typ.name, typ)
        else:
            other = context.type_name(typ.name)
            if other is None:
                other = context.new_type(typ.name, typ)
    elif typ.defined and other.defined:
        raise NameError("Redefinition of Typename '%s' not allowed" % typ.name)
    elif typ.defined:
        typ.merge_to(other)
    return other


def merge_ns_context(ns, context):
    other = context.NS_Strict(ns.name)
    # TODO: account for other = typedef
    if other is None:
        other = context.new_ns(ns.name, ns)
    elif ns.defined and other.defined:
        raise NameError("Redefinition of Namespace '%s' not allowed (yet)" % ns.name)
    elif ns.defined:
        ns.merge_to(other)
    return other


class EnumType(CompileContext, BaseType):
    def to_user_str(self):
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TYP_CLS_ENUM
    mangle_captures = {
        'E': None
    }

    @classmethod
    def from_mangle(cls, s, c):
        """
        :param str s:
        :param int c:
        :rtype: (EnumType, int)
        """
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return EnumType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "E%u%s" % (len(name), name)

    def __init__(self, parent, name=None, incomplete=True, variables=None, defined=False, the_base_type=None):
        """
        :param CompileContext|None parent:
        :param str|None name:
        :param bool incomplete:
        :param dict[str,ContextVariable]|None variables:
        :param bool defined:
        :param BaseType|None the_base_type:
        """
        super(EnumType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.the_base_type = the_base_type
        if variables is not None:
            self.vars.update(variables)
        self.defined = defined

    def compile_var_init(self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None):
        return self.the_base_type.compile_var_init(cmpl_obj, init_args, context, ref, cmpl_data, temp_links)

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((
            self.parent, self.name, self.incomplete, self.vars, self.defined, self.the_base_type))

    def merge_to(self, other):
        assert isinstance(other, EnumType)
        super(EnumType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.the_base_type = self.the_base_type
        other.defined = self.defined

    def build(self, tokens, c, end, context):
        # TODO: (mentioned later in this function)
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(tokens, c, "Expected a Type to follow ':' in enum declaration")
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, c, "Expected closing '}' for enum")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].type_id == CLS_NAME:
                    name = tokens[c].str
                    if self.has_var_strict(name):
                        raise ParsingError(tokens, c, "Redefinition of enumerated name: '%s'" % name)
                    expr, c = get_expr(tokens, c, ",", end_p, context)
                    self.new_var(name, ContextVariable(name, self.the_base_type).const_init(expr))
                    # TODO: assert ConstExpr
                else:
                    raise ParsingError(tokens, c, "Expected type_id=CLS_NAME Token in enum")
                c += 1
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def is_namespace(self):
        return False

    def is_type(self):
        return True


def get_strict_stmnt(tokens, c, end, context):
    assert isinstance(context, (ClassType, StructType, UnionType))
    # TODO: place all members in host_scopeable (allows for scoped 'using' [namespace])
    start = c
    pos = len(LST_STMNT_NAMES)
    if tokens[c].type_id == CLS_NAME and tokens[c].str == context.name and tokens[c + 1].str == "(":
        pos = STMNT_DECL
    elif tokens[c].type_id == CLS_NAME and is_type_name_part(tokens[c].str, context):
        pos = STMNT_DECL
    if pos == len(LST_STMNT_NAMES):
        try:
            pos = LST_STMNT_NAMES.index(tokens[c].str)
        except ValueError:
            pass
    rtn = None
    if pos == STMNT_CURLY_STMNT:
        rtn = CurlyStmnt()
        c = rtn.build(tokens, c, end, context)
        if start == c:
            raise ParsingError(tokens, c, "Expected only '{' statement (not expression)")
    elif pos == STMNT_DECL:
        rtn = DeclStmnt()
        # print "Before c = %u, end = %u, STMNT_DECL" % (c, end)
        c = rtn.build(tokens, c, end, context)
        # print "After c = %u, end = %u, STMNT_DECL" % (c, end)
    elif pos == STMNT_TYPEDEF:
        rtn = TypeDefStmnt()
        c = rtn.build(tokens, c, end, context)
    if rtn is None:
        raise ParsingError(tokens, c, "Expected only '{' statement or decl statement for strict statement")
    return rtn, c


def tok_to_str(tok):
    """
    :param ParseClass tok:
    :rtype: unicode|str
    """
    return tok.str


class ClassType(CompileContext, BaseType):
    def to_user_str(self):
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_init(self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TYP_CLS_CLASS
    mangle_captures = {
        'K': None
    }

    @classmethod
    def from_mangle(cls, s, c):
        """
        :param str s:
        :param int c:
        :rtype: (ClassType1, int)
        """
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return ClassType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "K%u%s" % (len(name), name)

    def __init__(self, parent, name=None, incomplete=True,
                 definition=None, var_order=None, defined=False, the_base_type=None):
        """
        :param CompileContext|None parent:
        :param unicode|str|None name:
        :param bool incomplete:
        :param dict[str,int] definition:
        :param list[ContextVariable] var_order:
        :param bool defined:
        :param BaseType|None the_base_type:
        """
        super(ClassType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.var_order = [] if var_order is None else var_order
        self.defined = defined
        self.the_base_type = the_base_type

    def offset_of(self, attr):
        """
        :param str attr:
        :rtype: int
        """
        # TODO: improve speed of OffsetOf by tracking the offsets along-side the types
        index = self.definition[attr]
        off = 0
        for c in range(index):
            off += size_of(self.var_order[0].typ)
        return off

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((
            self.parent, self.name, self.incomplete, self.definition, self.var_order, self.defined, self.the_base_type))

    def merge_to(self, other):
        assert isinstance(other, ClassType)
        super(ClassType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.var_order = self.var_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(self, tokens, c, end, context):
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(tokens, c, "Expected a Type to follow ':' in class declaration")
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, start, "Expected closing '}' for class")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].str in {"public", "private", "protected"}:
                    # TODO: IDEA: store a current access specifier variable
                    # TODO:   then combine that with inst in the definition of function: 'NewVar(self, V, inst)'
                    raise ParsingError(tokens, c, "access specifier keywords not allowed")
                stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def new_var(self, v, inst):
        """
        :param str v:
        :param ContextVariable inst:
        :rtype: ContextVariable
        """
        if inst.mods == ContextVariable.MOD_STATIC:
            return super(ClassType, self).new_var(v, inst)
        self.definition[v] = len(self.var_order)
        self.var_order.append(inst)
        return inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


class StructType(CompileContext, BaseType):
    def to_user_str(self):
        """
        :rtype: str
        """
        return "struct " + self.name

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TYP_CLS_STRUCT
    mangle_captures = {
        'B': None
    }

    @classmethod
    def from_mangle(cls, s, c):
        """
        :param str s:
        :param int c:
        :rtype: (StructType, int)
        """
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return StructType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "B%u%s" % (len(name), name)

    def __init__(self, parent, name=None, incomplete=True,
                 definition=None, var_order=None, defined=False, the_base_type=None):
        """
        :param CompileContext|None parent:
        :param unicode|str|None name:
        :param bool incomplete:
        :param dict[str,int] definition:
        :param list[ContextVariable] var_order:
        :param bool defined:
        :param BaseType|None the_base_type:
        """
        super(StructType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.var_order = [] if var_order is None else var_order
        self.defined = defined
        self.the_base_type = the_base_type

    def offset_of(self, attr):
        """
        :param str attr:
        :rtype: int
        """
        # TODO: improve speed of OffsetOf by tracking the offsets along-side the types
        index = self.definition[attr]
        off = 0
        for c in range(index):
            off += size_of(self.var_order[0].typ)
        return off

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((
            self.parent, self.name, self.incomplete, self.definition, self.var_order, self.defined, self.the_base_type))

    def merge_to(self, other):
        assert isinstance(other, StructType)
        super(StructType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.var_order = self.var_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(self, tokens, c, end, context):
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(tokens, c, "Expected a Type to follow ':' in class declaration")
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, start, "Expected closing '}' for struct")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].str in {"public", "private", "protected"}:
                    # TODO: IDEA: store a current access specifier variable
                    # TODO:   then combine that with inst in the definition of function: 'NewVar(self, V, inst)'
                    raise ParsingError(tokens, c, "access specifier keywords not allowed")
                try:
                    stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
                except ParsingError:
                    print("self.name = " + repr(self.name))
                    raise
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def compile_var_init(self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param list[BaseExpr|CurlyStmnt] init_args:
        :param CompileContext context:
        :param VarRef ref:
        :param LocalCompileData|None cmpl_data:
        :param list[(BaseType,BaseLink)]|None temp_links:
        """
        if self.incomplete:
            raise TypeError("struct %s is incomplete" % self.name)
        link = None
        name = None
        ctx_var = None
        is_local = True
        sz_var = size_of(self)
        if ref.ref_type == VAR_REF_TOS_NAMED:
            assert isinstance(ref, VarRefTosNamed)
            ctx_var = ref.ctx_var
            if ctx_var is not None:
                assert isinstance(ctx_var, ContextVariable)
                name = ctx_var.get_link_name()
                is_local = ctx_var.parent.is_local_scope()
                if not is_local:
                    assert isinstance(cmpl_obj, Compilation)
                    cmpl_obj1 = cmpl_obj.spawn_compile_object(CMPL_T_GLOBAL, name)
                    cmpl_obj1.memory.extend([0] * sz_var)
                    link = cmpl_obj.get_link(name)
        elif ref.ref_type == VAR_REF_LNK_PREALLOC:
            assert isinstance(ref, VarRefLnkPrealloc)
            if len(init_args) == 0:
                return sz_var
            link = ref.lnk
        else:
            raise TypeError("Unrecognized VarRef: %s" % repr(ref))
        if len(init_args) > 1:
            raise TypeError("Cannot instantiate struct types with more than one argument")
        if link is None:
            assert is_local
            assert cmpl_data is not None, "Expected cmpl_data to not be None for LOCAL"
            if len(init_args) == 0:
                sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
            else:
                expr = init_args[0]
                typ = expr.t_anot
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(typ)
                assert compare_no_cvr(self, src_vt), "self = %s, SrvVT = %s" % (
                    get_user_str_from_type(self), get_user_str_from_type(src_vt))
                sz = compile_expr(cmpl_obj, expr, context, cmpl_data, src_pt, temp_links)
                if is_src_ref:
                    assert sz == 8
                    sz_cls = (sz_var.bit_length() - 1)
                    assert sz_var == (1 << sz_cls)
                    cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                else:
                    assert sz == sz_var
            if ctx_var is not None:
                cmpl_data.put_local(ctx_var, name, sz_var, None, True)
        else:
            assert cmpl_data is None, "Expected cmpl_data to be None for GLOBAL"
            assert isinstance(cmpl_obj, Compilation)
            assert ctx_var is None or isinstance(ctx_var, ContextVariable)
            var_name = "<NONE>" if ctx_var is None else ctx_var.name
            assert name is not None
            if len(init_args):
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(init_args[0].t_anot)
                err0 = "Expected Expression sz == %s, but %u != %u (name = %r, linkName = '%s', expr = %r)"
                if is_src_ref:
                    sz = compile_expr(cmpl_obj, init_args[0], context, cmpl_data, src_pt, temp_links)
                    assert sz == 8, err0 % ("sizeof(void*)", sz, 8, var_name, name, init_args[0])
                    sz_cls = sz_var.bit_length() - 1
                    assert sz_var == 1 << sz_cls
                    cmpl_obj.memory.extend([
                        BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                else:
                    sz = compile_expr(cmpl_obj, init_args[0], context, cmpl_data, src_vt, temp_links)
                    assert sz == sz_var, err0 % ("sz_var", sz, sz_var, var_name, name, init_args[0])
                link.emit_stor(cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic)
        return sz_var

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        return -1

    def new_var(self, v, inst):
        """
        :param str v:
        :param ContextVariable inst:
        :rtype: ContextVariable
        """
        if inst.mods == ContextVariable.MOD_STATIC:
            return super(StructType, self).new_var(v, inst)
        self.definition[v] = len(self.var_order)
        self.var_order.append(inst)
        return inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


class UnionType(CompileContext, BaseType):
    def to_user_str(self):
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_init(self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TYP_CLS_UNION
    mangle_captures = {
        'U': None
    }

    @classmethod
    def from_mangle(cls, s, c):
        """
        :param str s:
        :param int c:
        :rtype: (UnionType, int)
        """
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return UnionType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "U%u%s" % (len(name), name)

    def __init__(self, parent, name=None, incomplete=True, definition=None, defined=False, the_base_type=None):
        """
        :param CompileContext|None parent:
        :param str|None name:
        :param bool incomplete:
        :param dict[str,ContextVariable]|None definition:
        :param bool defined:
        :param BaseType|None the_base_type:
        """
        super(UnionType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.defined = defined
        self.the_base_type = the_base_type

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((
            self.parent, self.name, self.incomplete, self.definition, self.defined, self.the_base_type))

    def merge_to(self, other):
        assert isinstance(other, UnionType)
        super(UnionType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(self, tokens, c, end, context):
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            raise ParsingError(tokens, c, "Inheritance is not allowed for unions")
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, start, "Expected closing '}' for union")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].str in {"public", "private", "protected"}:
                    # TODO: IDEA: store a current access specifier variable
                    # TODO:   then combine that with inst in the definition of function: 'NewVar(self, V, inst)'
                    raise ParsingError(tokens, c, "access specifier keywords not allowed")
                stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def new_var(self, v, inst):
        assert isinstance(inst, ContextVariable)
        if inst.mods == ContextVariable.MOD_STATIC:
            super(UnionType, self).new_var(v, inst)
        else:
            self.definition[v] = inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


MetaTypeCtors = [EnumType, ClassType, StructType, UnionType]


'''def GetTypeName(tokens, c, end, context, Strict=False):
    type_name = TypeNameInf()
    try:
        c = type_name.build(tokens, c, end, context)
    except Exception as Exc:
        if Strict:
            raise
        else: return None, c
    return type_name, c'''

# TODO: find out why MyGetExprPart(..from LangTest.py, 107, 391, ..context) returns ?, 2


@try_catch_wrapper0
def my_get_expr_part(tokens, c, end, context):
    """
    :param list[ParseClass] tokens:
    :param int c:
    :param int end:
    :param CompileContext context:
    :rtype: (BaseOpPart, int)
    """
    s = tokens[c].str
    if LiteralExpr.is_literal_token(tokens[c]):
        rtn = LiteralExpr()
        c = rtn.build(tokens, c, end, context)
        return ExprOpPart(rtn), c
    elif s == ".":
        line, col = tokens[c].line, tokens[c].col
        c += 1
        if tokens[c].type_id != CLS_NAME:
            raise ParsingError(tokens, c, "expected name after '.'")
        s += tokens[c].str
        c += 1
        return SimpleOpPart(BreakSymClass(s, line, col)), c
    elif s == "->":
        line, col = tokens[c].line, tokens[c].col
        c += 1
        if tokens[c].type_id != CLS_NAME:
            raise ParsingError(tokens, c, "expected name after '.'")
        s += tokens[c].str
        c += 1
        return SimpleOpPart(OperatorClass(s, line, col)), c
    elif s in DCT_FIXES:
        rtn = SimpleOpPart(tokens[c])
        c += 1
        return rtn, c
    elif s == "(":
        lvl = 1
        start = c
        c += 1
        comma_count = 0
        while lvl > 0:
            s = tokens[c].str
            if s in OPEN_GROUPS:
                lvl += 1
            elif s in CLOSE_GROUPS:
                lvl -= 1
            elif s == "," and lvl == 1:
                comma_count += 1
            c += 1
        end_t = c
        end_p = end_t - 1
        c = start + 1
        if c == end_p:
            c = end_t
            return ParenthOpPart([]), c
        if comma_count == 0:
            type_name, c = proc_typed_decl(tokens, c, end_p, context)
            if c > start + 1 and type_name is not None:
                assert isinstance(type_name, IdentifiedQualType)
                if type_name.name is not None:
                    print("WARN: (c = %u) Unexpected name in C-Style Cast Operator: '%s'" % (c, type_name.name))
                c = end_t
                return CastOpPart(type_name.typ), c
        lst_expr = [None] * (comma_count + 1)
        n_expr = 0
        while c < end_p:
            lst_expr[n_expr], c = get_expr(tokens, c, ",", end_p, context)
            c += 1
            n_expr += 1
        return ParenthOpPart(lst_expr), c
    elif s == "[":
        c += 1
        expr, c = get_expr(tokens, c, "]", end, context)
        if tokens[c].str != "]":
            raise ParsingError(tokens, c, "Only single expression inside '[' and ']' is allowed")
        c += 1
        return SParenthOpPart(expr), c
    elif s == "{":
        expr = CurlyExpr()
        # TODO: fix the incorrect usage (will throw error if '}' is encountered)
        c = expr.build(tokens, c, end, context)
        c += 1  # TODO: verify this is correct usage of return value
        return ExprOpPart(expr), c
    elif s == "?":
        c += 1
        expr, c = get_expr(tokens, c, ":", end, context)
        c += 1
        return InlineIfOpPart(expr), c
    elif tokens[c].type_id == CLS_NAME:
        rtn = NameRefExpr()
        c = rtn.build(tokens, c, end, context)
        return ExprOpPart(rtn), c
    else:
        raise ParsingError(tokens, c, "Unrecognized Token Type")


def mk_postfix(tokens, c, end, context, get_expr_part, delim=None, l_t_r=None):
    """
    :param list[ParseClass] tokens:
    :param int c:
    :param int end:
    :param CompileContext context:
    :param (list[ParseClass],int,int,CompileContext) -> (BaseOpPart, int) get_expr_part:
    :param str|None delim:
    :param dict[int,bool]|list[bool]|None l_t_r:
    """
    if l_t_r is None:
        l_t_r = LST_LTR_OPS
    op_stack = list()
    rtn = list()
    prev_op = None
    tok = None
    if delim is not None and tokens[c].str == delim:
        return [], c
    next_item, c = get_expr_part(tokens, c, end, context)
    while next_item is not None:
        prev = tok
        tok = next_item
        if c >= end or (delim is not None and tokens[c].str == delim):
            next_item = None
        else:
            # TODO temporary
            next_item, c = get_expr_part(tokens, c, end, context)
        # format = tuple of:
        #   Number of operands,
        #   token,
        #   precedence,
        #   a key in {1:prefix operator, 3: infix operator, 2: postfix operator}
        next_op = None
        is_prefix, is_infix, is_postfix = tok.can_prefix, tok.can_infix, tok.can_postfix
        the_sum = is_prefix + is_infix + is_postfix
        if tok.can_nofix:
            assert not is_prefix, "prefix operators cannot nofix (disambiguation requires backtracking)"
        if tok.is_expr:
            next_op = (0, tok)
        elif the_sum == 1:
            if tok.can_nofix and (prev_op is None or take_next(prev_op)):
                next_op = (0, tok)
            elif is_prefix:
                next_op = (1, tok, tok.prefix_lvl, 1)
            elif is_infix:
                next_op = (2, tok, tok.infix_lvl, 3)
            elif is_postfix:
                next_op = (1, tok, tok.postfix_lvl, 2)
            else:
                raise ValueError("Unknown error occurred: c = %u" % c)
        elif the_sum == 2:
            end_type = 0
            if tok.can_nofix and (prev_op is None or take_next(prev_op)):
                end_type = 0
            elif is_prefix and is_postfix:
                if prev_op is None or take_next(prev_op):
                    end_type = 1
                else:
                    end_type = 2
            elif is_infix and is_postfix:
                if prev_op is None:
                    raise ParsingError(tokens, c, "postfix/infix operator must appear after an expression")
                elif take_next(prev_op):
                    raise ParsingError(tokens, c, "Previous operator cannot directly capture infix or postfix")
                if next_item.is_expr:  # its prefix
                    end_type = 1  # TODO: verify changed 2 -> 1 is it correct? (also postfix->prefix)
                else:
                    t_take_prev = [next_item.postfix_lvl, next_item.infix_lvl]
                    if None in t_take_prev:
                        t_take_prev.remove(None)
                    if len(t_take_prev) == 2:
                        t_take_prev = min(t_take_prev)
                    else:
                        t_take_prev = t_take_prev[0]
                    t_not_take_prev = next_item.prefix_lvl
                    if t_take_prev is not None and t_not_take_prev is None:
                        end_type = 3  # tok is infix
                    elif t_take_prev is not None:
                        if t_take_prev > t_not_take_prev:
                            end_type = 3
                        else:
                            end_type = 2
                    elif t_not_take_prev is not None:
                        end_type = 3
                    else:  # tok is postfix
                        end_type = 2
            elif is_infix and is_prefix:
                if prev is None or take_next(prev_op):
                    end_type = 1
                else:
                    end_type = 3
            if end_type == 1:  # Prefix
                next_op = (1, tok, tok.prefix_lvl, 1)
            elif end_type == 2:  # Postfix
                next_op = (1, tok, tok.postfix_lvl, 2)
            elif end_type == 3:  # Infix
                next_op = (2, tok, tok.infix_lvl, 3)
            else:  # Nofix
                next_op = (0, tok)
        elif the_sum == 3:
            raise ParsingError(tokens, c, "Operators must only be able to be one of prefix, infix, or postfix")
        elif prev_op is not None:
            fix = 0
            if not take_next(prev_op):  # REMEMBER: tok is in Syms ^^^^
                fix |= 2
            lst_lvls = list(filter(lambda x: x[1] is not None, (
                next_item.prefix_lvl,
                next_item.infix_lvl,
                next_item.postfix_lvl)))
            if len(lst_lvls) == 0:
                fix |= 1  # cur is definitely going to capture next_item
            elif len(lst_lvls) == 1:
                if lst_lvls[0][0] == 0:
                    fix |= 1
                # otherwise it is not prefix
            else:
                pick = min(lst_lvls, key=lambda x: x[1])
                if pick[0] == 0:
                    fix |= 1
        elif prev.can_infix:  # but it could be multi -- edit: ignore multi
            # print c, tok
            if take_next(prev_op):  # tok: prefix unary operator,.
                next_op = (1, tok, tok.prefix_lvl, 1)
            elif take_prev(prev_op):  # tok: binary operator
                next_op = (2, tok, tok.infix_lvl, 3)
            else:
                raise ParsingError(tokens, c, "Invalid operator fixness or usage")
                # print("Unknown: rtn=%r, c=%r, prev=%r, tok=%r, next_item=%r" % (rtn, c, prev, tok, next_item))
        elif next_item.can_infix:
            if tok.can_infix and next_item.can_prefix:  # tok: binary operator
                next_op = (2, tok, tok.infix_lvl, 3)
            elif next_item.can_infix and tok.can_postfix:  # tok: Postfix unary operator
                next_op = (1, tok, tok.postfix_lvl, 2)
            else:
                raise ParsingError(tokens, c, "two operators cannot be the same type (binary, post-unary, pre-unary")
        else:
            if prev is None:
                if not tok.can_prefix:
                    raise ParsingError(tokens, c, "operator misused as postfix at BOL (it cannot be postfix)")
                next_op = (1, tok, tok.prefix_lvl, 1)
            elif next_item is None:
                if not tok.can_postfix:
                    raise ParsingError(tokens, c, "operator misused as prefix at EOL (it cannot be prefix)")
                next_op = (1, tok, tok.prefix_lvl, 2)
            elif tok.can_infix and not prev.can_infix and not next_item.can_infix:
                next_op = (2, tok, tok.infix_lvl, 2)
            else:
                raise ParsingError(
                    tokens, c, "could not resolve prev = %r, tok = %r, next_item = %r" % (prev, tok, next_item)
                )
        if next_op is None:
            pass
        elif next_op[0] > 0:
            if len(op_stack) > 0:
                lvl0 = op_stack[-1][2]
                lvl1 = next_op[2]
                if lvl1 > lvl0 or (lvl1 == lvl0 and l_t_r[lvl0]):
                    rtn.append(op_stack.pop())
            op_stack.append(next_op)
        else:
            rtn.append(next_op)
        prev_op = next_op
    rtn.extend(op_stack[::-1])
    # time.sleep(.2)
    # print "All the Postfix:\n  ", "\n  ".join(map(repr, rtn))
    # print "  prev_op=%r" % list(prev_op)
    # print "  next_op=%r" % list(next_op)
    # time.sleep(.2)
    return rtn, c


@try_catch_wrapper1
def get_expr(tokens, c, delim, end, context):
    """

    :param list[ParseClass] tokens:
    :param int c:
    :param str|None delim:
    :param int end:
    :param CompileContext context:
    :rtype: (None|BaseExpr, int)
    """
    # TODO: complete
    start = c
    rtn, c = mk_postfix(tokens, c, end, context, my_get_expr_part, delim)
    # print "All the Postfix:\n  ", "\n  ".join(map(repr, rtn))
    # time.sleep(.2)
    stack = list()
    for Part in rtn:
        if len(stack) < Part[0]:
            print(stack, Part)
            raise ParsingError(tokens, c, "Insufficient number of operands for operator: %r" % Part[1])
        if Part[0] == 0:
            try:
                stack.append(Part[1].build([], 0))  # nofix
            except Exception as exc:
                del exc
                print("c = %u" % c)
                raise
        elif Part[0] == 1:
            op_part = Part[1]
            assert isinstance(op_part, BaseOpPart)
            if len(stack) < 1:
                raise ParsingError(tokens, c, "expected operands for prefix/postfix operator: %s" % op_part.txt)
            a = stack.pop()
            try:
                stack.append(op_part.build([a], Part[3]))  # prefix/postfix
            except Exception as exc:
                del exc
                print("c = %u" % c)
                raise
        elif Part[0] == 2:
            op_part = Part[1]
            assert isinstance(op_part, BaseOpPart)
            b = stack.pop()
            a = stack.pop()
            try:
                stack.append(op_part.build([a, b], Part[3]))  # infix
            except Exception as exc:
                del exc
                print(get_user_str_parse_pos(tokens, c))
                raise
        else:
            raise ParsingError(tokens, c, "Unexpected number of required operands")
    if len(stack) == 0 and start == c:
        return None, c
    if len(stack) != 1:
        raise ParsingError(tokens, c, "Expected single expression got %s" % repr(stack))
    return stack[0], c


def compile_lang(tokens):
    """
    :param list[ParseClass] tokens:
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
        "sys_out", ContextVariable(
            "sys_out", QualType(
                QualType.QUAL_FN,
                PrimitiveType.from_str_name(['int']),
                [
                    QualType(
                        QualType.QUAL_PTR,
                        QualType(
                            QualType.QUAL_CONST,
                            PrimitiveType.from_str_name(["char"])
                        )
                    ),
                    PrimitiveType.from_str_name(["void"])
                ]
            )
        )
    )
    rtn = CurlyStmnt(None, "MAIN")
    c = rtn.build(tokens, c, end, global_ctx)
    if c == start:
        raise SyntaxError("Source Code must have semi-colons (';') in the top-level scope")
    return rtn, global_ctx


def size_of(typ, is_arg=False):
    if isinstance(typ, QualType):
        if typ.qual_id == QualType.QUAL_ARR:
            if is_arg or typ.ext_inf is None:
                return 8
            return size_of(typ.tgt_type) * typ.ext_inf
        elif typ.qual_id in {QualType.QUAL_FN, QualType.QUAL_PTR, QualType.QUAL_REF}:
            return 8
        elif typ.qual_id in {QualType.QUAL_CONST, QualType.QUAL_DEF, QualType.QUAL_REG, QualType.QUAL_VOLATILE}:
            return size_of(typ.tgt_type)
        else:
            raise ValueError("Unrecognized QualType.qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return size_of(typ.typ)
    elif isinstance(typ, PrimitiveType):
        return typ.size
    elif isinstance(typ, EnumType):
        return size_of(typ.the_base_type)
    elif isinstance(typ, (StructType, ClassType)):
        sz = 0 if typ.the_base_type is None else size_of(typ.the_base_type)
        # TODO: add 'packed' boolean attribute to StructType and ClassType1
        for ctx_var in typ.var_order:
            sz += size_of(ctx_var.typ)
        return sz
    elif isinstance(typ, UnionType):
        # TODO: remove BaseType from UnionType
        sz = 0
        for k in typ.definition:
            v = typ.definition[k]
            assert isinstance(v, ContextVariable)
            sz = max(sz, size_of(v.typ))
        return sz
    else:
        raise TypeError("Unrecognized type: %s" % typ.__class__.__name__)
    # TODO: add Typedef support
# Compare types ignoring [C]onst [V]olatile and [R]egister


def compare_no_cvr(type_a, type_b, ignore_ref=False):
    """
    :param BaseType type_a:
    :param BaseType type_b:
    :param bool ignore_ref:
    :rtype: bool
    """
    type_a = get_value_type(type_a) if ignore_ref else get_base_prim_type(type_a)
    type_b = get_value_type(type_b) if ignore_ref else get_base_prim_type(type_b)
    while type_a.type_class_id == TYP_CLS_QUAL and type_b.type_class_id == TYP_CLS_QUAL:
        assert isinstance(type_a, QualType)
        assert isinstance(type_b, QualType)
        if type_a.qual_id != type_b.qual_id:
            return False
        elif type_a.qual_id == QualType.QUAL_FN:
            if len(type_a.ext_inf) != len(type_b.ext_inf):
                return False
            if not compare_no_cvr(type_a.tgt_type, type_b.tgt_type):
                return False
            for c in range(len(type_a.ext_inf)):
                if not compare_no_cvr(type_a.ext_inf[c], type_b.ext_inf[c]):
                    return False
            return True
        elif type_a.qual_id == QualType.QUAL_ARR:
            if type_a.ext_inf is not None and type_b.ext_inf is not None:
                if type_a.ext_inf != type_b.ext_inf:
                    return False
        type_a = get_base_prim_type(type_a.tgt_type)
        type_b = get_base_prim_type(type_b.tgt_type)
    if type_a.type_class_id != type_b.type_class_id:
        return False
    elif type_a.type_class_id == TYP_CLS_PRIM:
        assert isinstance(type_a, PrimitiveType)
        assert isinstance(type_b, PrimitiveType)
        return type_a.typ == type_b.typ and type_a.sign == type_b.sign
    else:
        assert isinstance(type_a, (EnumType, UnionType, StructType, ClassType))
        assert isinstance(type_b, (EnumType, UnionType, StructType, ClassType))
        assert type_a.parent is not None, "parent should not be None"
        assert type_b.parent is not None, "parent should not be None"
        if type_a.parent is not type_b.parent:
            return False
        elif type_a.name != type_b.name:
            return False
    return True


class TempInfo(object):
    def __init__(self):
        self.temporaries = []
        """ :type: list[(BaseType, LocalRef)] """
    def alloc_temporary(self, cmpl_data, typ):
        """
        :param LocalCompileData cmpl_data:
        :param BaseType typ:
        :rtype: int
        """


def try_catch_wrapper_co_expr(fn):
    def new_fn(cmpl_obj, expr, context, cmpl_data=None, type_coerce=None, temp_links=None):
        """
        :param BaseCmplObj cmpl_obj:
        :param BaseExpr expr:
        :param CompileContext context:
        :param LocalCompileData|None cmpl_data:
        :param BaseType|None type_coerce:
        :param list[(BaseType,BaseLink)]|None temp_links:
        """
        try:
            return fn(cmpl_obj, expr, context, cmpl_data, type_coerce, temp_links)
        except Exception as exc:
            del exc
            print("%s: cmpl_obj = %r, expr = %r, context = %r, cmpl_data = %r, type_coerce = %r, temp_links = %r" % (
                fn.__name__, cmpl_obj, expr, context, cmpl_data, type_coerce, temp_links))
            raise
    new_fn.__name__ = new_fn.__name__ = fn.__name__ + "__wrapped"
    return new_fn


parsing_vars = {}


def compile_bin_op_expr(cmpl_obj, expr, context, cmpl_data, type_coerce, temp_links, res_type):
    """
    :param res_type:
    :param BaseCmplObj cmpl_obj:
    :param BinaryOpExpr expr:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    :param BaseType|None type_coerce:
    :param list[(BaseType,BaseLink)]|None temp_links:
    :rtype: (int, BaseType)
    """
    assert expr.t_anot is not None
    typ = None
    is_flt = False
    is_sign = False
    sz_type = 8
    sz_cls = 3
    inc_by = 1
    inc_by_before = True
    if expr.op_fn_type == OP_TYP_PTR_GENERIC:
        src_pt, typ, is_src_ref = get_tgt_ref_type(expr.a.t_anot)
        assert isinstance(typ, QualType)
        assert typ.qual_id == QualType.QUAL_PTR
        if expr.op_fn_data < 2:
            is_sign = bool(expr.op_fn_data & 1)
        else:
            assert expr.op_fn_data == 2
            is_sign = True
    elif expr.op_fn_type == OP_TYP_NATIVE:
        # src_pt = get_base_prim_type(expr.a.t_anot)
        typ = prim_types[expr.op_fn_data]
        is_flt = typ.typ in FLT_TYPE_CODES
        is_sign = typ.sign
        sz_type = typ.size
        sz_cls = sz_type.bit_length() - 1
    if typ is None:
        raise NotImplementedError("Not Implemented: op_fn_type = %u" % expr.op_fn_type)
    assert (1 << sz_cls) == sz_type
    sz1 = 0
    if expr.type_id in ASSIGNMENT_OPS:
        sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
        assert sz == 8, "Expression should be a reference"
        sz1 += sz
        res_none = type_coerce is void_t
        if res_none:
            res_type = void_t
        else:
            cmpl_obj.memory.extend([
                BC_LOAD, BCR_TOS | BCR_SZ_8])
            sz1 += 8
        if expr.type_id != BINARY_ASSGN:
            cmpl_obj.memory.extend([
                BC_LOAD, BCR_TOS | BCR_SZ_8,
                BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)
            ])
            sz1 += sz_type
        try:
            if expr.type_id not in [BINARY_ASSGN_LSHIFT, BINARY_ASSGN_RSHIFT]:
                assert compare_no_cvr(expr.b.t_anot, typ), "expr.b.t_anot = %s, typ = %s, expr = %s" % (
                    get_user_str_from_type(expr.b.t_anot), get_user_str_from_type(typ),
                    format_pretty(expr)
                )
            else:
                assert compare_no_cvr(expr.b.t_anot, PrimitiveType.from_type_code(INT_C, 1)), "expr.b.t_anot = %s, typ = %s, expr = %s" % (
                    get_user_str_from_type(expr.b.t_anot), get_user_str_from_type(typ),
                    format_pretty(expr)
                )
        except:
            parsing_vars["expr"] = expr
            parsing_vars["context"] = context
            parsing_vars["cmpl_obj"] = cmpl_obj
            raise
        sz_type1 = sz_type
        if expr.type_id in [BINARY_ASSGN_LSHIFT, BINARY_ASSGN_RSHIFT]:
            sz_type1 = 1
            sz = compile_expr(cmpl_obj, expr.b, context, cmpl_data, PrimitiveType.from_type_code(INT_C, 1), temp_links)
        else:
            sz = compile_expr(cmpl_obj, expr.b, context, cmpl_data, typ, temp_links)
        if inc_by != 1 and inc_by_before:
            emit_load_i_const(cmpl_obj.memory, inc_by, is_sign, sz_cls)
            cmpl_obj.memory.extend([BC_MUL1 + 2 * sz_cls + int(is_sign)])
        sz1 += sz
        assert sz_type1 == sz, "sz_type1 = %u, sz = %u; expr.b.t_anot = %s, typ = %s, expr.b = %r" % (
            sz_type, sz, get_user_str_from_type(expr.b.t_anot), get_user_str_from_type(typ), expr.b)
        if expr.type_id != BINARY_ASSGN:
            op_code_u, op_code_s, op_code_f = {
                BINARY_ASSGN_MOD: (BC_MOD1, BC_MOD1S, BC_FMOD_2),
                BINARY_ASSGN_DIV: (BC_DIV1, BC_DIV1S, BC_FDIV_2),
                BINARY_ASSGN_MUL: (BC_MUL1, BC_MUL1S, BC_FMUL_2),
                BINARY_ASSGN_MINUS: (BC_SUB1, BC_SUB1, BC_FSUB_2),
                BINARY_ASSGN_PLUS: (BC_ADD1, BC_ADD1, BC_FADD_2),
                BINARY_ASSGN_AND: (BC_AND1, BC_AND1, BC_NOP),
                BINARY_ASSGN_OR: (BC_OR1, BC_OR1, BC_NOP),
                BINARY_ASSGN_XOR: (BC_XOR1, BC_XOR1, BC_NOP),
                BINARY_ASSGN_RSHIFT: (BC_RSHIFT1, BC_RSHIFT1, BC_NOP),
                BINARY_ASSGN_LSHIFT: (BC_LSHIFT1, BC_LSHIFT1, BC_NOP),
            }[expr.type_id]
            op_code = BC_NOP
            if is_flt:
                if op_code_f != BC_NOP:
                    op_code = op_code_f - 1 + sz_cls
            else:
                op_code = op_code_s if is_sign else op_code_u
                if op_code != BC_NOP:
                    op_code += sz_cls if op_code_s == op_code_u else (2 * sz_cls)
            if op_code == BC_NOP:
                raise ValueError("Unsupported operator %s" % LST_BIN_OP_ID_MAP[expr.type_id])
            cmpl_obj.memory.append(op_code)
            sz1 -= sz_type1
        cmpl_obj.memory.extend([
            BC_SWAP, (sz_cls << 3) | BCS_SZ8_A,
            BC_STOR, BCR_ABS_S8 | (sz_cls << 5)
        ])
        sz1 -= sz_type + 8
        if res_none:
            sz = 0
        else:
            sz = 8
        assert sz1 == sz, "sz1 = %r" % sz1
    else:
        sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
        assert sz == sz_type, "Expected typ = %r, expr.a.t_anot = %r, expr.a = %r, got sz = %u" % (
            typ, expr.a.t_anot, expr.a, sz)
        sz_type1 = sz_type
        if expr.type_id in [BINARY_LSHIFT, BINARY_RSHIFT]:
            sz_type1 = 1
        sz = compile_expr(cmpl_obj, expr.b, context, cmpl_data, None, temp_links)
        if inc_by != 1 and inc_by_before:
            emit_load_i_const(cmpl_obj.memory, inc_by, is_sign, sz_cls)
            cmpl_obj.memory.extend([BC_MUL1 + 2 * sz_cls + int(is_sign)])
        assert sz == sz_type1, "sz = %u, sz_type1 = %u" % (sz, sz_type1)
        sz = sz_type
        op_code_u, op_code_s, op_code_f = {
            BINARY_MOD: (BC_MOD1, BC_MOD1S, BC_FMOD_2),
            BINARY_DIV: (BC_DIV1, BC_DIV1S, BC_FDIV_2),
            BINARY_MUL: (BC_MUL1, BC_MUL1S, BC_FMUL_2),
            BINARY_MINUS: (BC_SUB1, BC_SUB1, BC_FSUB_2),
            BINARY_PLUS: (BC_ADD1, BC_ADD1, BC_FADD_2),
            BINARY_AND: (BC_AND1, BC_AND1, BC_NOP),
            BINARY_OR: (BC_OR1, BC_OR1, BC_NOP),
            BINARY_XOR: (BC_XOR1, BC_XOR1, BC_NOP),
            BINARY_LT: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
            BINARY_GT: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
            BINARY_LE: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
            BINARY_GE: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
            BINARY_NE: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
            BINARY_EQ: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
            BINARY_RSHIFT: (BC_RSHIFT1, BC_RSHIFT1, BC_NOP),
            BINARY_LSHIFT: (BC_LSHIFT1, BC_LSHIFT1, BC_NOP),
        }[expr.type_id]
        op_code = BC_NOP
        if is_flt:
            if op_code_f != BC_NOP:
                op_code = op_code_f - 1 + sz_cls
        else:
            op_code = op_code_s if is_sign else op_code_u
            if op_code != BC_NOP:
                op_code += sz_cls if op_code_s == op_code_u else (2 * sz_cls)
        if op_code == BC_NOP:
            raise ValueError("Unsupported operator %s" % LST_BIN_OP_ID_MAP[expr.type_id])
        cmpl_obj.memory.append(op_code)
        if BINARY_LT <= expr.type_id <= BINARY_EQ:
            cmp_op_code = {
                BINARY_LT: BC_LT0,
                BINARY_GT: BC_GT0,
                BINARY_LE: BC_LE0,
                BINARY_GE: BC_GE0,
                BINARY_NE: BC_NE0,
                BINARY_EQ: BC_EQ0
            }[expr.type_id]
            cmpl_obj.memory.append(cmp_op_code)
            sz = 1
        elif inc_by != 1 and not inc_by_before:
            emit_load_i_const(cmpl_obj.memory, inc_by, is_sign, sz_cls)
            cmpl_obj.memory.extend([BC_DIV1 + 2 * sz_cls + int(is_sign)])
    return sz, res_type


class Counter(object):

    def __init__(self):
        self.count = 0

    def __call__(self):
        count = self.count
        self.count = count + 1
        return count


my_counter = Counter()


@try_catch_wrapper_co_expr
def compile_expr(cmpl_obj, expr, context, cmpl_data=None, type_coerce=None, temp_links=None):
    """
    :param BaseCmplObj cmpl_obj:
    :param BaseExpr expr:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    :param BaseType|None type_coerce:
    :param list[(BaseType,BaseLink)]|None temp_links:
    """
    if type_coerce is void_t:
        if expr.expr_id in {EXPR_LITERAL, EXPR_NAME}:
            return 0
    owns_temps = temp_links is None
    if owns_temps:
        temp_links = setup_temp_links(cmpl_obj, expr, context, cmpl_data)
    sz = 0 if expr.t_anot is None else size_of(expr.t_anot)
    res_type = expr.t_anot
    # count = my_counter()
    # print("compile_expr: %u\n expr = \n  " % count + format_pretty(expr).replace("\n", "\n  "))
    # print("\n res_type = \n  " + format_pretty(res_type).replace("\n", "\n  "))
    assert isinstance(res_type, BaseType)
    if expr.expr_id == EXPR_LITERAL:
        assert isinstance(expr, LiteralExpr)
        assert expr.t_anot is not None
        sz = size_of(expr.t_anot)
        if expr.t_lit in [LiteralExpr.LIT_CHR, LiteralExpr.LIT_FLOAT, LiteralExpr.LIT_INT]:
            sz_cls = sz.bit_length() - 1
            assert 0 <= sz_cls <= 3, "Invalid Size Class"
            sz1 = 1 << sz_cls
            if sz1 != sz:
                print("WARNING: Literal %r does not conform to a specific SizeClass sz=%u" % (expr, sz))
            prim_type = get_base_prim_type(expr.t_anot)
            assert isinstance(prim_type, PrimitiveType)
            cmpl_obj.memory.extend([
                BC_LOAD, BCR_ABS_C | (sz_cls << 5)])
            if expr.t_lit == LiteralExpr.LIT_FLOAT:
                if sz_cls == 2:
                    cmpl_obj.memory.extend(float_t.pack(expr.l_val))
                elif sz_cls == 3:
                    cmpl_obj.memory.extend(double_t.pack(expr.l_val))
                else:
                    raise TypeError("Only 4 and 8 byte floats are supported")
            else:
                cmpl_obj.memory.extend(sz_cls_align_long(expr.l_val, prim_type.sign, sz_cls))
            sz = sz1
        elif expr.t_lit == LiteralExpr.LIT_STR:
            prim_type, val_type, is_ref = get_tgt_ref_type(res_type)
            assert isinstance(prim_type, QualType)
            assert isinstance(val_type, QualType)
            assert is_ref
            assert val_type.qual_id == QualType.QUAL_ARR
            prim_type_coerce = prim_type if type_coerce is None else get_base_prim_type(type_coerce)
            elem_type = val_type.tgt_type
            sz_elem = size_of(elem_type)
            v_lit_bytes = bytearray(size_of(val_type))
            for c in range(len(expr.l_val)):
                v_lit_bytes[c * sz_elem:(c + 1) * sz_elem] = expr.l_val[c].to_bytes(sz_elem, "little")
            link = cmpl_obj.get_string_link(bytes(v_lit_bytes))
            if prim_type_coerce is not None and isinstance(prim_type_coerce, QualType):
                if prim_type_coerce.qual_id == QualType.QUAL_ARR:
                    sz = len(v_lit_bytes)
                    link.emit_load(cmpl_obj.memory, sz, cmpl_obj, byte_copy_cmpl_intrinsic)
                    res_type = val_type
                    '''Link1 = cmpl_obj.GetLink("@@ByteCopyFn1")
                    Byts1 = SzClsAlignLong(len(v_lit_bytes), False, 3)
                    # Begin add Stack
                    cmpl_obj.memory.extend([
                        BC_LOAD, BCR_ABS_C | BCR_SZ_8])
                    cmpl_obj.memory.extend(Byts1)
                    cmpl_obj.memory.extend([BC_ADD_SP8])
                    # end add Stack
                    # push [src]
                    link.EmitLEA(cmpl_obj.memory)
                    # Begin push [Size]
                    cmpl_obj.memory.extend([
                        BC_LOAD, BCR_ABS_C | BCR_SZ_8])
                    cmpl_obj.memory.extend(Byts1)
                    # end push [Size]
                    Link1.EmitLEA(cmpl_obj.memory)
                    cmpl_obj.memory.extend([BC_CALL])
                    sz = len(v_lit_bytes)'''
                elif prim_type_coerce.qual_id == QualType.QUAL_PTR:
                    assert compare_no_cvr(prim_type_coerce.tgt_type, elem_type)
                    link.emit_lea(cmpl_obj.memory)
                    sz = 8
                    res_type = QualType(QualType.QUAL_PTR, elem_type)
                elif prim_type_coerce.qual_id == QualType.QUAL_REF:
                    assert compare_no_cvr(prim_type_coerce.tgt_type, val_type)
                    link.emit_lea(cmpl_obj.memory)
                    sz = 8
                    res_type = prim_type
                else:
                    raise TypeError("Unsupported type_coerce = %s" % get_user_str_from_type(type_coerce))
            else:
                raise TypeError("Unknown annotated type: %r" % expr.t_anot)
    elif expr.expr_id == EXPR_PARENTH:
        assert isinstance(expr, ParenthExpr)
        if len(expr.lst_expr) != 1:
            raise NotImplementedError("ParenthExpr compilation is not supported when len(lst_expr) != 1")
        if type_coerce is not None:
            res_type = type_coerce
        sz = compile_expr(cmpl_obj, expr.lst_expr[0], context, cmpl_data, type_coerce, temp_links)
    elif expr.expr_id == EXPR_FN_CALL:
        assert isinstance(expr, FnCallExpr)
        if expr.fn.expr_id != EXPR_NAME:
            raise SyntaxError("Only Named functions can be called")
        assert isinstance(expr.fn, NameRefExpr)
        variadic = False
        sz0 = 0
        lst_arg_types = []
        fn_type = None if expr.fn.t_anot is None else get_value_type(expr.fn.t_anot)
        if fn_type is None:
            print("Cannot call an expression that is not type-annotated")
            # raise TypeError("Cannot call an expression that is not type-annotated")
        elif fn_type.type_class_id != TYP_CLS_QUAL:
            print("Cannot call a non-function expression")
            # raise TypeError("Cannot call a non-function expression")
        else:
            assert isinstance(fn_type, QualType)
            if fn_type.qual_id != QualType.QUAL_FN:
                print("Cannot call a non-function expression")
                # raise TypeError("Cannot call a non-function expression")
            else:
                lst_arg_types = list(fn_type.ext_inf)
                for c in range(len(lst_arg_types)):
                    cur = lst_arg_types[c]
                    if cur is not None and isinstance(cur, IdentifiedQualType):
                        cur = cur.typ
                        lst_arg_types[c] = cur
        res_type = fn_type.tgt_type
        sz_ret = size_of(res_type)
        sz_cls_ret = emit_load_i_const(cmpl_obj.memory, sz_ret, False)
        cmpl_obj.memory.extend([
            BC_ADD_SP1 + sz_cls_ret])
        lnk_ret = LocalRef.from_bp_off_pre_inc(cmpl_data.bp_off, sz_ret)
        cmpl_data.bp_off += sz_ret
        c = len(expr.lst_args)
        while c > 0:
            c -= 1
            arg = expr.lst_args[c]
            coerce_t = None
            if c < len(lst_arg_types):
                coerce_t = fn_type.ext_inf[c]
                if isinstance(coerce_t, IdentifiedQualType):
                    coerce_t = coerce_t.typ
            assert coerce_t is None or isinstance(coerce_t, BaseType)
            sz = compile_expr(cmpl_obj, arg, context, cmpl_data, coerce_t, temp_links)
            cmpl_data.bp_off += sz
            sz0 += sz
        if variadic:
            lnk_ret.emit_lea(cmpl_obj.memory)
            cmpl_data.bp_off += 8
            sz0 += 8
        sz_addr = compile_expr(cmpl_obj, expr.fn, context, cmpl_data, None, temp_links)
        assert sz_addr == 8
        cmpl_obj.memory.extend([
            BC_CALL])
        sz_cls = emit_load_i_const(cmpl_obj.memory, sz0, False)
        cmpl_obj.memory.extend([
            BC_RST_SP1 + sz_cls])
        cmpl_data.bp_off -= sz0
        cmpl_data.bp_off -= sz_ret
        sz = sz_ret
    elif expr.expr_id == EXPR_PTR_MEMBER:
        assert isinstance(expr, SpecialPtrMemberExpr)
        prim_type = get_base_prim_type(expr.obj.t_anot)
        assert prim_type.type_class_id == TYP_CLS_QUAL, "Must be pointer"
        assert isinstance(prim_type, QualType)
        assert prim_type.qual_id == QualType.QUAL_PTR, "Must be pointer"
        val_type = get_base_prim_type(prim_type.tgt_type)
        if val_type.type_class_id == TYP_CLS_UNION:
            assert isinstance(val_type, UnionType)
            return compile_expr(cmpl_obj, expr.obj, context, cmpl_data, prim_type, temp_links)
        raise NotImplementedError("Not Implemented")
    elif expr.expr_id == EXPR_DOT:
        assert isinstance(expr, SpecialDotExpr)
        prim_type, val_type, is_ref = get_tgt_ref_type(expr.obj.t_anot)
        if not is_ref:
            raise TypeError("Cannot use dot operator on non-reference type")
        if val_type.type_class_id == TYP_CLS_UNION:
            assert isinstance(val_type, UnionType)
            return compile_expr(cmpl_obj, expr.obj, context, cmpl_data, prim_type, temp_links)
        elif val_type.type_class_id == TYP_CLS_STRUCT:
            assert isinstance(val_type, StructType)
            compile_expr(cmpl_obj, expr.obj, context, cmpl_data, prim_type, temp_links)
            emit_load_i_const(cmpl_obj.memory, val_type.offset_of(expr.attr), False, 3)
            cmpl_obj.memory.extend([BC_ADD8])
            return 8
        elif val_type.type_class_id == TYP_CLS_CLASS:
            assert isinstance(val_type, ClassType)
            compile_expr(cmpl_obj, expr.obj, context, cmpl_data, prim_type, temp_links)
            emit_load_i_const(cmpl_obj.memory, val_type.offset_of(expr.attr), False, 3)
            cmpl_obj.memory.extend([BC_ADD8])
            return 8
        # TODO: add 2 opcodes or use a memory reference (BCR_R_BP)
        #   one for this ---keep----[data you don't want][data you want] -> -keep--[data you want]
        #   one for getting the current stack pointer
    elif expr.expr_id == EXPR_NAME:
        # TODO: right now name resolution is done at CodeGen time
        # TODO:   maybe this needs to be changed so that name resolution
        # TODO:   is done at Parse Time
        assert isinstance(expr, NameRefExpr)
        ctx_var = expr.ctx_var
        assert isinstance(ctx_var, ContextVariable)
        lnk_name = ctx_var.get_link_name()
        lnk = cmpl_data.get_local(lnk_name) if ctx_var.parent.is_local_scope() else cmpl_obj.get_link(lnk_name)
        assert isinstance(lnk, BaseLink)
        if type_coerce is None:
            if res_type is None:
                raise TypeError("Cannot process NameRefExpr without t_anot")
            assert isinstance(res_type, QualType)
            assert res_type.qual_id == QualType.QUAL_REF
            lnk.emit_lea(cmpl_obj.memory)
            sz = 8
        else:
            prim_type_coerce = get_base_prim_type(type_coerce)
            val_type = get_base_prim_type(ctx_var.typ)
            do_as_ref = False
            # do_as_val = False
            if prim_type_coerce.type_class_id == TYP_CLS_QUAL:
                assert isinstance(prim_type_coerce, QualType)
                do_as_ref = prim_type_coerce.qual_id == QualType.QUAL_REF
            if do_as_ref:
                lnk.emit_lea(cmpl_obj.memory)
                sz = 8
            else:
                res_type = val_type
                if compare_no_cvr(prim_type_coerce, val_type):
                    sz = size_of(val_type)
                    # TODO: change this so that the BaseType subclasses are responsible for construction
                    # TODO:   from a pointer already on the stack
                    lnk.emit_load(cmpl_obj.memory, sz, cmpl_obj, byte_copy_cmpl_intrinsic)
                else:
                    raise TypeError(
                        "Expected type_coerce to be reference or value type: type_coerce = %r, val_type = %r" % (
                            type_coerce, val_type
                        )
                    )
    elif expr.expr_id == EXPR_CAST:
        assert isinstance(expr, CastOpExpr)
        assert expr.t_anot is not None
        if expr.cast_type == CastOpExpr.CAST_EXPLICIT:
            print("WARN: Explicit casts are treated the same way as implicit casts")
        sz = compile_conv_general(cmpl_obj, expr, context, cmpl_data, temp_links)
    elif expr.expr_id == EXPR_BIN_OP:
        assert isinstance(expr, BinaryOpExpr)
        sz, res_type = compile_bin_op_expr(cmpl_obj, expr, context, cmpl_data, type_coerce, temp_links, res_type)
    elif expr.expr_id == EXPR_SPARENTH:
        assert isinstance(expr, SParenthExpr)
        assert expr.t_anot is not None
        sz = compile_expr(cmpl_obj, expr.left_expr, context, cmpl_data, None, temp_links)
        assert sz == 8
        sz_elem = size_of(get_value_type(expr.t_anot))
        sz = compile_expr(cmpl_obj, expr.inner_expr, context, cmpl_data, None, temp_links)
        assert sz == 8, "expr = %r, expr.t_anot = %r" % (expr, expr.t_anot)  # sizeof(SizeL)
        if sz_elem != 1:
            emit_load_i_const(cmpl_obj.memory, sz_elem, False, 3)
            cmpl_obj.memory.extend([
                BC_MUL8, BC_ADD8
            ])
        else:
            cmpl_obj.memory.append(BC_ADD8)
    elif expr.expr_id == EXPR_UNI_OP:
        assert isinstance(expr, UnaryOpExpr)
        assert expr.t_anot is not None
        if expr.type_id in [UNARY_REFERENCE, UNARY_STAR]:
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
            assert sz == 8
        elif expr.type_id == UNARY_BOOL_NOT:
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, bool_t, temp_links)
            assert sz == 1
            cmpl_obj.memory.append(BC_EQ0)
            res_type = bool_t
        elif expr.type_id == UNARY_BIT_NOT:
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
            sz_cls = sz.bit_length() - 1
            assert 1 << sz_cls == sz and 0 <= sz_cls <= 3
            cmpl_obj.memory.append(BC_NOT1 + sz_cls)
        elif expr.type_id == UNARY_MINUS:
            typ_bits = get_bc_conv_bits(expr.a.t_anot)
            sz_cls = (typ_bits & 0x7) >> (0 if typ_bits & 0x8 else 1)
            sub_code = (BC_FSUB_2 if typ_bits & 0x8 else BC_SUB1) + sz_cls
            assert BC_FSUB_2 <= sub_code <= BC_FSUB_16 or BC_SUB1 <= sub_code <= BC_SUB8
            emit_load_i_const(cmpl_obj.memory, 0, False, 0)
            cmpl_obj.memory.extend([
                BC_CONV, typ_bits << 4,  # input bits are 0 for unsigned byte
            ])
            res_type = expr.a.t_anot
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
            cmpl_obj.memory.append(sub_code)
        elif expr.type_id == UNARY_PLUS:
            res_type = expr.a.t_anot
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
        elif expr.type_id in [UNARY_PRE_DEC, UNARY_PRE_INC, UNARY_POST_DEC, UNARY_POST_INC]:
            inc_by = 0
            sz_num = 8
            if expr.op_fn_type == OP_TYP_NATIVE:
                inc_by = 1
                sz_num = size_of(prim_types[expr.op_fn_data])
            elif expr.op_fn_type == OP_TYP_PTR_GENERIC:
                inc_by = expr.op_fn_data
                sz_num = 8
            if inc_by == 0:
                raise NotImplementedError(
                    "Expression (id = UNARY_OP_EXPR, type_id = %u) compilation of OP_TYP_FUNCTION or void *" %
                    expr.type_id
                )
            sz_cls = sz_num.bit_length() - 1
            assert 1 << sz_cls == sz_num
            a_type = expr.a.t_anot
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
            assert sz == 8 and a_type.type_class_id == TYP_CLS_QUAL
            assert isinstance(a_type, QualType)
            assert a_type.qual_id == QualType.QUAL_REF
            swap_byte = (sz_cls << 3) | BCS_SZ8_A
            load_byte = BCR_ABS_S8 | (sz_cls << 5)
            is_add = expr.type_id in [UNARY_PRE_INC, UNARY_POST_INC]
            if expr.type_id in [UNARY_PRE_DEC, UNARY_PRE_INC]:
                if type_coerce is void_t:
                    res_type = void_t
                    sz = 0
                else:
                    cmpl_obj.memory.extend([
                        BC_LOAD, BCR_TOS | BCR_SZ_8,  # reference that is returned
                    ])
                cmpl_obj.memory.extend([
                    BC_LOAD, BCR_TOS | BCR_SZ_8,
                    BC_LOAD, load_byte,
                ])
            else:
                if type_coerce is void_t:
                    res_type = void_t
                    sz = 0
                    cmpl_obj.memory.extend([
                        BC_LOAD, BCR_TOS | BCR_SZ_8,
                        BC_LOAD, load_byte,
                    ])
                else:
                    res_type = get_value_type(a_type)
                    sz = size_of(res_type)
                    cmpl_obj.memory.extend([
                        BC_LOAD, BCR_TOS | BCR_SZ_8,
                        BC_LOAD, load_byte,
                        BC_SWAP, swap_byte,
                        BC_LOAD, BCR_TOS | BCR_SZ_8,
                        BC_LOAD, load_byte,
                    ])
            emit_load_i_const(cmpl_obj.memory, inc_by, False, sz_cls)
            cmpl_obj.memory.extend([
                (BC_ADD1 if is_add else BC_SUB1) + sz_cls,
                BC_SWAP, swap_byte,
                BC_STOR, load_byte
            ])

        else:
            raise NotImplementedError(
                "Expression (id = UNARY_OP_EXPR, type_id = %u) compilation is not supported" % expr.type_id
            )
    else:
        raise NotImplementedError("Expression (id = %u) compilation is not supported" % expr.expr_id)
    if owns_temps:
        tear_down_temp_links(cmpl_obj, temp_links, expr, context, cmpl_data)
    if type_coerce is void_t and not compare_no_cvr(res_type, type_coerce):
        sz_cls_rst = emit_load_i_const(cmpl_obj.memory, sz, False)
        cmpl_obj.memory.extend([
            BC_RST_SP1 + sz_cls_rst
        ])
        # res_type = Void_T
        sz = 0
    elif type_coerce is not None and not compare_no_cvr(res_type, type_coerce):
        parsing_vars["expr"] = expr
        parsing_vars["type_coerce"] = type_coerce
        parsing_vars["res_type"] = res_type
        # print("compile_expr(%u):\n  res_type = %s" % (count, format_pretty(res_type)))
        raise TypeError("The Expression result type is %s and cannot coerce to %s; expr = %r, sz = %d" % (
            get_user_str_from_type(res_type), get_user_str_from_type(type_coerce), expr, sz))
    return sz


'''
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
'''


def byte_copy_cmpl_intrinsic(cmpl_obj, memory, size, is_stack, is_load):
    """
    :param BaseCmplObj cmpl_obj:
    :param bytearray memory:
    :param int|None size:
    :param bool is_stack:
    :param bool is_load:
    """
    if is_load:
        lnk = cmpl_obj.get_link("@@ByteCopyFn1" if is_stack else "@@ByteCopyFn")
        memory.extend([
            BC_LOAD, BCR_ABS_C | BCR_SZ_8])
        memory.extend(sz_cls_align_long(size, False, 3))
        lnk.emit_lea(memory)
        memory.extend([BC_CALL])
    else:
        lnk = cmpl_obj.get_link("@@ByteCopyFn2" if is_stack else "@@ByteCopyFn")
        memory.extend([
            BC_LOAD, BCR_ABS_C | BCR_SZ_8])
        memory.extend(sz_cls_align_long(size, False, 3))
        lnk.emit_lea(memory)
        memory.extend([BC_CALL])
    return 16 if is_stack else 24


class LocalCompileData(object):
    """
    :type bp_off: int
    :type vars: list[(ContextVariable, LocalRef)]
    :type local_links: dict[str,int]
    :type parent: LocalCompileData|None
    :type local_labels: dict[str,Linkage]
    :type cur_breakable: (Linkage, Linkage)|None
    :type res_data: (BaseType, BaseLink)|None
    """
    def __init__(self, parent=None):
        """
        :param LocalCompileData|None parent:
        """
        self.bp_off = 0 if parent is None else parent.bp_off
        self.vars = []
        self.local_links = {}
        self.sizes = {}
        self.parent = parent
        self.local_labels = {} if parent is None else parent.local_labels
        self.cur_breakable = None if parent is None else parent.cur_breakable
        self.res_data = None

    def compile_leave_scope(self, cmpl_obj, context):
        """
        :param BaseCmplObj cmpl_obj:
        :param CompileContext context:
        """
        rel_bp_off = self.get_rel_bp_off()
        if not rel_bp_off:
            return
        stack_sz = 0
        c = len(self.vars)  # TODO: Convert to putLocal and __getitem__ for LocalLink access
        while c > 0:
            c -= 1
            assert isinstance(c, int)
            ctx_var, lnk = self.vars[c]
            sz_var = size_of(ctx_var.typ)
            # TODO: change steps involved
            # step 1:
            #   do deinitialization (non-trivial destructors including member variables)
            #     NOTE: this may require new instruction for load (REG_SP to get current stack pointer)
            # step 2:
            #   do deallocation (if necessary)
            res = ctx_var.typ.compile_var_de_init(cmpl_obj, context, VarRefTosNamed(ctx_var), self)
            assert res == -1, "cannot do complex de-initialization"
            stack_sz += sz_var
        if stack_sz != 0:
            sz_cls = emit_load_i_const(cmpl_obj.memory, stack_sz, False)
            cmpl_obj.memory.extend([
                BC_RST_SP1 + sz_cls
            ])

    def get_rel_bp_off(self):
        parent = self.parent
        return self.bp_off + (0 if parent is None else parent.bp_off)

    def get_label(self, k):
        """
        :param str k:
        :rtype: Linkage
        """
        link = self.local_labels.get(k, None)
        if link is None:
            link = self.local_labels[k] = Linkage()
        return link

    def get_local(self, k):
        """
        :param str k:
        :rtype: LocalRef
        """
        return self[k][1]

    def put_local(self, ctx_var, link_name=None, sz_var=None, bp_off=None, bp_off_pre_inc=False):
        """
        :param ContextVariable ctx_var:
        :param str link_name:
        :param int|None sz_var:
        :param int|None bp_off:
        :param bool bp_off_pre_inc:
        :rtype: LocalRef
        """
        if link_name is None:
            link_name = ctx_var.get_link_name()
        if sz_var is None:
            sz_var = size_of(ctx_var.typ)
        if bp_off is None:
            bp_off = self.bp_off
        add_bp = bp_off == self.bp_off
        lnk = (
            LocalRef.from_bp_off_pre_inc(bp_off, sz_var)
            if bp_off_pre_inc else
            LocalRef.from_bp_off_post_inc(bp_off, sz_var))
        # print "PUT_LOCAL: link_name=%r, initial-bp_off=%r, lnk.RelAddr=%r" % (link_name, self.bp_off, lnk.RelAddr)
        self.setitem(link_name, (ctx_var, lnk))
        if add_bp:
            self.bp_off += sz_var
        # print "PUT_LOCAL: final-bp_off=%r" % self.bp_off
        return lnk

    def __getitem__(self, k):
        """
        :param str k:
        :rtype: (ContextVariable, LocalRef)
        """
        try:
            return self.vars[self.local_links[k]]
        except KeyError:
            if self.parent is None:
                raise
            return self.parent[k]

    def setitem(self, k, v):
        """
        :param str k:
        :param (ContextVariable, LocalRef) v:
        """
        var_index = self.local_links.get(k, None)
        if var_index is not None:
            raise KeyError("Variable '%s' already exists" % k)
        self.local_links[k] = len(self.vars)
        self.vars.append(v)

    def strict_get(self, k, default=None):
        """
        :param str k:
        :param T default:
        :rtype: LocalRef|T
        """
        var_index = self.local_links.get(k, None)
        if var_index is None:
            return default
        return self.vars[var_index][1]

    def get(self, k, default=None):
        """
        :param str k:
        :param T default:
        :rtype: LocalRef|T
        """
        lnk = self.strict_get(k, None)
        if lnk is None:
            if self.parent is None:
                return default
            return self.parent.get(k, default)
        return lnk


def compile_stmnt1(cmpl_obj, stmnt, context, cmpl_data=None):
    """
    :param BaseCmplObj cmpl_obj:
    :param BaseStmnt stmnt:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    """
    del cmpl_obj, context, cmpl_data
    try:
        a = 1/0
        del a
        # return CompileStmntNoLineColMsg(cmpl_obj, stmnt, context, cmpl_data)
    except Exception as Exc:
        print(traceback.format_exc())
        raise Exc.__class__(*(tuple(Exc.args) + ("In Statement at line:col = %u:%u" % stmnt.position,)))


CURRENT_CMPL_CONDITIONS = {
    "arch": "StackVM-64"
}


def get_vars_from_compile_data(cmpl_data):
    """
    :param LocalCompileData cmpl_data:
    :rtype: list[(ContextVariable, LocalRef)]
    """
    if cmpl_data.parent is None:
        return cmpl_data.vars
    else:
        return get_vars_from_compile_data(cmpl_data.parent) + cmpl_data.vars


# NoLineColMsg
def compile_stmnt(cmpl_obj, stmnt, context, cmpl_data=None):
    """
    :param BaseCmplObj cmpl_obj:
    :param BaseStmnt stmnt:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    """
    if stmnt.stmnt_type == STMNT_ASM:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, AsmStmnt)
        if stmnt.condition is None or stmnt.condition.get("arch", CURRENT_CMPL_CONDITIONS["arch"]) == CURRENT_CMPL_CONDITIONS["arch"]:
            rel_bp_names = {}
            for ctx_var, local_ref in get_vars_from_compile_data(cmpl_data):
                rel_bp_names[ctx_var.get_link_name()] = (local_ref.rel_addr, local_ref.sz)
            if stmnt.condition is not None and stmnt.condition.get("display_links", False):
                print("Links for assembly named '%s' are as follows: %s" % (stmnt.condition.get("name", "<UNNAMED>"), format_pretty(rel_bp_names)))
            assemble(cmpl_obj, rel_bp_names, "\n".join(stmnt.inner_asm))
    elif stmnt.stmnt_type == STMNT_CURLY_STMNT:
        assert isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, CurlyStmnt)
        return compile_curly(cmpl_obj, stmnt, context, cmpl_data)
    elif stmnt.stmnt_type == STMNT_DECL:
        assert isinstance(stmnt, DeclStmnt)
        assert stmnt.decl_lst is not None
        sz_off = 0
        for cur_decl in stmnt.decl_lst:
            assert isinstance(cur_decl, SingleVarDecl)
            ctx_var = context.scoped_get_strict(cur_decl.var_name)
            sz_off += cur_decl.type_name.compile_var_init(
                cmpl_obj, cur_decl.init_args, context, VarRefTosNamed(ctx_var), cmpl_data)
        return sz_off
    elif stmnt.stmnt_type == STMNT_IF:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, IfElse)
        assert stmnt.stmnt is not None
        assert stmnt.cond.t_anot is not None, "type annotation required: " + repr(stmnt.cond)
        # assert stmnt.cond.t_anot is bool
        sz = compile_expr(
            cmpl_obj, stmnt.cond, context, cmpl_data, get_value_type(stmnt.cond.t_anot))
        assert sz == 1, "Error:\n  cond = %r\n  cond.t_anot = %r" % (stmnt.cond, stmnt.cond.t_anot)
        # assert sz == sizeof(bool)
        cmpl_obj.memory.extend([
            BC_EQ0,
            BC_LOAD, BCR_EA_R_IP | BCR_SZ_8, 0, 0, 0, 0, 0, 0, 0, 0,
            BC_JMPIF
        ])
        lnk_ref = LinkRef(len(cmpl_obj.memory) - 9, 0)
        compile_stmnt(cmpl_obj, stmnt.stmnt, context, cmpl_data)
        if stmnt.else_stmnt is not None:
            # jump past the else-statement
            cmpl_obj.memory.extend([
                BC_LOAD, BCR_EA_R_IP | BCR_SZ_8, 0, 0, 0, 0, 0, 0, 0, 0,
                BC_JMP,
            ])
            lnk_ref.fill_ref(cmpl_obj.memory, len(cmpl_obj.memory))
            lnk_ref = LinkRef(len(cmpl_obj.memory) - 9, 0)
            compile_stmnt(cmpl_obj, stmnt.else_stmnt, context, cmpl_data)
        lnk_ref.fill_ref(cmpl_obj.memory, len(cmpl_obj.memory))
    elif stmnt.stmnt_type == STMNT_FOR:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, ForLoop)
        assert stmnt.init is not None
        assert stmnt.cond is not None
        assert stmnt.stmnt is not None
        cmpl_data1 = LocalCompileData(cmpl_data)
        lnk_begin_loop = Linkage()
        lnk_end_loop = Linkage()
        cmpl_data1.cur_breakable = (lnk_begin_loop, lnk_end_loop)
        sz0 = compile_stmnt(cmpl_obj, stmnt.init, stmnt.context, cmpl_data1)
        lnk_begin_loop.src = len(cmpl_obj.memory)
        lnk_end_body = Linkage()
        sz = compile_expr(cmpl_obj, stmnt.cond, stmnt.context, cmpl_data1)
        assert sz == 1
        cmpl_obj.memory.extend([BC_EQ0])
        lnk_end_loop.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMPIF])
        compile_stmnt(cmpl_obj, stmnt.stmnt, stmnt.context, cmpl_data1)
        lnk_end_body.src = len(cmpl_obj.memory)
        if stmnt.incr is not None:
            sz = compile_expr(cmpl_obj, stmnt.incr, stmnt.context, cmpl_data1, void_t)
            assert sz == 0
        lnk_begin_loop.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([
            BC_JMP])
        lnk_end_loop.src = len(cmpl_obj.memory)
        sz_cls = emit_load_i_const(cmpl_obj.memory, sz0, False)
        cmpl_obj.memory.extend([
            BC_RST_SP1 + sz_cls])
        lnk_begin_loop.fill_all(cmpl_obj.memory)
        lnk_end_body.fill_all(cmpl_obj.memory)
        lnk_end_loop.fill_all(cmpl_obj.memory)
    elif stmnt.stmnt_type == STMNT_WHILE:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, WhileLoop)
        # assert stmnt.cond.t_anot is bool
        cmpl_data1 = LocalCompileData(cmpl_data)
        lnk_begin_loop = Linkage()
        lnk_end_loop = Linkage()
        cmpl_data1.cur_breakable = (lnk_begin_loop, lnk_end_loop)
        lnk_begin_loop.src = len(cmpl_obj.memory)
        sz = compile_expr(
            cmpl_obj, stmnt.cond, context, cmpl_data)
        assert sz == 1  # assert sz == sizeof(bool)
        cmpl_obj.memory.extend([BC_EQ0])
        lnk_end_loop.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMPIF])
        compile_stmnt(cmpl_obj, stmnt.stmnt, context, cmpl_data1)
        lnk_begin_loop.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMP])
        lnk_end_loop.src = len(cmpl_obj.memory)
        lnk_begin_loop.fill_all(cmpl_obj.memory)
        lnk_end_loop.fill_all(cmpl_obj.memory)
    elif stmnt.stmnt_type == STMNT_CONTINUE:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert cmpl_data.cur_breakable is not None
        cmpl_data.cur_breakable[0].emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMP])
    elif stmnt.stmnt_type == STMNT_BRK:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert cmpl_data.cur_breakable is not None
        cmpl_data.cur_breakable[1].emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMP])
    elif stmnt.stmnt_type == STMNT_RTN:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, ReturnStmnt)
        cmpl_data1 = cmpl_data
        # Leave all the scopes except for the scope that has no parent (ie the function argument scope)
        scopes_to_leave = []
        while cmpl_data1.parent is not None:
            scopes_to_leave.append(cmpl_data1)
            cmpl_data1 = cmpl_data1.parent
        assert cmpl_data1.res_data is not None
        res_type, res_link = cmpl_data1.res_data
        sz_res = size_of(res_type)  # TODO: right now return values are treated like variable values
        sz_res1 = res_type.compile_var_init(cmpl_obj, [stmnt.expr], context, VarRefLnkPrealloc(res_link), cmpl_data)
        assert sz_res1 == sz_res, "Size returned from CompileVarInit is inconsistent with SizeOf(res_type)"
        for Scope in scopes_to_leave:
            assert isinstance(Scope, LocalCompileData)
            Scope.compile_leave_scope(cmpl_obj, context)
        # TODO: change function calling convention
        # TODO:   convention: caller pushes args just like it does now
        # TODO:   except there is an additional argument that represents the return value
        # already sortof done
        cmpl_obj.memory.extend([BC_RET])
    elif stmnt.stmnt_type == STMNT_SEMI_COLON:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, SemiColonStmnt)
        if stmnt.expr is not None:
            sz = compile_expr(cmpl_obj, stmnt.expr, context, cmpl_data, void_t)
            assert sz == 0
    elif stmnt.stmnt_type == STMNT_NAMESPACE:
        assert isinstance(stmnt, NamespaceStmnt)
        for inner_stmnt in stmnt.lst_stmnts:
            compile_stmnt(cmpl_obj, inner_stmnt, stmnt.ns, cmpl_data)
    elif stmnt.stmnt_type == STMNT_TYPEDEF:
        pass # Do nothing for typedef statement
    else:
        raise ValueError("Unrecognized Statement Type")
    return 0


def compile_curly(cmpl_obj, stmnt, context, cmpl_data=None):
    """
    :param CompileObject cmpl_obj:
    :param CurlyStmnt stmnt:
    :param CompileContext context:
    :param LocalCompileData|None cmpl_data:
    """
    del context
    # key format is "name@fullscopename"
    #   fullscopename format is cur.name.rsplit(" ", 1)[-1][:-1] + ("-" + cur.parent.fullscopename)
    #     if cur.parent is not cur.host_scopeable else ""
    assert stmnt.stmnts is not None
    if cmpl_data is None:
        print("WARN: Curly Statement usually requires cmpl_data")
    cmpl_data = LocalCompileData(cmpl_data)
    for cur_stmnt in stmnt.stmnts:
        compile_stmnt(cmpl_obj, cur_stmnt, stmnt.context, cmpl_data)
    cmpl_data.compile_leave_scope(cmpl_obj, stmnt.context)
    return 0


def flatify_dep_desc(dep_dct, start_k):
    """
    :param str start_k:
    :param dict[str, list[str]] dep_dct:
    :rtype: set[str]
    """
    rtn = set()
    set_next = {start_k}
    while len(set_next):
        set_get = set_next
        rtn |= set_get
        set_next = set()
        for k in set_get:
            if k not in dep_dct:
                raise KeyError("Unresolved External Symbol: " + k)
            set_next.update(dep_dct[k])
        set_next -= rtn
    return rtn


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
def compile_lang1(tokens, cmpl_opts):
    """
    :param list[ParseClass] tokens:
    :param CompilerOptions cmpl_opts:
    """
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
        cmpl_obj.memory.extend([
            BC_CALL, BC_HLT])
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
            '''OldDeps = ExternDeps
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
                if len(Missing): print "PRE-WARN: Missing symbols\n  " + "\n  ".join(sorted(Missing))'''
            excl = unused_deps
        cmpl_obj.merge_all(link_opts, extern_deps, excl)
        cmpl_obj.link_all()
    return lst_stmnt, global_ctx, cmpl_obj, dep_dct


mangle_maps = {}


def _do_the_init():
    global mangle_maps
    for Cls in [PrimitiveType, QualType, StructType, ClassType, UnionType, EnumType]:
        for k in Cls.mangle_captures:
            if k in mangle_maps:
                print("CONFLICT: %s and %s at k = %r" % (Cls.__name__, mangle_maps[k].__name__, k))
            mangle_maps[k] = Cls
    '''for k in sorted(MangleMaps):
        Cls = MangleMaps[k]
        print "ALLOC: %s to class %s" % (k, Cls.__name__)'''


_do_the_init()
