"""Tests for the error/exit-code model."""
from __future__ import annotations

from audit.errors import (
    AuditError, ConfigError, ToolMissingError,
    EXIT_OK, EXIT_ERROR, EXIT_CONFIG_ERROR, EXIT_TOOL_MISSING, EXIT_INTERNAL,
)


class TestExitCodes:
    def test_constants_are_distinct(self):
        codes = {EXIT_OK, EXIT_ERROR, EXIT_CONFIG_ERROR, EXIT_TOOL_MISSING, EXIT_INTERNAL}
        assert len(codes) == 5

    def test_error_levels(self):
        assert EXIT_OK == 0
        assert EXIT_ERROR > EXIT_OK
        assert EXIT_INTERNAL > EXIT_CONFIG_ERROR


class TestAuditErrorHierarchy:
    def test_base_to_dict_has_required_fields(self):
        e = AuditError("boom", details={"k": 1}, fix="do X")
        d = e.to_dict()
        assert d["error"] == "boom"
        assert d["code"] == "AUDIT_ERROR"
        assert d["exit_code"] == EXIT_INTERNAL
        assert d["details"] == {"k": 1}
        assert d["fix"] == "do X"

    def test_subclasses_inherit_code_and_exit(self):
        assert ConfigError("x").code == "CONFIG_ERROR"
        assert ConfigError("x").exit_code == EXIT_CONFIG_ERROR
        assert ToolMissingError("x").code == "TOOL_MISSING"
        assert ToolMissingError("x").exit_code == EXIT_TOOL_MISSING

    def test_subclass_is_catchable_as_base(self):
        try:
            raise ConfigError("bad")
        except AuditError as e:
            assert e.exit_code == EXIT_CONFIG_ERROR
