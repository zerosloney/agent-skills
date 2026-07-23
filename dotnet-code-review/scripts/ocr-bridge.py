#!/usr/bin/env python3
"""
OCR Bridge — 自动桥接 open-code-review 与 dotnet-code-review

用法:
  python ocr-bridge.py                       # 自动检测项目
  python ocr-bridge.py --target /path        # 指定项目目录
  python ocr-bridge.py --diff HEAD           # 审查未提交变更
  python ocr-bridge.py --from main --to HEAD # 审查分支差异
  python ocr-bridge.py --commit <hash>       # 审查指定提交
  python ocr-bridge.py --preview             # 预览（不运行分析）

 工作流:
  1. 运行 `ocr review --preview` 获取变更文件
  2. 解析 OCR 输出，提取 .cs/.csproj/.sln 文件
  3. 调用 review.py 分析提取的文件
  4. 合并 OCR 的规则匹配 + dotnet-code-review 的分析结果
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Add scripts/ to path so we can import review.py
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from review import run_review, format_json, format_markdown  # noqa: E402


# ============================================================
# OCR Integration
# ============================================================

def ocr_available() -> bool:
    """Check if `ocr` CLI is available."""
    try:
        result = subprocess.run(
            ["ocr", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_ocr_preview(target: str, diff_mode: str = "workspace", from_ref: str = "HEAD",
                    to_ref: str = "", commit: str = "") -> dict:
    """Run `ocr review --preview` and parse output.

    Returns dict with:
        - files: list of file changes {path, status, lines_added, lines_deleted}
        - raw: original OCR output
        - diff_mode: the diff mode used
    """
    cmd = ["ocr", "review", "--preview"]

    # Add diff parameters based on mode
    if diff_mode == "commit" and commit:
        cmd.extend(["--commit", commit])
    elif diff_mode == "range" and from_ref:
        cmd.extend(["--from", from_ref])
        if to_ref:
            cmd.extend(["--to", to_ref])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=target,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"files": [], "raw": "", "error": str(e), "diff_mode": diff_mode}

    return {
        "files": parse_ocr_output(result.stdout),
        "raw": result.stdout,
        "error": result.stderr if result.returncode != 0 else "",
        "diff_mode": diff_mode,
    }


def parse_ocr_output(output: str) -> list[dict]:
    """Parse `ocr review --preview` text output.

    Expected format:
        Will review
        [A]  src/OrderService.cs                 +48   -0
        [M]  src/PaymentService.cs               +12   -3
        Excluded from review
        ...
    """
    files = []
    in_review_section = False
    # Strip ANSI escape sequences
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)

    for line in clean.splitlines():
        if "Will review" in line:
            in_review_section = True
            continue
        if "Excluded from review" in line:
            in_review_section = False
            continue
        if not in_review_section:
            continue

        line = line.strip()
        if not line:
            continue

        # Pattern: [A]  path/to/file.cs                 +48   -0
        m = re.match(r"^\[([AMD])\]\s+(.+?)\s+[+-]\d+\s+[+-]\d+\s*$", line)
        if m:
            status = m.group(1)
            fpath = m.group(2).strip()
            count_m = re.search(r"[+-](\d+)\s+[+-](\d+)", line)
            added = int(count_m.group(1)) if count_m else 0
            deleted = int(count_m.group(2)) if count_m else 0
            files.append({
                "path": fpath,
                "status": status,
                "lines_added": added,
                "lines_deleted": deleted,
            })

    return files


def filter_csharp_files(ocr_result: dict) -> list[str]:
    """Filter OCR output to only C# files (cs, csproj, sln)."""
    extensions = {".cs", ".csproj", ".sln"}
    return [
        f["path"] for f in ocr_result.get("files", [])
        if Path(f["path"]).suffix.lower() in extensions
    ]


# ============================================================
# OCR Rule File Support
# ============================================================

def load_ocr_rules(target: str) -> dict:
    """Load OCR rule.json (project or global level).

    Returns dict with rule_content, rule_path, parsed_rules.
    """
    rule_paths = [
        Path(target) / ".opencodereview" / "rule.json",
        Path.home() / ".opencodereview" / "rule.json",
    ]

    for rp in rule_paths:
        if rp.exists():
            try:
                content = rp.read_text(encoding="utf-8")
                data = json.loads(content)
                return {
                    "rule_path": str(rp),
                    "rule_content": content,
                    "parsed_rules": data.get("rules", []),
                    "merge_system_rule": data.get("merge_system_rule", True),
                }
            except (json.JSONDecodeError, OSError) as e:
                return {
                    "rule_path": str(rp),
                    "rule_content": "",
                    "parsed_rules": [],
                    "error": f"Failed to parse {rp}: {e}",
                }

    return {
        "rule_path": "",
        "rule_content": "",
        "parsed_rules": [],
    }


def convert_ocr_rules_to_custom(ocr_rules: list[dict]) -> list[dict]:
    """Convert OCR rule format to our custom rule format.

    OCR rule format:
        {"path": "**/*.cs", "rule": "LLM prompt"}

    Our custom rule format:
        {"id": "OCR001", "pattern": "...", "severity": "warning", ...}

    Note: OCR rules are LLM prompts, not regex patterns.
    This function extracts keywords/patterns from the LLM prompt
    for heuristic matching.
    """
    custom_rules = []
    for i, ocr_rule in enumerate(ocr_rules, 1):
        path_pattern = ocr_rule.get("path", "**/*.cs")
        rule_text = ocr_rule.get("rule", "")

        # Extract simple keywords from LLM prompt for heuristic matching
        # This is a best-effort conversion; OCR rules are designed for LLM consumption
        keywords = extract_keywords_from_prompt(rule_text)

        if keywords:
            # Convert keywords to a simple regex pattern
            pattern = r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b"
            custom_rules.append({
                "id": f"OCR{i:03d}",
                "name": f"ocr-rule-{i}",
                "severity": "info",
                "category": "best-practice",
                "pattern": pattern,
                "message": rule_text[:200],
                "suggestion": "See OCR rule for details",
                "file_patterns": [path_pattern],
                "source": "ocr",
            })

    return custom_rules


def extract_keywords_from_prompt(prompt: str) -> list[str]:
    """Extract keywords from an LLM prompt for heuristic matching."""
    # Common patterns to look for in C# code review prompts
    patterns = [
        r"\b(?:BinaryFormatter|WebClient|HttpContext\.Current)\b",
        r"\b(?:async void|Task\.Result|Task\.Wait)\b",
        r"\b(?:catch\s*\(\s*Exception)\b",
        r"\b(?:Console\.WriteLine|Thread\.Sleep)\b",
        r"\b(?:new\s+HttpClient)\b",
    ]

    keywords = []
    for pattern in patterns:
        matches = re.findall(pattern, prompt)
        for m in matches:
            if isinstance(m, str) and m not in keywords:
                keywords.append(m)

    return keywords[:5]  # Limit to top 5 keywords


# ============================================================
# Combined Analysis
# ============================================================

def run_combined_analysis(
    target: str,
    diff_mode: str = "workspace",
    from_ref: str = "HEAD",
    to_ref: str = "",
    commit: str = "",
    ocr_files: list[str] = None,
    format: str = "json",
) -> dict:
    """Run combined OCR + dotnet-code-review analysis."""

    # Step 1: OCR preview (if available)
    ocr_result = None
    if ocr_available() and not ocr_files:
        ocr_result = run_ocr_preview(target, diff_mode, from_ref, to_ref, commit)
        ocr_files = filter_csharp_files(ocr_result)
    elif not ocr_files:
        ocr_files = []

    # Step 2: Load OCR rules
    ocr_rules_info = load_ocr_rules(target)

    # Step 3: Run dotnet-code-review on OCR files or full project
    args = _build_namespace(target, ocr_files)
    review_result = run_review(args)

    # Step 4: Merge results
    combined = {
        "ocr_preview": ocr_result,
        "ocr_rules": ocr_rules_info,
        "review": review_result,
    }

    return combined


def _build_namespace(target: str, files: list[str]) -> "argparse.Namespace":
    """Build Namespace for run_review."""
    import argparse
    return argparse.Namespace(
        target=target if not files else None,
        diff=None,
        files=files if files else None,
        all=None,
        format="json",
        preview=False,
        verbose=False,
    )


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        prog="ocr-bridge",
        description="OCR + dotnet-code-review 桥接工具",
    )
    parser.add_argument("--target", "-t", default=os.getcwd(),
                        help="Target directory (default: current directory)")
    parser.add_argument("--diff", "-d", choices=["workspace", "range", "commit"],
                        default="workspace", help="Diff mode")
    parser.add_argument("--from", dest="from_ref", default="HEAD",
                        help="Base ref for range mode")
    parser.add_argument("--to", dest="to_ref", default="",
                        help="Target ref for range mode")
    parser.add_argument("--commit", dest="commit_hash", default="",
                        help="Commit hash for commit mode")
    parser.add_argument("--preview", action="store_true",
                        help="Preview mode (OCR + file list, no analysis)")
    parser.add_argument("--format", choices=["json", "markdown"], default="json",
                        help="Output format")
    parser.add_argument("--skip-ocr", action="store_true",
                        help="Skip OCR preview, use dotnet-code-review only")
    parser.add_argument("--files", nargs="+",
                        help="Specific files to analyze (skip OCR)")

    args = parser.parse_args()
    target = args.target

    # ── Check OCR availability ──
    if not args.skip_ocr and not ocr_available():
        print("⚠️  ocr CLI not available. Falling back to dotnet-code-review only.",
              file=sys.stderr)
        args.skip_ocr = True

    # ── Preview mode ──
    if args.preview:
        result = {"mode": "preview", "target": target}
        if not args.skip_ocr:
            ocr_result = run_ocr_preview(target, args.diff, args.from_ref, args.to_ref, args.commit_hash)
            result["ocr_files"] = ocr_result.get("files", [])
            result["csharp_files"] = filter_csharp_files(ocr_result)
        else:
            from review import discover_files
            result["csharp_files"] = discover_files(target, [".cs"])
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # ── Run combined analysis ──
    if args.skip_ocr:
        # Run only dotnet-code-review
        review_args = argparse.Namespace(
            target=target, diff=None, files=args.files, all=None,
            format=args.format, preview=False, verbose=False,
        )
        result = run_review(review_args)
        result["bridge_mode"] = "dotnet-only"
    else:
        # Run combined OCR + dotnet-code-review
        combined = run_combined_analysis(
            target=target,
            diff_mode=args.diff,
            from_ref=args.from_ref,
            to_ref=args.to_ref,
            commit=args.commit_hash,
            ocr_files=args.files,
            format=args.format,
        )
        result = combined["review"]
        result["bridge_mode"] = "combined"
        result["ocr_preview"] = {
            "files": combined["ocr_preview"].get("files", []) if combined.get("ocr_preview") else [],
            "diff_mode": combined["ocr_preview"].get("diff_mode", "") if combined.get("ocr_preview") else "",
        }
        result["ocr_rules_loaded"] = bool(combined.get("ocr_rules", {}).get("parsed_rules"))

    # ── Output ──
    if args.format == "markdown":
        print(format_markdown(result))
    else:
        print(format_json(result))

    # ── Exit code ──
    by_sev = result.get("by_severity", {})
    if by_sev.get("error", 0) > 0:
        sys.exit(1)
    elif by_sev.get("warning", 0) > 0:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()