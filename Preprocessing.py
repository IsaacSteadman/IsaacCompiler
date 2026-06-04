"""
IsaacCompiler C Preprocessor.

Text-level preprocessing that runs before the lexer/parser pipeline.
Supports a practical subset of the C preprocessor:

  Directives
  ----------
  #include "file"  / #include <file>
  #define NAME
  #define NAME replacement
  #define NAME(params) replacement
  #undef  NAME
  #ifdef  NAME / #ifndef NAME
  #if     0 | 1 | defined(X) | !defined(X) | expr&&expr | expr||expr | !expr
  #elif   <same expressions>
  #else
  #endif
  #error  message    (raises PreprocessorError)
  #warning message   (prints to stderr, continues)
  #pragma ...        (silently ignored)

  Other
  -----
  Line continuation (backslash-newline joins adjacent logical lines).
  Macro substitution skips string literals "..." and char literals '...'.
  Object-like macros are expanded recursively (but not re-entrantly).
  Function-like macros with balanced-parenthesis argument parsing.
  ## token-pasting (left-to-right, identifier/number tokens).
  # stringification (raw argument, per C11 §6.10.3.2).

Not implemented (future work):
  arithmetic #if expressions, #line.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Public exceptions / data types
# ---------------------------------------------------------------------------


class PreprocessorError(Exception):
    """Raised when the preprocessor encounters an unrecoverable error."""

    def __init__(self, message: str, file: str = "<unknown>", line: int = 0) -> None:
        loc = f"{file}:{line}" if line else file
        super().__init__(f"{loc}: preprocessor error: {message}")
        self.pp_file = file
        self.pp_line = line


class MacroDef:
    """Represents one #define directive."""

    __slots__ = ("name", "params", "replacement", "variadic")

    def __init__(
        self,
        name: str,
        params: Optional[List[str]],
        replacement: str,
        variadic: bool = False,
    ) -> None:
        self.name = name
        # params is None  → object-like macro   (#define A value)
        # params is list  → function-like macro  (#define F(x) expr)
        # When variadic is True, params ends with "__VA_ARGS__" and the macro
        # accepts a variable number of trailing arguments.
        self.params = params
        self.replacement = replacement
        self.variadic = variadic


# ---------------------------------------------------------------------------
# Pre-compiled regular expressions
# ---------------------------------------------------------------------------

# Match a preprocessor directive line: optional leading whitespace, then #, then name
_DIRECTIVE_RE = re.compile(r"^\s*#\s*(\w+)(.*)", re.DOTALL)

# Match a #define argument: NAME [(params)] rest
# group 1: macro name
# group 2: full (params) including parens — None when absent (object-like)
# group 3: params string inside the parens — None when absent
# group 4: rest of line (the replacement, to be stripped by caller)
_DEFINE_RE = re.compile(r"(\w+)(\(([^)]*)\))?(.*)", re.DOTALL)

# Match identifier/number tokens on both sides of a ## token-paste operator.
# Used by _process_token_paste to concatenate adjacent tokens left-to-right.
_TOKEN_PASTE_RE = re.compile(r"([A-Za-z0-9_]+)\s*##\s*([A-Za-z0-9_]+)")


# ---------------------------------------------------------------------------
# Preprocessor
# ---------------------------------------------------------------------------


class Preprocessor:
    """
    Stateful C preprocessor.

    Create one instance per translation unit (or share one across an
    #include chain — the same ``Preprocessor`` object handles recursive
    includes, maintaining a single ``defines`` dict and ``_included_files``
    set for the entire unit).
    """

    # GNU keyword aliases → canonical keyword replacements (object-like macros).
    _GNU_ALIASES: Dict[str, str] = {
        "__asm__": "asm",
        "__volatile__": "volatile",
        "__inline__": "inline",
        "__inline": "inline",
        "__const__": "const",
        "__signed__": "signed",
        "__typeof__": "typeof",
        "__restrict__": "restrict",
        "__restrict": "restrict",
    }

    def __init__(
        self,
        include_dirs: List[str],
        defines: Optional[Dict[str, MacroDef]] = None,
    ) -> None:
        self.include_dirs: List[str] = list(include_dirs)
        self.defines: Dict[str, MacroDef] = dict(defines) if defines else {}
        # Conditional-inclusion stack.
        # Each entry is (active: bool, can_switch: bool) where:
        #   active      – this level is currently producing output.
        #   can_switch  – the parent level was active AND no True branch has
        #                 been taken yet (so #elif / #else may activate).
        self._if_stack: List[Tuple[bool, bool]] = []
        # Absolute paths of files currently being preprocessed (cycle detection).
        self._included_files: Set[str] = set()
        # True when the scan position is inside a /* ... */ block comment
        # that has not yet been closed (spans multiple source lines).
        self._in_block_comment: bool = False
        # __COUNTER__: incremented each time the macro is expanded.
        self._counter: int = 0
        # Absolute paths of files that have seen #pragma once.
        self._pragma_once_files: Set[str] = set()
        # Predefined C standard macros (freestanding C11 environment).
        _builtin: Dict[str, str] = {
            "__STDC__": "1",
            "__STDC_VERSION__": "201112L",
            "__STDC_HOSTED__": "0",
        }
        for name, repl in _builtin.items():
            if name not in self.defines:
                self.defines[name] = MacroDef(name, None, repl)
        # C11 static_assert convenience alias (from <assert.h>).
        if "static_assert" not in self.defines:
            self.defines["static_assert"] = MacroDef(
                "static_assert", None, "_Static_assert"
            )
        # GNU keyword aliases (only inject if not overridden by caller).
        for alias, canonical in self._GNU_ALIASES.items():
            if alias not in self.defines:
                self.defines[alias] = MacroDef(alias, None, canonical)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def including(self) -> bool:
        """True when every enclosing conditional level is active."""
        return all(active for active, _ in self._if_stack)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def preprocess_file(self, path: str) -> str:
        """Preprocess the file at *path* and return the expanded source."""
        abs_path = os.path.abspath(path)
        if abs_path in self._included_files:
            # Cycle detected — return empty string.
            # (Normal double-inclusion is handled by include guards in the
            # file itself; this only fires when A includes B includes A.)
            return ""
        if abs_path in self._pragma_once_files:
            # Already processed and the file contained #pragma once.
            return ""
        self._included_files.add(abs_path)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fl:
                source = fl.read()
        except OSError as exc:
            raise PreprocessorError(str(exc)) from exc
        result = self.preprocess(source, abs_path)
        self._included_files.discard(abs_path)
        return result

    def preprocess(self, source: str, source_path: str = "<string>") -> str:
        """
        Preprocess *source* and return the preprocessed string.

        Directive lines and line-continuation markers are replaced with blank
        lines so that the total line count of the output matches the input.
        This preserves line numbers for lexer / parser error messages.

        Lines from #include'd files are inserted inline (which shifts
        subsequent line numbers in the outer file — a future #line-marker
        scheme can address this if needed).
        """
        raw_lines = source.split("\n")
        output_parts: List[str] = []
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]
            lineno = i + 1
            # Join backslash-continuation lines into one logical line,
            # emitting a blank placeholder for each consumed physical line.
            while line.endswith("\\") and i + 1 < len(raw_lines):
                output_parts.append("")
                i += 1
                lineno = i + 1
                line = line[:-1] + raw_lines[i]
            result = self._process_line(line, source_path, lineno)
            output_parts.append(result)
            i += 1
        return "\n".join(output_parts)

    # ------------------------------------------------------------------
    # Line-level dispatch
    # ------------------------------------------------------------------

    def _process_line(self, line: str, source_path: str, lineno: int) -> str:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            m = _DIRECTIVE_RE.match(line)
            if m:
                directive = m.group(1).lower()
                rest = m.group(2).strip()
                return self._handle_directive(directive, rest, source_path, lineno)
            # Bare '#' with no word after it — ignore silently
            return ""
        if not self.including:
            return ""
        # Inject dynamic predefined macros — updated every line.
        self.defines["__FILE__"] = MacroDef("__FILE__", None, f'"{source_path}"')
        self.defines["__LINE__"] = MacroDef("__LINE__", None, str(lineno))
        return self._apply_macros(line)

    # ------------------------------------------------------------------
    # Directive dispatch
    # ------------------------------------------------------------------

    def _handle_directive(
        self,
        name: str,
        args: str,
        source_path: str,
        lineno: int,
    ) -> str:
        def _err(msg: str) -> PreprocessorError:
            return PreprocessorError(msg, source_path, lineno)

        # ----------------------------------------------------------
        # Conditional directives — processed even when NOT including
        # (the if_stack must stay balanced regardless of outer state).
        # ----------------------------------------------------------
        if name == "ifdef":
            macro_name = args.strip()
            parent = self.including
            taken = parent and (macro_name in self.defines)
            self._if_stack.append((taken, parent and not taken))
            return ""

        if name == "ifndef":
            macro_name = args.strip()
            parent = self.including
            taken = parent and (macro_name not in self.defines)
            self._if_stack.append((taken, parent and not taken))
            return ""

        if name == "if":
            parent = self.including
            taken = parent and self._eval_if_expr(args.strip(), source_path, lineno)
            self._if_stack.append((taken, parent and not taken))
            return ""

        if name == "elif":
            if not self._if_stack:
                raise _err("#elif without #if / #ifdef / #ifndef")
            active, can_switch = self._if_stack[-1]
            if can_switch:
                if self._eval_if_expr(args.strip(), source_path, lineno):
                    # Take this branch; no further switching allowed.
                    self._if_stack[-1] = (True, False)
                # else: leave as (False, True) — still looking for a True branch
            else:
                # Already took a True branch (or parent was not active).
                self._if_stack[-1] = (False, False)
            return ""

        if name == "else":
            if not self._if_stack:
                raise _err("#else without #if / #ifdef / #ifndef")
            active, can_switch = self._if_stack[-1]
            # can_switch is True iff no prior branch was taken AND parent active.
            self._if_stack[-1] = (can_switch, False)
            return ""

        if name == "endif":
            if not self._if_stack:
                raise _err("#endif without #if / #ifdef / #ifndef")
            self._if_stack.pop()
            return ""

        # ----------------------------------------------------------
        # Below this point: only execute when currently including.
        # ----------------------------------------------------------
        if not self.including:
            return ""

        if name == "include":
            return self._handle_include(args, source_path, lineno)

        if name == "define":
            self._handle_define(args, source_path, lineno)
            return ""

        if name == "undef":
            self.defines.pop(args.strip(), None)
            return ""

        if name == "error":
            raise _err(f"#error {args}")

        if name == "warning":
            print(f"{source_path}:{lineno}: warning: {args}", file=sys.stderr)
            return ""

        if name == "pragma":
            # Handle #pragma once: skip this file on subsequent includes.
            rest = args.strip()
            if rest == "once":
                abs_path = os.path.abspath(source_path)
                self._pragma_once_files.add(abs_path)
            # All other #pragma directives are silently ignored.
            return ""

        if name == "line":
            return ""  # silently ignored

        raise _err(f"unknown preprocessor directive: #{name}")

    # ------------------------------------------------------------------
    # #include
    # ------------------------------------------------------------------

    def _handle_include(self, args: str, source_path: str, lineno: int) -> str:
        args = args.strip()
        if args.startswith('"') and args.endswith('"') and len(args) >= 2:
            filename = args[1:-1]
            is_angled = False
        elif args.startswith("<") and args.endswith(">") and len(args) >= 2:
            filename = args[1:-1]
            is_angled = True
        else:
            raise PreprocessorError(
                f"malformed #include argument: {args!r}", source_path, lineno
            )

        path = self._find_include(filename, source_path, is_angled)
        if path is None:
            searched = (
                self.include_dirs
                if is_angled
                else [os.path.dirname(os.path.abspath(source_path))] + self.include_dirs
            )
            raise PreprocessorError(
                f"cannot find include file {filename!r}\n" f"  searched: {searched}",
                source_path,
                lineno,
            )
        return self.preprocess_file(path)

    def _find_include(
        self, filename: str, from_path: str, is_angled: bool
    ) -> Optional[str]:
        """Search for *filename* and return its absolute path, or None."""
        search: List[str] = []
        if not is_angled:
            # Quoted includes: search relative to the including file first.
            search.append(os.path.dirname(os.path.abspath(from_path)))
        search.extend(self.include_dirs)
        for d in search:
            candidate = os.path.join(d, filename)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
        return None

    # ------------------------------------------------------------------
    # __has_attribute / __has_builtin / __has_feature
    # ------------------------------------------------------------------

    # Attributes / builtins that this compiler (or the StackVM toolchain)
    # actually supports.  Grow these sets as features are implemented.
    _SUPPORTED_ATTRIBUTES: FrozenSet[str] = frozenset(
        {
            "packed",
            "aligned",
            "noreturn",
            "unused",
            "always_inline",
            "noinline",
            "warn_unused_result",
            "weak",
            "section",
            "constructor",
            "destructor",
        }
    )
    _SUPPORTED_BUILTINS: FrozenSet[str] = frozenset(
        {
            "builtin_bswap16",
            "builtin_bswap32",
            "builtin_bswap64",
            "builtin_clz",
            "builtin_clzl",
            "builtin_clzll",
            "builtin_expect",
            "builtin_memcpy",
            "builtin_memset",
            "builtin_strlen",
            "builtin_ctz",
            "builtin_ctzl",
            "builtin_ctzll",
            "builtin_ffs",
            "builtin_ffsl",
            "builtin_ffsll",
            "builtin_popcount",
            "builtin_popcountl",
            "builtin_popcountll",
            "builtin_unreachable",
            "builtin_offsetof",
            "builtin_types_compatible_p",
            "builtin_constant_p",
        }
    )
    _SUPPORTED_FEATURES: FrozenSet[str] = frozenset()

    def _has_attribute_value(self, macro: str, arg: str) -> int:
        """Return 1 if the queried attribute/builtin/feature is supported, else 0."""
        if macro == "__has_attribute":
            return 1 if arg in self._SUPPORTED_ATTRIBUTES else 0
        if macro in ("__has_builtin", "__has_extension"):
            return 1 if arg in self._SUPPORTED_BUILTINS else 0
        if macro == "__has_feature":
            return 1 if arg in self._SUPPORTED_FEATURES else 0
        return 0

    # ------------------------------------------------------------------
    # #define
    # ------------------------------------------------------------------

    def _handle_define(self, args: str, source_path: str, lineno: int) -> None:
        args = args.strip()
        if not args:
            raise PreprocessorError("empty #define", source_path, lineno)
        m = _DEFINE_RE.match(args)
        if not m:
            raise PreprocessorError(f"malformed #define: {args!r}", source_path, lineno)

        macro_name: str = m.group(1)
        has_params: bool = m.group(2) is not None
        params_str: Optional[str] = m.group(3)  # text inside the parens, or None
        replacement: str = m.group(4).strip() if m.group(4) else ""

        variadic = False
        if not has_params:
            params: Optional[List[str]] = None  # object-like
        elif params_str and params_str.strip():
            raw_params = [p.strip() for p in params_str.split(",")]
            if raw_params and raw_params[-1] == "...":
                variadic = True
                raw_params[-1] = "__VA_ARGS__"
            params = raw_params
        else:
            params = []  # function-like with zero parameters

        self.defines[macro_name] = MacroDef(macro_name, params, replacement, variadic)

    # ------------------------------------------------------------------
    # #if / #elif expression evaluation
    # ------------------------------------------------------------------

    def _eval_if_expr(self, expr: str, source_path: str, lineno: int) -> bool:
        """Evaluate a #if / #elif expression and return its boolean value.

        The expression is first processed for ``defined(X)`` / ``defined X``
        sub-expressions (which must NOT be macro-expanded), then the
        remainder is macro-expanded, and finally evaluated as a 64-bit
        signed integer constant expression.

        Supported operators (full C preprocessor precedence):
          Unary:        !  ~  -  +
          Multiplicative: *  /  %
          Additive:     +  -
          Shift:        <<  >>
          Relational:   <  >  <=  >=
          Equality:     ==  !=
          Bitwise:      &  ^  |
          Logical:      &&  ||
          Parentheses:  ( )
          defined(X) / defined X
          __has_attribute(X) / __has_builtin(X) / __has_feature(X)
          __has_include("f") / __has_include(<f>)
        """
        expr = expr.strip()
        if not expr:
            return False

        # Replace defined(X) / defined X with 0 or 1 BEFORE macro expansion.
        def _sub_defined(s: str) -> str:
            # defined(MACRO) form
            s = re.sub(
                r"\bdefined\s*\(\s*(\w+)\s*\)",
                lambda m: "1" if m.group(1) in self.defines else "0",
                s,
            )
            # defined MACRO form (not followed by '(')
            s = re.sub(
                r"\bdefined\s+(\w+)",
                lambda m: "1" if m.group(1) in self.defines else "0",
                s,
            )
            return s

        expr = _sub_defined(expr)

        # Replace __has_include("f") / __has_include(<f>) with 0 or 1
        # BEFORE general macro expansion.
        def _sub_has_include(s: str) -> str:
            def _repl(m: "re.Match") -> str:
                return str(self._has_include_value(m.group(1), source_path))

            return re.sub(r"__has_include\s*\(([^)]*)\)", _repl, s)

        expr = _sub_has_include(expr)

        # Macro-expand the remaining expression text.
        expr = self._apply_macros(expr, preserve_has_include=True)
        expr = _sub_has_include(expr)
        expr = expr.strip()
        if not expr:
            return False

        # Evaluate the expanded integer constant expression.
        try:
            val = self._eval_int_expr(expr)
            return bool(val)
        except Exception:
            print(
                f"{source_path}:{lineno}: warning: "
                f"unsupported #if expression {expr!r}, treating as 0",
                file=sys.stderr,
            )
            return False

    def _has_include_value(self, arg: str, source_path: str) -> int:
        """Return 1 when a __has_include operand resolves to a file, else 0."""
        arg = arg.strip()
        if arg.startswith('"') and arg.endswith('"'):
            filename = arg[1:-1]
            is_angled = False
        elif arg.startswith("<") and arg.endswith(">"):
            filename = arg[1:-1]
            is_angled = True
        else:
            return 0
        found = self._find_include(filename, source_path, is_angled)
        return 1 if found is not None else 0

    # Operator precedence levels for _eval_int_expr (lowest first).
    # Each entry is a tuple of operator strings at the same precedence.
    _IF_BINOP_LEVELS: List[Tuple[str, ...]] = [
        ("||",),
        ("&&",),
        ("|",),
        ("^",),
        ("&",),
        ("==", "!="),
        ("<=", ">=", "<", ">"),  # two-char before one-char
        ("<<", ">>"),
        ("+", "-"),
        ("*", "/", "%"),
    ]

    def _eval_int_expr(self, expr: str) -> int:
        """Recursively evaluate an integer constant expression string.

        Returns a 64-bit signed integer value.  Raises ValueError on
        syntax errors or unsupported constructs.
        """
        expr = expr.strip()
        if not expr:
            raise ValueError("empty expression")

        # Try a plain integer literal (decimal, hex, octal, binary).
        # Strip common C suffixes: U, L, UL, LL, ULL (case-insensitive).
        lit = re.sub(r"[uUlL]+$", "", expr)
        try:
            return int(lit, 0)
        except ValueError:
            pass

        # Outer parentheses stripping — only if the ENTIRE expr is wrapped.
        if expr.startswith("(") and expr.endswith(")"):
            depth = 0
            all_wrapped = True
            for idx, ch in enumerate(expr):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if depth == 0 and idx < len(expr) - 1:
                    all_wrapped = False
                    break
            if all_wrapped:
                return self._eval_int_expr(expr[1:-1])

        # Binary operator search: scan right-to-left through each precedence
        # level (lowest first).  Finding the rightmost operator at depth 0
        # gives left-associativity via recursion on the left sub-expression.
        for level in self._IF_BINOP_LEVELS:
            i = len(expr) - 1
            depth = 0
            while i >= 0:
                ch = expr[i]
                if ch in ")]}":
                    depth += 1
                elif ch in "([{":
                    depth -= 1
                elif depth == 0:
                    for op in level:
                        end_op = i + 1
                        start_op = i - len(op) + 1
                        if start_op >= 0 and expr[start_op:end_op] == op:
                            # Make sure it is not part of a longer operator.
                            # e.g. '<' should not match inside '<<' or '<='.
                            before = expr[start_op - 1] if start_op > 0 else ""
                            after = expr[end_op] if end_op < len(expr) else ""
                            if op == "<" and (before == "<" or after in "<="):
                                break
                            if op == ">" and (before in ">=" or after in ">="):
                                break
                            if op == "&" and (before == "&" or after == "&"):
                                break
                            if op == "|" and (before == "|" or after == "|"):
                                break
                            if op in ("+", "-") and start_op == 0:
                                break  # would be unary — handled below
                            lhs_str = expr[:start_op].strip()
                            rhs_str = expr[end_op:].strip()
                            if not lhs_str or not rhs_str:
                                break
                            lhs = self._eval_int_expr(lhs_str)
                            rhs = self._eval_int_expr(rhs_str)
                            if op == "||":
                                return int(bool(lhs) or bool(rhs))
                            if op == "&&":
                                return int(bool(lhs) and bool(rhs))
                            if op == "|":
                                return lhs | rhs
                            if op == "^":
                                return lhs ^ rhs
                            if op == "&":
                                return lhs & rhs
                            if op == "==":
                                return int(lhs == rhs)
                            if op == "!=":
                                return int(lhs != rhs)
                            if op == "<=":
                                return int(lhs <= rhs)
                            if op == ">=":
                                return int(lhs >= rhs)
                            if op == "<":
                                return int(lhs < rhs)
                            if op == ">":
                                return int(lhs > rhs)
                            if op == "<<":
                                return lhs << rhs
                            if op == ">>":
                                return lhs >> rhs
                            if op == "+":
                                return lhs + rhs
                            if op == "-":
                                return lhs - rhs
                            if op == "*":
                                return lhs * rhs
                            if op == "/":
                                if rhs == 0:
                                    raise ValueError("division by zero")
                                return int(lhs / rhs)  # truncate towards zero
                            if op == "%":
                                if rhs == 0:
                                    raise ValueError("modulo by zero")
                                return lhs % rhs
                i -= 1

        # Unary operators.
        if expr.startswith("!"):
            return int(not self._eval_int_expr(expr[1:]))
        if expr.startswith("~"):
            return ~self._eval_int_expr(expr[1:])
        if expr.startswith("-"):
            return -self._eval_int_expr(expr[1:])
        if expr.startswith("+"):
            return self._eval_int_expr(expr[1:])

        raise ValueError(f"cannot evaluate constant expression: {expr!r}")

    # ------------------------------------------------------------------
    # Macro substitution
    # ------------------------------------------------------------------

    def _apply_macros(
        self,
        text: str,
        _expanding: FrozenSet[str] = frozenset(),
        preserve_has_include: bool = False,
    ) -> str:
        """Apply macro substitution to *text*, skipping string/char literals and
        block/line comments.

        ``self._in_block_comment`` carries multi-line block-comment state
        between calls: it is True when a ``/*`` on a previous line has not
        yet been closed by ``*/``.

        *_expanding* names macros whose expansion is in progress; they are
        not re-expanded to prevent infinite recursion.
        """
        # Recursive calls (expanding macro replacement text) are never
        # inside a real block comment, so only the top-level call checks
        # _in_block_comment.
        is_top_level = not _expanding

        if not self.defines and (not is_top_level or not self._in_block_comment):
            return text

        result: List[str] = []
        i = 0
        n = len(text)

        # ---- Continue a block comment that started on a previous line ----
        if is_top_level and self._in_block_comment:
            j = text.find("*/", i)
            if j == -1:
                # Entire line is inside the block comment — output as-is.
                return text
            result.append(text[i : j + 2])
            i = j + 2
            self._in_block_comment = False

        while i < n:
            ch = text[i]

            # ---- Block comment /* ... */ — copy verbatim, skip macros ----
            if ch == "/" and i + 1 < n and text[i + 1] == "*":
                j = text.find("*/", i + 2)
                if j == -1:
                    # Block comment runs to end of line (multi-line comment).
                    result.append(text[i:])
                    if is_top_level:
                        self._in_block_comment = True
                    break
                result.append(text[i : j + 2])
                i = j + 2
                continue

            # ---- Skip double-quoted string literals "..." ----------------
            if ch == '"':
                j = i + 1
                while j < n:
                    c2 = text[j]
                    j += 1
                    if c2 == "\\":
                        j += 1  # skip escaped character
                        continue
                    if c2 == '"':
                        break
                result.append(text[i:j])
                i = j
                continue

            # ---- Skip single-quoted char literals '...' -----------------
            if ch == "'":
                j = i + 1
                while j < n:
                    c2 = text[j]
                    j += 1
                    if c2 == "\\":
                        j += 1
                        continue
                    if c2 == "'":
                        break
                result.append(text[i:j])
                i = j
                continue

            # ---- Line comment // — do not expand past this point --------
            if ch == "/" and i + 1 < n and text[i + 1] == "/":
                result.append(text[i:])
                break

            # ---- Identifier (possible macro name) -----------------------
            if ch.isalpha() or ch == "_":
                j = i + 1
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                ident = text[i:j]

                # __COUNTER__ — expands to an incrementing integer.
                if ident == "__COUNTER__" and ident not in _expanding:
                    result.append(str(self._counter))
                    self._counter += 1
                    i = j
                    continue

                # __has_attribute / __has_builtin / __has_feature / __has_include —
                # consume the following (...) argument and expand to 0 or 1.
                if (
                    ident
                    in (
                        "__has_attribute",
                        "__has_builtin",
                        "__has_feature",
                        "__has_extension",
                    )
                    and ident not in _expanding
                ):
                    k = j
                    while k < n and text[k] in " \t":
                        k += 1
                    if k < n and text[k] == "(":
                        args, end_args = self._parse_macro_args(text, k)
                        if args is not None:
                            arg_name = args[0].strip().strip("_") if args else ""
                            val = self._has_attribute_value(ident, arg_name)
                            result.append(str(val))
                            i = end_args
                            continue

                if ident == "__has_include" and ident not in _expanding:
                    k = j
                    while k < n and text[k] in " \t":
                        k += 1
                    if k < n and text[k] == "(":
                        # Find the closing paren (the argument may contain < > or " ")
                        args, end_args = self._parse_macro_args(text, k)
                        if args is not None:
                            if preserve_has_include:
                                result.append(text[i:end_args])
                            else:
                                val = 0  # not evaluated at expansion time; handled in _eval_if_expr
                                result.append(str(val))
                            i = end_args
                            continue

                macro = self.defines.get(ident)
                if macro is not None and ident not in _expanding:
                    if macro.params is None:
                        # Object-like: process ## then recursively expand.
                        pasted = self._process_token_paste(macro.replacement)
                        expanded = self._apply_macros(
                            pasted,
                            _expanding | {ident},
                            preserve_has_include,
                        )
                        result.append(expanded)
                        i = j
                        continue
                    else:
                        # Function-like: look for '(' (allowing whitespace).
                        k = j
                        while k < n and text[k] in " \t":
                            k += 1
                        if k < n and text[k] == "(":
                            args, end = self._parse_macro_args(text, k)
                            if args is not None:
                                expanded = self._expand_func_macro(
                                    macro,
                                    args,
                                    _expanding | {ident},
                                    preserve_has_include,
                                )
                                result.append(expanded)
                                i = end
                                continue
                # Not a macro (or already expanding) — output as-is.
                result.append(ident)
                i = j
                continue

            # ---- Any other character ------------------------------------
            result.append(ch)
            i += 1

        return "".join(result)

    def _parse_macro_args(
        self, text: str, start: int
    ) -> Tuple[Optional[List[str]], int]:
        """Parse function-like macro arguments starting at '(' at *start*.

        Returns ``(list_of_arg_strings, position_after_closing_paren)`` on
        success, or ``(None, start)`` if the parentheses are unmatched.
        """
        assert text[start] == "("
        depth = 0
        current: List[str] = []
        args: List[str] = []
        i = start
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "(":
                depth += 1
                if depth > 1:
                    current.append(ch)
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    args.append("".join(current).strip())
                    return args, i + 1
                current.append(ch)
            elif ch == "," and depth == 1:
                args.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
            i += 1
        return None, start  # unmatched parenthesis

    def _expand_func_macro(
        self,
        macro: MacroDef,
        args: List[str],
        _expanding: FrozenSet[str],
        preserve_has_include: bool = False,
    ) -> str:
        """Expand a function-like macro call."""
        if macro.variadic:
            # Collect all arguments beyond the fixed parameters into __VA_ARGS__.
            # __VA_ARGS__ is always the last entry in macro.params.
            required = len(macro.params) - 1
            if len(args) < required:
                raise PreprocessorError(
                    f"macro '{macro.name}' takes at least {required} argument(s), "
                    f"got {len(args)}"
                )
            va_str = ", ".join(args[required:])
            args = list(args[:required]) + [va_str]
        else:
            # F() with zero params: _parse_macro_args returns [''], normalise.
            if len(args) == 1 and args[0] == "" and len(macro.params) == 0:
                args = []
            if len(args) != len(macro.params):
                raise PreprocessorError(
                    f"macro '{macro.name}' takes {len(macro.params)} argument(s), "
                    f"got {len(args)}"
                )
        # Process # stringification FIRST, using the raw (un-expanded) args.
        # The C standard requires that stringification captures the token text
        # before any macro expansion of the argument.
        replacement = self._process_stringification(
            macro.replacement, macro.params, args
        )
        # GCC ##__VA_ARGS__ extension: handle comma deletion and ## removal
        # while __VA_ARGS__ is still literally present in the replacement text,
        # so that the substitution can be targeted precisely.
        if macro.variadic:
            va_val = args[-1] if args else ""
            if va_val == "":
                # Empty __VA_ARGS__: delete the comma immediately preceding ##
                # and the ## operator itself (GCC comma-deletion rule).
                replacement = re.sub(r",\s*##\s*__VA_ARGS__", "", replacement)
            # Remove any remaining ## before __VA_ARGS__ (non-empty case: just
            # strip the ## so __VA_ARGS__ is substituted normally below).
            replacement = re.sub(r"##\s*__VA_ARGS__", "__VA_ARGS__", replacement)
        # Expand any macros in the argument expressions.
        expanded_args = [
            self._apply_macros(a, _expanding, preserve_has_include) for a in args
        ]
        # Substitute parameter names in the replacement template.
        substituted = self._substitute_params(replacement, macro.params, expanded_args)
        # Process ## token-pasting after parameter substitution.
        substituted = self._process_token_paste(substituted)
        # Recursively expand macros in the result (allows pasted token to be a macro).
        return self._apply_macros(substituted, _expanding, preserve_has_include)

    @staticmethod
    def _stringify_arg(raw_arg: str) -> str:
        """Wrap *raw_arg* in a C string literal, applying the transformations
        required by the C11 standard for the ``#`` stringification operator:

        * Leading and trailing whitespace is stripped.
        * Internal whitespace sequences are collapsed to a single space.
        * Backslashes are escaped as ``\\\\``.
        * Double-quote characters are escaped as ``\\"``.
        """
        s = raw_arg.strip()
        s = re.sub(r"\s+", " ", s)
        s = s.replace("\\", "\\\\")
        s = s.replace('"', '\\"')
        return f'"{s}"'

    @staticmethod
    def _process_stringification(
        replacement: str, params: List[str], raw_args: List[str]
    ) -> str:
        """Replace every ``# param`` occurrence in *replacement* with the
        stringified form of the corresponding raw (un-expanded) argument.

        A ``#`` immediately followed by optional whitespace and then a
        parameter name is treated as the stringification operator.  A ``##``
        token-paste sequence is left untouched.

        String and character literals in the replacement text are copied
        verbatim so that a ``#`` inside a literal is never misinterpreted.
        """
        if "#" not in replacement or not params:
            return replacement

        param_map = dict(zip(params, raw_args))
        result: List[str] = []
        i = 0
        n = len(replacement)

        while i < n:
            ch = replacement[i]

            # ---- Skip double-quoted string literals in the replacement ----
            if ch == '"':
                j = i + 1
                while j < n:
                    c2 = replacement[j]
                    j += 1
                    if c2 == "\\":
                        j += 1
                        continue
                    if c2 == '"':
                        break
                result.append(replacement[i:j])
                i = j
                continue

            # ---- Skip single-quoted char literals in the replacement ------
            if ch == "'":
                j = i + 1
                while j < n:
                    c2 = replacement[j]
                    j += 1
                    if c2 == "\\":
                        j += 1
                        continue
                    if c2 == "'":
                        break
                result.append(replacement[i:j])
                i = j
                continue

            if ch == "#":
                # ## token-paste: copy verbatim and advance past both chars.
                if i + 1 < n and replacement[i + 1] == "#":
                    result.append("##")
                    i += 2
                    continue

                # Potential stringification: # followed by optional whitespace
                # then a parameter name identifier.
                j = i + 1
                while j < n and replacement[j] in " \t":
                    j += 1
                if j < n and (replacement[j].isalpha() or replacement[j] == "_"):
                    k = j + 1
                    while k < n and (replacement[k].isalnum() or replacement[k] == "_"):
                        k += 1
                    ident = replacement[j:k]
                    if ident in param_map:
                        result.append(Preprocessor._stringify_arg(param_map[ident]))
                        i = k
                        continue

                # Not a stringification operator — copy the # verbatim.
                result.append("#")
                i += 1
                continue

            result.append(ch)
            i += 1

        return "".join(result)

    @staticmethod
    def _substitute_params(replacement: str, params: List[str], args: List[str]) -> str:
        """Replace parameter names in *replacement* with their argument strings.

        Uses identifier-aware scanning so that a parameter name only matches
        at word boundaries (e.g. param ``x`` does not match ``xy``).
        """
        if not params:
            return replacement
        param_map = dict(zip(params, args))
        result: List[str] = []
        i = 0
        n = len(replacement)
        while i < n:
            ch = replacement[i]
            if ch.isalpha() or ch == "_":
                j = i + 1
                while j < n and (replacement[j].isalnum() or replacement[j] == "_"):
                    j += 1
                ident = replacement[i:j]
                result.append(param_map.get(ident, ident))
                i = j
            else:
                result.append(ch)
                i += 1
        return "".join(result)

    @staticmethod
    def _process_token_paste(text: str) -> str:
        """Process ``##`` token-pasting operators in *text*.

        Concatenates the identifier/number tokens immediately to the left and
        right of each ``##`` operator, scanning left-to-right so that
        ``A ## B ## C`` is handled correctly (→ ``AB ## C`` → ``ABC``).

        ``##`` at the very start or end of the replacement list is undefined
        behaviour in standard C; a warning is emitted to stderr and the
        stray operator is dropped.
        """
        if "##" not in text:
            return text

        # Warn about ## at start / end (UB — strip the operator).
        stripped = text.strip()
        if stripped.startswith("##"):
            print(
                "warning: '##' at start of macro replacement is undefined behavior",
                file=sys.stderr,
            )
            text = re.sub(r"^\s*##\s*", "", text)
        if text.strip().endswith("##"):
            print(
                "warning: '##' at end of macro replacement is undefined behavior",
                file=sys.stderr,
            )
            text = re.sub(r"\s*##\s*$", "", text)

        # Paste tokens left-to-right.  Loop because the regex consumes the
        # right-hand token, leaving a subsequent ## unmatched on one pass
        # (e.g. "A ## B ## C" → "AB ## C" on the first iteration).
        prev = None
        while prev != text:
            prev = text
            text = _TOKEN_PASTE_RE.sub(lambda m: m.group(1) + m.group(2), text)
        return text


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------


def preprocess(
    source: str,
    include_dirs: List[str],
    defines: Optional[Dict[str, MacroDef]] = None,
) -> str:
    """Preprocess a C/C++ source string and return the expanded result.

    Parameters
    ----------
    source:
        Raw source text to preprocess.
    include_dirs:
        Directories to search for ``#include <...>`` and ``#include "..."``
        files (in addition to the directory of the source file itself for
        quoted includes).
    defines:
        Optional pre-defined macros (equivalent to ``-D`` on the command
        line).  Map macro names to ``MacroDef`` instances.
    """
    p = Preprocessor(include_dirs, defines)
    return p.preprocess(source)
