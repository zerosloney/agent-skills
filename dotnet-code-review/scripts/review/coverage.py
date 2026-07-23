from __future__ import annotations
import logging
from pathlib import Path
from .models import CodeIssue

logger = logging.getLogger('dotnet-review')



# ============================================================
# Code Coverage (optional, Cobertura XML from coverlet/dotnet-coverage)
# ============================================================

def load_coverage(coverage_path: str) -> dict:
    """Load Cobertura XML coverage report.

    Supports:
    - coverlet `coverage.cobertura.xml`
    - ReportGenerator `Cobertura.xml`

    Returns:
        {
            "files": {
                "relative/path/File.cs": {
                    "line_rate": 0.85,
                    "lines": {1: True/False, 2: True/False, ...}
                },
                ...
            },
            "summary": {"line_rate": 0.85, "lines_covered": 100, "lines_total": 120},
            "format": "cobertura"
        }

    Returns empty dict on failure.
    """
    if not coverage_path:
        return {}
    path = Path(coverage_path)
    if not path.exists():
        return {}

    try:
        import xml.etree.ElementTree as ET
    except ImportError:
        return {}

    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return {}

    root = tree.getroot()
    if root.tag != "coverage":
        return {}

    result = {"files": {}, "summary": {}, "format": "cobertura"}

    # Overall summary
    line_rate = float(root.attrib.get("line-rate", "0"))
    lines_covered = int(root.attrib.get("lines-covered", "0"))
    lines_total = int(root.attrib.get("lines-valid", "0"))
    result["summary"] = {
        "line_rate": round(line_rate, 4),
        "lines_covered": lines_covered,
        "lines_total": lines_total,
    }

    # Per-file data
    for cls in root.findall(".//class"):
        filename = cls.attrib.get("filename", "")
        if not filename:
            continue

        # Normalize filename (Cobertura may use backslashes or forward slashes)
        filename_norm = filename.replace("\\", "/").lstrip("./")
        file_line_rate = float(cls.attrib.get("line-rate", "0"))

        file_data = {"line_rate": round(file_line_rate, 4), "lines": {}}
        for line in cls.findall(".//line"):
            try:
                line_num = int(line.attrib.get("number", "0"))
                hits = int(line.attrib.get("hits", "0"))
                file_data["lines"][line_num] = hits > 0
            except (ValueError, TypeError):
                continue

        result["files"][filename_norm] = file_data

    return result



def analyze_coverage(
    cs_files: list[str],
    coverage: dict,
    threshold: float = 0.6,
) -> list[CodeIssue]:
    """Detect methods/files with low test coverage.

    Args:
        cs_files: List of .cs file paths being reviewed
        coverage: Output from load_coverage()
        threshold: Line coverage below this triggers a warning (default 0.6 = 60%)

    Returns:
        List of CodeIssue for files below threshold.
    """
    if not coverage or not coverage.get("files"):
        return []

    issues = []
    covered_files = coverage["files"]

    for cs_file in cs_files:
        # Try to match file - normalize paths
        norm = cs_file.replace("\\", "/").lstrip("./")
        # Cobertura filenames may not include full path - match by suffix
        file_data = covered_files.get(norm)
        if not file_data:
            # Try matching by basename
            base = Path(cs_file).name
            for cov_path, cov_data in covered_files.items():
                if cov_path.endswith(base) or Path(cov_path).name == base:
                    file_data = cov_data
                    break
        if not file_data:
            # No coverage data for this file → untested
            try:
                content = Path(cs_file).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # Count non-blank, non-comment lines
            code_lines = sum(
                1 for ln in content.split("\n")
                if ln.strip() and not ln.strip().startswith(("//", "/*", "*", "///"))
            )
            if code_lines >= 10:  # Only flag files with substantial code
                issues.append(CodeIssue(
                    file=cs_file, line=1, column=1,
                    severity="warning",
                    category="test",
                    rule="COVERAGE_MISSING",
                    message=f"No coverage data for {Path(cs_file).name} ({code_lines} lines)",
                    suggestion="Add unit tests to cover this file. Coverage report may be incomplete.",
                ))
            continue

        line_rate = file_data.get("line_rate", 1.0)
        if line_rate < threshold:
            try:
                content = Path(cs_file).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            lines_list = content.split("\n")
            # Find first untested line as representative location
            line_num = 1
            for ln, covered in sorted(file_data.get("lines", {}).items()):
                if not covered and 1 <= ln <= len(lines_list):
                    line_num = ln
                    break

            issues.append(CodeIssue(
                file=cs_file, line=line_num, column=1,
                severity="warning" if line_rate >= 0.3 else "error",
                category="test",
                rule="COVERAGE_LOW",
                message=f"Low test coverage in {Path(cs_file).name}: {line_rate * 100:.1f}% (threshold {threshold * 100:.0f}%)",
                suggestion=f"Add tests to cover untested code. Coverage is below {threshold * 100:.0f}% threshold.",
            ))

    return issues
