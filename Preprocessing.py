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

Not implemented (future work):
  ## token-pasting, # stringification, __VA_ARGS__, arithmetic #if
  expressions, #line, predefined macros (__FILE__, __LINE__).
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

    __slots__ = ("name", "params", "replacement")

    def __init__(
        self,
        name: str,
        params: Optional[List[str]],
        replacement: str,
    ) -> None:
        self.name = name
        # params is None  → object-like macro   (#define A value)
        # params is list  → function-like macro  (#define F(x) expr)
        self.params = params
        self.replacement = replacement


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
            return ""  # silently ignored

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

        if not has_params:
            params: Optional[List[str]] = None  # object-like
        elif params_str and params_str.strip():
            params = [p.strip() for p in params_str.split(",")]
        else:
            params = []  # function-like with zero parameters

        self.defines[macro_name] = MacroDef(macro_name, params, replacement)

    # ------------------------------------------------------------------
    # #if / #elif expression evaluation
    # ------------------------------------------------------------------

    def _eval_if_expr(self, expr: str, source_path: str, lineno: int) -> bool:
        """Evaluate a simple #if / #elif expression.

        Supported forms:
          integer literal (0, 1, 0xFF, ...)
          defined(X)  /  defined X
          !defined(X) / !defined X
          expr && expr
          expr || expr
          ! expr
        """
        expr = expr.strip()
        if not expr:
            return False

        # Integer literal (decimal, hex, octal, binary)
        try:
            return bool(int(expr, 0))
        except ValueError:
            pass

        # defined(X) or !defined(X) — with optional spaces
        m = re.match(r"^(!?)\s*defined\s*\(\s*(\w+)\s*\)\s*$", expr)
        if not m:
            m = re.match(r"^(!?)\s*defined\s+(\w+)\s*$", expr)
        if m:
            is_negated = bool(m.group(1))
            is_defined = m.group(2) in self.defines
            return is_defined if not is_negated else not is_defined

        # Split on || first (lower precedence), then && within each part.
        or_parts = self._split_logical(expr, "||")
        if len(or_parts) > 1:
            return any(self._eval_if_expr(p, source_path, lineno) for p in or_parts)

        and_parts = self._split_logical(expr, "&&")
        if len(and_parts) > 1:
            return all(self._eval_if_expr(p, source_path, lineno) for p in and_parts)

        # Leading '!'
        if expr.startswith("!"):
            return not self._eval_if_expr(expr[1:].strip(), source_path, lineno)

        # Parenthesised sub-expression
        if expr.startswith("(") and expr.endswith(")"):
            return self._eval_if_expr(expr[1:-1], source_path, lineno)

        # Unsupported — warn and treat as False
        print(
            f"{source_path}:{lineno}: warning: "
            f"unsupported #if expression {expr!r}, treating as 0",
            file=sys.stderr,
        )
        return False

    @staticmethod
    def _split_logical(expr: str, op: str) -> List[str]:
        """Split *expr* on *op* ('||' or '&&') at parenthesis depth 0."""
        depth = 0
        parts: List[str] = []
        start = 0
        op_len = len(op)
        for i in range(len(expr)):
            if expr[i] == "(":
                depth += 1
            elif expr[i] == ")":
                depth -= 1
            elif depth == 0 and expr[i : i + op_len] == op:
                parts.append(expr[start:i].strip())
                start = i + op_len
        parts.append(expr[start:].strip())
        return parts

    # ------------------------------------------------------------------
    # Macro substitution
    # ------------------------------------------------------------------

    def _apply_macros(self, text: str, _expanding: FrozenSet[str] = frozenset()) -> str:
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
                macro = self.defines.get(ident)
                if macro is not None and ident not in _expanding:
                    if macro.params is None:
                        # Object-like: substitute and recursively expand.
                        expanded = self._apply_macros(
                            macro.replacement, _expanding | {ident}
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
                                    macro, args, _expanding | {ident}
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
    ) -> str:
        """Expand a function-like macro call."""
        # F() with zero params: _parse_macro_args returns [''], normalise.
        if len(args) == 1 and args[0] == "" and len(macro.params) == 0:
            args = []
        if len(args) != len(macro.params):
            raise PreprocessorError(
                f"macro '{macro.name}' takes {len(macro.params)} argument(s), "
                f"got {len(args)}"
            )
        # Expand any macros in the argument expressions first.
        expanded_args = [self._apply_macros(a, _expanding) for a in args]
        # Substitute parameter names in the replacement template.
        substituted = self._substitute_params(
            macro.replacement, macro.params, expanded_args
        )
        # Recursively expand macros in the result.
        return self._apply_macros(substituted, _expanding)

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
