"""Tests for smoke_test.py — verifies the context-free post-generation checks.

Each check has a positive case (issue detected) and negative case (clean code passes).
Uses tmp_path to create temporary .cs files.
"""

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPT_DIR))

from smoke_test import check_file


# ============================================================
# 1. Placeholder detection
# ============================================================

class TestPlaceholderDetection:
    def test_placeholder_detected(self, tmp_path):
        """Code with {业务名} should fail placeholder check."""
        f = tmp_path / "Frm_Test.cs"
        f.write_text("public class Frm_{业务名} { }", encoding="utf-8")
        issues = check_file(f)
        assert any(i["check"] == "no_placeholders" and i["status"] == "FAIL" for i in issues)

    def test_gridstyle_placeholder_detected(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        f.write_text('var gs = new GridStyle("{GridStyle}");', encoding="utf-8")
        issues = check_file(f)
        assert any(i["check"] == "no_placeholders" for i in issues)

    def test_clean_code_no_placeholders(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        f.write_text("public class Frm_Test { public void M() { } }", encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)


# ============================================================
# 2. TODO / NotImplemented detection
# ============================================================

class TestTodoDetection:
    def test_todo_detected(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        f.write_text("// TODO: implement this\npublic class C { }", encoding="utf-8")
        issues = check_file(f)
        assert any(i["check"] == "no_todos" for i in issues)

    def test_notimplemented_detected(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        f.write_text("throw new NotImplementedException();", encoding="utf-8")
        issues = check_file(f)
        assert any(i["check"] == "no_todos" for i in issues)

    def test_clean_code_no_todos(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        f.write_text("public class C { public void M() { Console.WriteLine(\"ok\"); } }", encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)


# ============================================================
# 3. Partial class name consistency
# ============================================================

class TestPartialClassConsistency:
    def test_matching_name_passes(self, tmp_path):
        f = tmp_path / "Frm_Test.Designer.cs"
        f.write_text("partial class Frm_Test { }", encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)

    def test_mismatched_name_detected(self, tmp_path):
        f = tmp_path / "Frm_Test.Designer.cs"
        f.write_text("partial class Frm_WrongName { }", encoding="utf-8")
        issues = check_file(f)
        assert any(i["check"] == "partial_class_match" and i["status"] == "FAIL" for i in issues)


# ============================================================
# 4. IView style is reference-driven, not smoke-tested
# ============================================================

class TestIViewStyle:
    def test_get_property_allowed(self, tmp_path):
        """Method-style IView contracts may expose get-only input properties."""
        f = tmp_path / "IView.cs"
        f.write_text("public interface IView { string Name { get; } }", encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)

    def test_set_only_passes(self, tmp_path):
        f = tmp_path / "IView.cs"
        f.write_text("public interface IView { string Name { set; } }", encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)


# ============================================================
# ============================================================
# 6. Duplicate event subscription detection
# ============================================================

class TestDuplicateEventSubscription:
    def test_duplicate_event_detected(self, tmp_path):
        """Same event += twice in one file should fail."""
        f = tmp_path / "Frm_Test.cs"
        f.write_text(
            "gvMain.RowClick += new RowClickEventHandler(OnRowClick);\n"
            "gvMain.RowClick += new RowClickEventHandler(OnRowClick2);",
            encoding="utf-8"
        )
        issues = check_file(f)
        assert any(i["check"] == "no_duplicate_event_subscription" and i["status"] == "FAIL" for i in issues)

    def test_single_event_ok(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        f.write_text("gvMain.RowClick += new RowClickEventHandler(OnRowClick);", encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)

    def test_designer_events_not_checked(self, tmp_path):
        """Events in InitializeComponent of Designer.cs are fine (auto-generated)."""
        f = tmp_path / "Frm_Test.Designer.cs"
        f.write_text(
            "this.gvMain.RowClick += new RowClickEventHandler(...);\n"
            "this.gvMain.RowClick += new RowClickEventHandler(...);",
            encoding="utf-8"
        )
        issues = check_file(f)
        assert not any(i["check"] == "no_duplicate_event_subscription" for i in issues)


# ============================================================
# 7. GridStyle style is reference-driven, not smoke-tested
# ============================================================

class TestGridStyleStyle:
    def test_literal_gridstyle_allowed(self, tmp_path):
        """GridStyle("ASS", ...) is valid when it matches the reference form."""
        f = tmp_path / "Frm_Test.Designer.cs"
        f.write_text('this._gridStyle = new GridStyle("ASS", this, gcMain, gvMain);',
                     encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)

    def test_variable_gridstyle_ok(self, tmp_path):
        f = tmp_path / "Frm_Test.Designer.cs"
        f.write_text('this._gridStyle = new GridStyle(gridCode, this, gcMain, gvMain);',
                     encoding="utf-8")
        issues = check_file(f)
        assert not any(i["check"] == "gridstyle_hardcoded" for i in issues)

    def test_hardcoded_in_comment_ignored(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        # GridStyle in a comment line should be ignored
        f.write_text('// _gridStyle = new GridStyle("ASS", this, gcMain, gvMain);',
                     encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)


# ============================================================
# 5. Empty catch block detection
# ============================================================

class TestEmptyCatch:
    def test_empty_catch_detected(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        f.write_text("try { } catch (Exception ex) { }", encoding="utf-8")
        issues = check_file(f)
        assert any(i["check"] == "no_empty_catch" for i in issues)

    def test_catch_with_body_passes(self, tmp_path):
        f = tmp_path / "Frm_Test.cs"
        f.write_text("try { } catch (Exception ex) { logger.Error(ex); }", encoding="utf-8")
        issues = check_file(f)
        assert all(i["status"] == "PASS" for i in issues)
