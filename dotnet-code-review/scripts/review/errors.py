from __future__ import annotations
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger('dotnet-review')

EXIT_OK = 0             # Success / no issues
EXIT_ERROR = 1          # Errors found in code
EXIT_WARNING = 2        # Warnings found in code
EXIT_CONFIG_ERROR = 3   # Configuration error
EXIT_TOOL_MISSING = 4   # Required tool not available
EXIT_INTERNAL = 5       # Internal error
EXIT_USER_ERROR = 6     # User input error
EXIT_INVALID_INPUT = 7  # Invalid input (not a valid user error but malformed)



class ReviewError(Exception):
    """Base exception for review errors."""
    code: str = "REVIEW_ERROR"
    exit_code: int = EXIT_INTERNAL

    def __init__(self, message: str, details: dict = None, fix: str = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.fix = fix

    def to_dict(self) -> dict:
        """Convert to structured error dict."""
        result = {
            "error": self.message,
            "code": self.code,
            "exit_code": self.exit_code,
        }
        if self.details:
            result["details"] = self.details
        if self.fix:
            result["fix"] = self.fix
        return result



class ConfigError(ReviewError):
    code = "CONFIG_ERROR"
    exit_code = EXIT_CONFIG_ERROR



class ToolMissingError(ReviewError):
    code = "TOOL_MISSING"
    exit_code = EXIT_TOOL_MISSING



class UserInputError(ReviewError):
    code = "USER_INPUT_ERROR"
    exit_code = EXIT_USER_ERROR



def safe_read_file(filepath: str) -> str:
    """Safely read a file with encoding fallback.

    Tries UTF-8 first, then UTF-8-BOM, GBK (common on Windows), and latin-1
    (never fails for any byte sequence). Raises ``ReviewError`` only if every
    encoding fails (e.g. permission denied).
    """
    encodings = ["utf-8", "utf-8-sig", "gbk", "latin-1"]
    last_error = None
    for encoding in encodings:
        try:
            return Path(filepath).read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError) as e:
            last_error = e
            continue
    raise ReviewError(
        f"Failed to read file: {filepath}",
        details={"file": filepath, "last_error": str(last_error)},
        fix="Check file encoding and permissions",
    )



def run_with_retry(func, max_retries: int = 2, retry_delay: float = 1.0, *args, **kwargs):
    """Run a function with retry logic for transient failures."""
    import time as _time
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except (subprocess.TimeoutExpired, OSError) as e:
            last_error = e
            if attempt < max_retries:
                logger.debug(f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}")
                _time.sleep(retry_delay)
            else:
                break
    raise ReviewError(
        f"Function {func.__name__} failed after {max_retries + 1} attempts",
        details={"last_error": str(last_error)},
        fix="Check system resources and try again",
    )
