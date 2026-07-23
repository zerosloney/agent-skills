from __future__ import annotations
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger('dotnet-review')



# ============================================================
# API Compatibility Check (Roslyn symbols)
# ============================================================

def _extract_public_api(filepath: str) -> set[str]:
    """Extract public API signatures from a .cs file.

    Returns a set of strings like "ClassName.MethodName(Type1, Type2)"
    """
    apis = set()
    try:
        code = Path(filepath).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return apis

    # Regex-based extraction (lightweight, no Roslyn dependency)
    # Matches: public class/interface/struct Name, public ReturnType MethodName(...)
    for m in re.finditer(r"\bpublic\s+(?:static\s+|abstract\s+|sealed\s+|virtual\s+|override\s+)*" +
                         r"(?:class|interface|struct|enum)\s+(\w+)", code):
        apis.add(f"type:{m.group(1)}")

    for m in re.finditer(r"\bpublic\s+(?:static\s+|abstract\s+|sealed\s+|virtual\s+|override\s+)*" +
                         r"(?:[\w<>?,\s]+)\s+(\w+)\s*\(([^)]*)\)", code):
        params = ", ".join(p.strip().split()[0] if p.strip() else "" for p in m.group(2).split(","))
        apis.add(f"method:{m.group(1)}({params})")

    for m in re.finditer(r"\bpublic\s+(?:[\w<>?,\s]+)\s+(\w+)\s*\{", code):
        apis.add(f"prop:{m.group(1)}")

    return apis



def check_api_compatibility(
    project_root: str,
    base_ref: str = "HEAD",
    packages: list[dict] | None = None,
) -> dict:
    """Check public API compatibility between current working tree and base_ref.

    Uses git diff to identify changed .cs files, then compares public API
    surface area between the two revisions.

    Returns:
        {
            "added": ["method:Foo(string)"],
            "removed": ["type:OldType"],
            "changed": ["method:Bar(int)->method:Bar(string)"],
            "breaking": ["Removed public class OldType (breaking)"],
            "error": "..." or None
        }
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
            capture_output=True, text=True, timeout=15, cwd=project_root,
        )
        if result.returncode != 0:
            return {"added": [], "removed": [], "changed": [], "breaking": [],
                    "error": f"git diff failed: {result.stderr.strip()}"}
        changed_files = [f for f in result.stdout.splitlines() if f.strip().endswith(".cs")]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"added": [], "removed": [], "changed": [], "breaking": [],
                "error": "git not available"}

        # Build temp dirs for base and current, extract APIs, then clean up
    tmp_base = None
    tmp_curr = None
    base_apis: set[str] = set()
    curr_apis: set[str] = set()
    try:
        import tempfile
        import shutil
        tmp_base = tempfile.mkdtemp(prefix="api_base_")
        tmp_curr = tempfile.mkdtemp(prefix="api_curr_")

        # Export current versions
        for f in changed_files:
            src = Path(project_root) / f
            if not src.exists():
                continue
            dst = Path(tmp_curr) / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        # Export base versions
        for f in changed_files:
            proc = subprocess.run(
                ["git", "show", f"{base_ref}:{f}"],
                capture_output=True, text=True, timeout=10, cwd=project_root,
            )
            if proc.returncode == 0:
                dst = Path(tmp_base) / f
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(proc.stdout, encoding="utf-8", errors="ignore")

        # Extract public APIs before cleanup
        for f in changed_files:
            base_apis.update(_extract_public_api(str(Path(tmp_base) / f)))
            curr_apis.update(_extract_public_api(str(Path(tmp_curr) / f)))

    except Exception as e:
        return {"added": [], "removed": [], "changed": [], "breaking": [],
                "error": str(e)}
    finally:
        # Clean up temp dirs
        if tmp_base:
            shutil.rmtree(tmp_base, ignore_errors=True)
        if tmp_curr:
            shutil.rmtree(tmp_curr, ignore_errors=True)

    added = sorted(curr_apis - base_apis)
    removed = sorted(base_apis - curr_apis)
    changed = []
    breaking = []

    # Detect breaking changes: removed public members
    for api in removed:
        if api.startswith("type:") or api.startswith("method:"):
            breaking.append(f"Removed public {api} (breaking)")
        elif api.startswith("prop:"):
            breaking.append(f"Removed public property {api} (breaking)")

    # Detect signature changes (same name, different params)
    removed_methods = {m for m in removed if m.startswith("method:")}
    added_methods = {m for m in added if m.startswith("method:")}
    for rm in removed_methods:
        name = rm.split("(")[0]
        for am in added_methods:
            if am.startswith(name):
                changed.append(f"{rm} -> {am}")

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "breaking": breaking,
        "error": None,
    }
