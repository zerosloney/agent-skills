#!/usr/bin/env python3
"""
LLM Wiki Manager 技能合规验证

检查项:
  1. SKILL.md 存在且含 name/version/description
  2. scripts/ 目录结构完整
  3. 所有脚本可正常 import（无语法/依赖错误）
  4. init.py 包含必要 import

用法:
  python scripts/validate.py
"""

import sys
import ast
import importlib.util
from pathlib import Path


def _skill_root() -> Path:
    return Path(__file__).parent.parent


def _scripts_dir() -> Path:
    return Path(__file__).parent


def check_skill_md() -> list[str]:
    errors = []
    root = _skill_root()
    md = root / "SKILL.md"
    if not md.exists():
        errors.append("SKILL.md 不存在")
        return errors

    content = md.read_text("utf-8", errors="replace")
    for field in ("name:", "version:", "description:"):
        if field not in content:
            errors.append(f"SKILL.md 缺少 {field!r} 字段")
    return errors


def check_init_imports() -> list[str]:
    errors = []
    init_file = _scripts_dir() / "init.py"
    if not init_file.exists():
        errors.append("init.py 不存在")
        return errors

    try:
        src = init_file.read_text("utf-8", errors="replace")
        tree = ast.parse(src)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        if "os" not in imports:
            errors.append("init.py 缺少 import os")
    except SyntaxError as e:
        errors.append(f"init.py 语法错误: {e}")
    return errors


def check_scripts_importable() -> list[str]:
    errors = []
    scripts = ["fetch", "search", "lint"]
    for name in scripts:
        path = _scripts_dir() / f"{name}.py"
        if not path.exists():
            errors.append(f"{name}.py 不存在")
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            try:
                importlib.util.module_from_spec(spec)
                spec.loader.exec_module(importlib.util.module_from_spec(spec))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}.py 导入失败: {e}")
    return errors


def check_directory_structure() -> list[str]:
    errors = []
    root = _skill_root()
    required = ["scripts", "SKILL.md"]
    for name in required:
        if not (root / name).exists():
            errors.append(f"缺少必要目录/文件: {name}")
    return errors


def main() -> None:
    all_errors: list[str] = []
    checks = [
        ("SKILL.md 合规", check_skill_md),
        ("目录结构", check_directory_structure),
        ("init.py 依赖", check_init_imports),
        ("脚本可导入", check_scripts_importable),
    ]

    for name, fn in checks:
        errs = fn()
        if errs:
            print(f"❌ {name}:")
            for e in errs:
                print(f"   - {e}")
            all_errors.extend(errs)
        else:
            print(f"✅ {name}")

    print()
    if all_errors:
        print(f"❌ 共 {len(all_errors)} 个问题")
        sys.exit(1)
    print("✅ 全部检查通过")


if __name__ == "__main__":
    main()
