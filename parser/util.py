from typing import Callable, List, Optional, Tuple, Any, TYPE_CHECKING


def try_catch_wrapper0(
    fn: Callable[[List["Token"], int, int, "CompileContext"], Tuple[Any, int]]
) -> Callable[[List["Token"], int, int, "CompileContext"], Tuple[Any, int]]:
    def new_fn(tokens, c, end, context):
        try:
            return fn(tokens, c, end, context)
        except Exception as exc:
            del exc
            print(
                "%s: tokens = ..., c = %u, end = %u, context = ..."
                % (fn.__name__, c, end)
            )
            raise

    new_fn.__name__ = fn.__name__ + "__wrapped"
    return new_fn


def try_catch_wrapper1(
    fn: Callable[
        [List["Token"], int, Optional[str], int, "CompileContext"], Tuple[Any, int]
    ]
) -> Callable[
    [List["Token"], int, Optional[str], int, "CompileContext"], Tuple[Any, int]
]:
    def new_fn(tokens, c, delim, end, context):
        # noinspection PyBareException,PyPep8
        try:
            return fn(tokens, c, delim, end, context)
        except Exception as exc:
            del exc
            print(
                "%s: tokens = ..., c = %u, Delim = %r, end = %u, context = ..."
                % (fn.__name__, c, delim, end)
            )
            raise

    new_fn.__name__ = fn.__name__ + "__wrapped"
    return new_fn


def try_catch_wrapper_co_expr(fn):
    def new_fn(
        cmpl_obj: "BaseCmplObj",
        expr: "BaseExpr",
        context: "CompileContext",
        cmpl_data: Optional["LocalCompileData"] = None,
        type_coerce: Optional["BaseType"] = None,
        temp_links: Optional[List[Tuple["BaseType", "BaseLink"]]] = None,
    ):
        try:
            return fn(cmpl_obj, expr, context, cmpl_data, type_coerce, temp_links)
        except Exception as exc:
            del exc
            print(
                "%s: cmpl_obj = %r, expr = %r, context = %r, cmpl_data = %r, type_coerce = %r, temp_links = %r"
                % (
                    fn.__name__,
                    cmpl_obj,
                    expr,
                    context,
                    cmpl_data,
                    type_coerce,
                    temp_links,
                )
            )
            raise

    new_fn.__name__ = new_fn.__name__ = fn.__name__ + "__wrapped"
    return new_fn


if TYPE_CHECKING:
    from ..lexer.lexer import Token
    from .context.CompileContext import CompileContext
    from .expr.BaseExpr import BaseExpr
    from .type.BaseType import BaseType
    from ..code_gen.BaseCmplObj import BaseCmplObj
    from ..code_gen.LocalCompileData import LocalCompileData
    from ..code_gen.BaseLink import BaseLink
