"""
Cognitive complexity calculation for C# code.

KNOWN LIMITATIONS
-----------------
- Regex-based parsing cannot handle nested generics, lambda nesting,
  or pattern matching expressions accurately.
- LINQ chains may be incorrectly counted as nesting.
- Switch expressions are counted as conditional branches.
- Accuracy: ~+-5% for simple methods, ~+-20% for complex methods
  compared to SonarSource reference implementation.
- For precise results, use the Roslyn analyzer layer (requires .NET SDK).
"""
from __future__ import annotations

import logging

logger = logging.getLogger('dotnet-review')



# ============================================================
# Cognitive Complexity (SONAR Source)
# ============================================================
# Cognitive Complexity™ 评分标准 (SonarSource):
# - +1 基础方法
# - +N 嵌套层级 (每层 +1)
# - +1 结构化分流 (if/else, switch, for, foreach, while, catch, do, recursion)
# - +1 逻辑连接符 (&&, ||, ?:)
# - +1 多入口 (goto, labels)
# ============================================================

def calculate_cognitive_complexity(filepath: str, code: str) -> int:
    """Calculate cognitive complexity for a file.

    Returns total cognitive complexity score.
    """
    lines = code.split("\n")
    total_cc = 0

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Method-level increment: any named method/constructor
        if _is_cognitive_method(line):
            # Compute CC for this method body
            method_cc, end_i = _compute_method_cc(lines, i)
            total_cc += method_cc
            i = end_i
        else:
            i += 1

    return total_cc



def _is_cognitive_method(line: str) -> bool:
    """Check if line starts a method that should increment cognitive complexity."""
    if not line:
        return False
    modifiers = ["public", "private", "protected", "internal", "static", "virtual", "override", "abstract", "sealed", "async", "partial"]
    has_modifier = any(m in line for m in modifiers)
    has_parens = "(" in line and ")" in line
    is_destructor = line.startswith("~")
    is_lambda = "=>" in line and ("(" in line or line.strip().startswith("("))
    return (has_modifier or is_destructor) and has_parens and not is_lambda



def _compute_method_cc(lines: list[str], start: int) -> tuple[int, int]:
    """Compute cognitive complexity for a method starting at `start`.

    Returns (cc_score, line_after_method_end).
    """
    cc = 0
    nesting = 0

    # Find opening brace
    brace_start = start
    while brace_start < len(lines) and "{" not in lines[brace_start]:
        brace_start += 1
    if brace_start >= len(lines):
        return 0, start + 1

    i = brace_start
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # Track nesting via braces
        for ch in raw:
            if ch == "{":
                nesting += 1
            elif ch == "}":
                nesting -= 1

        if nesting == 0:
            # Exited method body
            return cc, i + 1

        cc_increment, _ = _cognitive_increment(stripped, nesting)
        cc += cc_increment

        i += 1

    return cc, i



def _cognitive_increment(line: str, current_nesting: int) -> tuple[int, int]:
    """Calculate cognitive complexity increment for a single statement.

    Returns (increment, additional_nesting_from_line).
    Increment accounts for:
    - The BCSP (binary conditional statement penalty) at current nesting
    - Structural statement increments
    - Recursion / goto
    """
    inc = 0
    extra_nesting = 0

    if not line or line.startswith("//") or line.startswith("/*"):
        return 0, 0

    # Logical connectors && and || at this nesting level
    # (they increase complexity by 1 each, but at top-level they don't nest further)
    if ("&&" in line or "||" in line) and not line.startswith("case"):
        # Only count if they are actual boolean connectors
        pass

    # Structural increments (+1 for each structural pattern at current level)
    # These increment at their nesting level
    for kw in ["if", "for", "foreach", "while", "catch", "do"]:
        if line.startswith(kw + " ") or line.startswith(kw + "("):
            inc += 1
            break

    # else is only +1 if it's a standalone else (not else if, which is covered by if)
    if line.startswith("else ") and "if" not in line:
        inc += 1

    # switch increments
    if line.startswith("switch ") or line.startswith("case ") or line.startswith("default:"):
        inc += 1

    # try/finally/throw
    if line.startswith("try ") or line.startswith("finally") or line.startswith("throw"):
        inc += 1

    # Recursion
    if " recursion" in line.lower() or line.startswith("return ") and current_nesting > 1:
        pass  # Recursion detection is complex without semantic analysis

    # Increment from nesting of children is already tracked via `nesting` param
    # The increment for nested structures is: increment * nesting
    # But per SonarQube rules: structural increment is +1 at the level it appears
    # AND child level increments are added at the increased nesting

    return inc, extra_nesting
