from __future__ import annotations

# Exit codes this CLI can actually return:
#   0  success / no error-severity findings / threshold met
#   1  error-severity findings present, or threshold not met
#   3  configuration error (argparse rejection, bad input)
#   5  internal error (unhandled AuditError)
#
# Note: missing eslint/tsc/npm does NOT exit non-zero — those tiers degrade
# gracefully and emit degradation_notices. EXIT_TOOL_MISSING is retained only
# for callers that construct AuditError subclasses manually.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG_ERROR = 3
EXIT_TOOL_MISSING = 4   # reserved — not returned by the built-in scan path
EXIT_INTERNAL = 5


class AuditError(Exception):
    """Base exception for frontend-audit errors."""

    code: str = "AUDIT_ERROR"
    exit_code: int = EXIT_INTERNAL

    def __init__(self, message: str, details: dict | None = None, fix: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.fix = fix

    def to_dict(self) -> dict:
        result = {"error": self.message, "code": self.code, "exit_code": self.exit_code}
        if self.details:
            result["details"] = self.details
        if self.fix:
            result["fix"] = self.fix
        return result


class ConfigError(AuditError):
    code = "CONFIG_ERROR"
    exit_code = EXIT_CONFIG_ERROR


class ToolMissingError(AuditError):
    code = "TOOL_MISSING"
    exit_code = EXIT_TOOL_MISSING
