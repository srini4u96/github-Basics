from __future__ import annotations

import re
from typing import List, Tuple

_STRINGS_OR_COMMENTS = re.compile(r"('(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")|//[^\n]*|/\*.*?\*/", re.S)
_DECISIONS = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?![.?])")


def strip_comments(code: str) -> str:
    """Remove // and /* */ comments while leaving string literals untouched."""
    return _STRINGS_OR_COMMENTS.sub(lambda m: m.group(1) or "", code or "")


def code_metrics(code: str) -> Tuple[int, int]:
    """(non-blank lines, approximate cyclomatic complexity)."""
    lines = sum(1 for line in code.splitlines() if line.strip())
    without_strings = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", code)
    return lines, 1 + len(_DECISIONS.findall(without_strings))


def add_unique(items: List[str], value: str) -> None:
    if value and value not in items:
        items.append(value)
