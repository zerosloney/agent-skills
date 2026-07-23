from __future__ import annotations
import logging
import re
from .models import CodeIssue

logger = logging.getLogger('dotnet-review')



# ============================================================
# XML Documentation Check
# ============================================================

def check_xml_documentation(filepath: str, code: str) -> list[CodeIssue]:
    """Check public APIs for missing XML documentation."""
    issues = []
    lines = code.split("\n")
    # Pattern: public method/class/interface declaration without /// comment before
    public_pattern = re.compile(
        r"^\s*public\s+(?:(?:static|abstract|sealed|partial|async)\s+)*(?:class|interface|struct|enum|[\w<>?,\s\[\]]+)\s+\w+",
    )

    for i, line in enumerate(lines):
        if not public_pattern.match(line):
            continue
        # Skip if already has XML doc above (look back up to 5 lines)
        has_doc = False
        for j in range(max(0, i - 5), i):
            if "///" in lines[j]:
                has_doc = True
                break
        if has_doc:
            continue
        # Skip if it's just a property/getter/setter
        if "{" in line and ("=>" in line or "get;" in line or "set;" in line):
            continue
        # Extract the member name
        m = re.search(r"\b(?:class|interface|struct|enum)\s+(\w+)|(?:[\w<>?,\s]+)\s+(\w+)\s*[(<]", line)
        name = m.group(1) or m.group(2) if m else "?"
        issues.append(CodeIssue(
            file=filepath,
            line=i + 1,
            column=1,
            severity="info",
            category="style",
            rule="DOC001",
            message=f"Public member '{name}' missing XML documentation",
            source="doc",
            suggestion="Add /// XML doc comments for public APIs.",
        ))
    return issues
