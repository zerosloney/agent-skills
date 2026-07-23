#!/usr/bin/env python3
"""
项目指纹扫描脚本 — Step 0b 替代方案。

将 project-fingerprint.md 的 glance/deep 扫描逻辑封装为本脚本，
agent 直接跑脚本拿固定格式的指纹卡，不需要读复杂的决策树。

用法:
    # 默认 glance 档（6 个查询，全部过滤注释）
    python scripts/scan_project.py --root "C:/Project/CSS.WHXL.Extend"

    # 强制 deep 档（全量扫描）
    python scripts/scan_project.py --root "C:/Project/CSS.WHXL.Extend" --deep

    # 指定目标子目录（glance 档子目录 GridStyle 代号检测）
    python scripts/scan_project.py --root "C:/Project/CSS.WHXL.Extend" --subdir "ITPManagement"

输出:
    - stdout: 项目指纹卡（markdown 格式）
    - exit 0: 纯一（可直接进 Step 1）
    - exit 1: 需要用户决策（异质性）
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


# ── Comment filter (fixed: covers string-embedded comments too) ──────────────

def filter_comments(lines: list[str]) -> list[str]:
    """
    Filter out C# comment lines from raw file content.

    Removes:
      - Single-line comments:     // ... (line starts with whitespace* //)
      - Block comment continuations:  * ... (inside /* */)
      - Triple-slash doc comments: /// ...
      - String-embedded comments:  code /* comment */ code
      - Line-embedded // comments:  code // comment

    Does NOT remove: code inside string literals ("..." or '...').
    """
    result = []
    # Remove block-comment spans
    clean = re.sub(r'/\*.*?\*/', '', '\n'.join(lines), flags=re.DOTALL)
    for raw_line in clean.split('\n'):
        # Strip line-embedded // comments (but not string literals)
        # Strategy: split on '//', but only if outside a string
        stripped = _strip_line_comment(raw_line)
        if stripped.strip():
            result.append(stripped)
    return result


def _strip_line_comment(line: str) -> str:
    """Strip // comment suffix from a line, respecting string literals."""
    result = []
    in_string = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == '"' and (i == 0 or line[i - 1] != '\\'):
            in_string = not in_string
            result.append(c)
        elif c == '/' and i + 1 < len(line) and line[i + 1] == '/' and not in_string:
            break  # rest of line is a comment
        else:
            result.append(c)
        i += 1
    return ''.join(result).rstrip()


def read_cs_files(root: Path, extensions=None):
    """Recursively read all .cs files under root (optionally filtered by extensions)."""
    if extensions is None:
        extensions = ['.cs']
    files = []
    for ext in extensions:
        files.extend(root.rglob(f'*{ext}'))
    return files


# ── Scan commands (rg preferred, Select-String fallback) ────────────────────

def _has_rg() -> bool:
    try:
        subprocess.run(['rg', '--version'], capture_output=True, check=False)
        return True
    except FileNotFoundError:
        return False


def _rg(query: str, root: Path, pattern_hint: Optional[str] = None) -> list[str]:
    """Run ripgrep and return matching lines."""
    cmd = ['rg', '--no-line-number', query, str(root)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                               errors='replace')
        if result.returncode not in (0, 1):
            return []
        return [ln for ln in result.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def _select_string(query: str, root: Path) -> list[str]:
    """Fallback: use PowerShell Select-String on Windows."""
    import subprocess
    ps = f'Get-ChildItem -Recurse -Filter *.cs "{root}" | Select-String -Pattern "{query}" | ForEach-Object {{ $_.Line }}'
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace')
        return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def _file_paths_from_matches(lines: list[str]) -> set[str]:
    """Extract unique file paths from ripgrep output (path:line:content format)."""
    paths = set()
    for ln in lines:
        parts = ln.split(':')
        if len(parts) >= 2:
            path = parts[0]
            if path.endswith('.cs'):
                paths.add(path)
    return paths


def scan_glance(root: Path, subdir: Optional[str] = None) -> dict:
    """
    Run glance scan (6 queries, all filtered by comment strip).
    Returns a dict with scan results.
    """
    target_root = root / subdir if subdir else root
    use_rg = _has_rg()

    def grep(query, r=root):
        lines = _rg(query, r) if use_rg else _select_string(query, r)
        return lines

    def grep_sub(query, r=target_root):
        lines = _rg(query, r) if use_rg else _select_string(query, r)
        return lines

    # Filter helper (Python-side, applies after grep)
    def filter_cs_comment_lines(raw_lines):
        return filter_comments(raw_lines)

    # 1. Form base class family
    fbase_paths = _file_paths_from_matches(filter_cs_comment_lines(grep(r':\s*frmBase\b')))
    fgen_paths = _file_paths_from_matches(filter_cs_comment_lines(grep(r':\s*frm_Base<')))
    total_base = len(fbase_paths | fgen_paths)
    dominant_base = 'frmBase' if len(fbase_paths) >= len(fgen_paths) else 'frm_Base<T>'
    base_pct = max(len(fbase_paths), len(fgen_paths)) / total_base * 100 if total_base else 0

    # 2. Data access
    fsql_paths = _file_paths_from_matches(filter_cs_comment_lines(grep(r'SqlOperate\s+_so\s*=')))
    form_paths = _file_paths_from_matches(filter_cs_comment_lines(grep(r'DbHelp\.Query<')))
    total_dal = len(fsql_paths | form_paths)
    dominant_dal = 'SqlOperate' if len(fsql_paths) >= len(form_paths) else 'DbHelp.Query'
    dal_pct = max(len(fsql_paths), len(form_paths)) / total_dal * 100 if total_dal else 0

    # 3. GridStyle codes (subdir-aware)
    grid_raw = grep_sub(r'new GridStyle\(')
    grid_codes = set()
    for ln in filter_cs_comment_lines(grid_raw):
        m = re.search(r'new GridStyle\s*\(\s*"([A-Za-z]+)"', ln)
        if m:
            grid_codes.add(m.group(1))
    grid_str = ', '.join(sorted(grid_codes)) if grid_codes else '—'

    # 4. Collection layer
    coll_paths = _file_paths_from_matches(filter_cs_comment_lines(grep(r'class\s+Collection_')))
    has_coll = len(coll_paths) > 0

    # 5. DAL layer completeness
    dal_files = [f for f in read_cs_files(root) if re.search(r'DAL[A-Z]', f.name, re.I)]
    ser_files = [f for f in read_cs_files(root) if f.name.endswith('Ser.cs')]
    dal_count = len(dal_files)
    ser_count = len(ser_files)
    dal_ratio = round(dal_count / ser_count, 2) if ser_count > 0 else 0

    # 6. Connection name (filtered)
    conn_raw = grep(r'varlist\.[A-Za-z]+(Conn|DBHelp)')
    conn_map = defaultdict(int)
    for ln in filter_cs_comment_lines(conn_raw):
        m = re.search(r'(varlist\.[A-Za-z]+(?:Conn|DBHelp))', ln)
        if m:
            conn_map[m.group(1)] += 1
    conn_sorted = sorted(conn_map.items(), key=lambda x: -x[1])
    conn_top = conn_sorted[0][0] if conn_sorted else '—'

    # Determine heterogeneity level
    flags = []
    if base_pct < 95:
        flags.append('🟡')
    if dal_pct < 95:
        flags.append('🟡')
    if len(grid_codes) >= 2:
        flags.append('🔴')

    if base_pct < 75 or dal_pct < 75:
        heter = '🔴'
    elif '🔴' in flags:
        heter = '🔴'
    elif '🟡' in flags:
        heter = '🟡'
    else:
        heter = '🟢'

    # Should auto-upgrade to deep?
    upgrade = heter in ('🟡', '🔴')

    return {
        'root': str(root),
        'subdir': subdir,
        'total_cs': len(read_cs_files(root)),
        'fbase': len(fbase_paths),
        'fgen': len(fgen_paths),
        'dominant_base': dominant_base,
        'base_pct': round(base_pct, 1),
        'fsql': len(fsql_paths),
        'form': len(form_paths),
        'dominant_dal': dominant_dal,
        'dal_pct': round(dal_pct, 1),
        'grid_codes': grid_codes,
        'grid_str': grid_str,
        'has_coll': has_coll,
        'coll_count': len(coll_paths),
        'dal_count': dal_count,
        'ser_count': ser_count,
        'dal_ratio': dal_ratio,
        'conn_top': conn_top,
        'conn_map': dict(conn_sorted[:5]),
        'heter': heter,
        'upgrade': upgrade,
    }


def scan_deep(root: Path, subdir: Optional[str] = None) -> dict:
    """
    Run deep scan = glance + namespace breakdown + class prefix detection +
    using-statement analysis + directory structure + git history.

    Deep 是 glance 的超集：先跑 glance，再附加全量探测。
    """
    # 先跑 glance 拿基础数据
    result = scan_glance(root, subdir)
    use_rg = _has_rg()

    def grep(query, r=root):
        lines = _rg(query, r) if use_rg else _select_string(query, r)
        return filter_comments(lines)

    # ── Deep 1: 命名空间分布 ──
    ns_raw = grep(r'^namespace\s+')
    ns_map = defaultdict(int)
    for ln in ns_raw:
        m = re.match(r'namespace\s+(\S+)', ln)
        if m:
            ns_map[m.group(1)] += 1
    result['namespaces'] = dict(sorted(ns_map.items(), key=lambda x: -x[1])[:10])

    # ── Deep 2: 类名前缀分布 ──
    prefix_raw = grep(r'class\s+([A-Z][A-Za-z0-9_]*)\s*[:\s<]')
    prefix_map = defaultdict(int)
    for ln in prefix_raw:
        m = re.match(r'class\s+([A-Z][A-Za-z0-9_]*)', ln)
        if m:
            name = m.group(1)
            # 提取前缀（DAL_, Frm_, Dlg_, UC_ 等）
            prefix = re.match(r'([A-Z][A-Za-z0-9_]*?)(?=[A-Z][a-z]|$)', name)
            if prefix:
                prefix_map[prefix.group(1)] += 1
    result['class_prefixes'] = dict(sorted(prefix_map.items(), key=lambda x: -x[1])[:15])

    # ── Deep 3: using 命名空间引用 ──
    using_raw = grep(r'^using\s+')
    using_map = defaultdict(int)
    for ln in using_raw:
        m = re.match(r'using\s+(\S+)', ln)
        if m:
            ns = m.group(1)
            # 只统计项目相关命名空间（跳过 System/微软标准库）
            if not ns.startswith('System') and not ns.startswith('Microsoft') and not ns.startswith('DevExpress'):
                using_map[ns] += 1
    result['using_refs'] = dict(sorted(using_map.items(), key=lambda x: -x[1])[:10])

    # ── Deep 4: 目录结构（DAL/BLL/Common/UI 分层） ──
    dirs = [d.name for d in root.rglob('*') if d.is_dir() and d.name in ('DAL', 'BLL', 'BIZ', 'Common', 'UI')]
    result['layer_dirs'] = sorted(set(dirs))

    # ── Deep 5: git 历史演化（最近 6 个月新增文件命名风格） ──
    try:
        git_result = subprocess.run(
            ['git', 'log', '--since=6 months ago', '--pretty=format:', '--name-only',
             '--diff-filter=A', '--', '*.cs'],
            cwd=str(root), capture_output=True, text=True, timeout=30
        )
        if git_result.returncode == 0:
            new_files = [ln.strip() for ln in git_result.stdout.splitlines() if ln.strip().endswith('.cs')]
            result['git_new_files'] = len(new_files)
            # 新增文件的类名前缀
            new_prefixes = defaultdict(int)
            for f in new_files:
                basename = Path(f).stem
                prefix = re.match(r'([A-Z][A-Za-z0-9_]*)', basename)
                if prefix:
                    new_prefixes[prefix.group(1)] += 1
            result['git_new_prefixes'] = dict(sorted(new_prefixes.items(), key=lambda x: -x[1])[:10])
        else:
            result['git_new_files'] = 0
            result['git_new_prefixes'] = {}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        result['git_new_files'] = 0
        result['git_new_prefixes'] = {}

    result['deep'] = True
    return result


def output_fingerprint_card(result: dict) -> str:
    """Render a fingerprint card in markdown format."""
    r = result
    lines = [
        f"## 项目指纹卡 (Step 0b 输出)",
        "",
        f"| 字段 | 值 |",
        f"|------|----|",
        f"| 项目根 | `{r['root']}` |",
        f"| 扫描子目录 | `{r['subdir'] or '全项目'}` |",
        f"| 扫描 .cs 文件数 | {r['total_cs']} |",
        f"|",
        f"| 维度 | 主导 | 占比 | 异类 |",
        f"|------|------|------|------|",
        f"| 窗体基类 | `{r['dominant_base']}` | {r['base_pct']}% | "
        f"{'frm_Base<T>' if r['dominant_base']=='frmBase' and r['fgen']>0 else 'frmBase' if r['dominant_base']=='frm_Base<T>' and r['fbase']>0 else '—'} |",
        f"| 数据访问 | `{r['dominant_dal']}` | {r['dal_pct']}% | "
        f"{'DbHelp.Query' if r['dominant_dal']=='SqlOperate' and r['form']>0 else 'SqlOperate' if r['dominant_dal']=='DbHelp.Query' and r['fsql']>0 else '—'} |",
        f"| GridStyle 代号 | `{r['grid_str']}` | — | {'多代号⚠️' if len(r['grid_codes'])>=2 else '—'} |",
        f"| Collection 层 | {'有' if r['has_coll'] else '无'} | — | — |",
        f"| DAL 层完整性 | DAL={r['dal_count']} / Ser={r['ser_count']} = {r['dal_ratio']} | — | {'无独立DAL层⚠️' if r['dal_ratio']<0.1 else '—'} |",
        f"| 连接名 (top1) | `{r['conn_top']}` | — | — |",
        f"|",
        f"**异质性等级**: {r['heter']}  {'← 直接进 Step 1' if r['heter']=='🟢' else '← 需用户决策' if r['heter']=='🟡' else '← 必须用户二选一'}",
        "",
    ]

    # Upgrade advice
    if r['heter'] == '🟡':
        lines.append("> ⚠️ 自动升级到 deep（全量扫描）: 基类或数据访问存在少数异类，建议全量扫描确认。")
    elif r['heter'] == '🔴':
        lines.append("> 🔴 强制用户二选一（路径 a: 跟随主导 / 路径 b: 跟随最近 / 路径 c: 新开分支）")
    else:
        lines.append("> ✅ 直接进 Step 1")

    # DAL decision hint
    if r['dal_ratio'] < 0.1:
        lines.append("> ℹ️ DAL/Ser < 0.1 → **无独立 DAL 层**，Step 4 不生成 `*DAL.cs`，数据访问内联到 Ser。")

    # Deep scan additional info
    if r.get('deep'):
        lines.append("")
        lines.append("### Deep 扫描补充")
        lines.append("")
        if r.get('namespaces'):
            top_ns = list(r['namespaces'].items())[:5]
            lines.append(f"| 命名空间 (top5) | {' | '.join(f'`{k}` ({v})' for k, v in top_ns)} |")
        if r.get('class_prefixes'):
            top_pf = list(r['class_prefixes'].items())[:5]
            lines.append(f"| 类名前缀 (top5) | {' | '.join(f'{k} ({v})' for k, v in top_pf)} |")
        if r.get('using_refs'):
            top_using = list(r['using_refs'].items())[:5]
            lines.append(f"| using 引用 (top5) | {' | '.join(f'`{k}` ({v})' for k, v in top_using)} |")
        if r.get('layer_dirs'):
            lines.append(f"| 分层目录 | {', '.join(r['layer_dirs']) if r['layer_dirs'] else '无' } |")
        if r.get('git_new_files'):
            lines.append(f"| 近6月新增 .cs | {r['git_new_files']} 个 |")
        if r.get('git_new_prefixes'):
            top_git = list(r['git_new_prefixes'].items())[:5]
            lines.append(f"| 新增前缀 (top5) | {' | '.join(f'{k} ({v})' for k, v in top_git)} |")

    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="项目指纹扫描脚本（Step 0b glance/deep 两档封装）"
    )
    parser.add_argument('--root', '-r', required=True,
                        help='项目根目录（.sln 或 .csproj 所在）')
    parser.add_argument('--subdir', '-s',
                        help='目标子目录（如 ITPManagement），用于子目录级 GridStyle 代号检测')
    parser.add_argument('--deep', action='store_true',
                        help='强制 deep 档（全量扫描，替代 glance 默认行为）')
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        return 1

    # Choose scan mode
    if args.deep:
        result = scan_deep(root, args.subdir)
    else:
        result = scan_glance(root, args.subdir)

    card = output_fingerprint_card(result)
    print(card)

    return 0 if result['heter'] == '🟢' else 1


if __name__ == '__main__':
    sys.exit(main())
