#!/usr/bin/env python3
"""
Count rules actually emitted by the C# analyzers.

This is the single source of truth for "how many rules does the engine
actually execute?" — used to verify SKILL.md and references/*.md don't
drift from the real implementation.

Two categories:
  AST      — C# Roslyn AST analyzer (scripts/csharp-ast-analyzer/Program.cs)
  SEMANTIC — C# Roslyn semantic analyzer (scripts/csharp-semantic-analyzer/Program.cs)

We grep for the rule IDs that the analyzers *emit* (not the IDs they
*consume* internally). The patterns below cover each layer's emission
convention.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AST_CS = ROOT / "scripts" / "csharp-ast-analyzer" / "Program.cs"
SEM_CS = ROOT / "scripts" / "csharp-semantic-analyzer" / "Program.cs"

# AST analyzer emits rules via `Add("LEGACY_xxx", ...)` or helper functions
# like `CheckPascalCase(Identifier, "LEGACY_xxx", ...)`. Capture the
# LEGACY_xxx ID in either case.
AST_ADD_RE = re.compile(
    r'\b(?:Add|CheckPascalCase)\(\s*(?:\w+\.\w+,\s*)?'
    r'"(?P<id>LEGACY_[A-Za-z0-9_]+)"'
)
# Semantic analyzer emits via Add(diagnostics, file, loc, "<ID>", ...) with
# 4-arg signature; "ID" can be SEM/EF/ASP/P/RCS followed by digits. We capture any
# quoted 4-7 char code inside an Add call.
SEM_ADD_RE = re.compile(
    r'\bAdd\(\s*diagnostics,\s*[^,]+,\s*[^,]+,\s*"(?P<id>(?:SEM|EF|ASP|P|RCS)\d{2,4})"'
)


def count_layer(name: str, path: Path, pattern: re.Pattern, group: str = "id") -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [m.group(group) for m in pattern.finditer(text)]


def main() -> int:
    ast_ids = sorted(set(count_layer("AST", AST_CS, AST_ADD_RE)))
    sem_ids = sorted(set(count_layer("SEM", SEM_CS, SEM_ADD_RE)))

    print("=" * 60)
    print("dotnet-code-review rule counts (computed from source)")
    print("=" * 60)
    print(f"AST LEGACY_* rules emitted     : {len(ast_ids):4d}")
    print(f"Semantic SEM/EF/ASP/P/RCS rules  : {len(sem_ids):4d}")
    print(f"  - SEM_*                       : {sum(1 for i in sem_ids if i.startswith('SEM')):4d}")
    print(f"  - EF_*                        : {sum(1 for i in sem_ids if i.startswith('EF')):4d}")
    print(f"  - ASP_*                       : {sum(1 for i in sem_ids if i.startswith('ASP')):4d}")
    print(f"  - P_*                         : {sum(1 for i in sem_ids if i.startswith('P')):4d}")
    print(f"  - RCS_*                       : {sum(1 for i in sem_ids if i.startswith('RCS')):4d}")
    print(f"  Total unique active (no dedupe): {len(ast_ids) + len(sem_ids):4d}")

    print()
    print("-" * 60)
    print("Semantic codes:", ", ".join(sem_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())