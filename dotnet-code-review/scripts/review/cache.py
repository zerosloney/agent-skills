from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger('dotnet-review')

# Cache version derived from analyzer DLL hashes — invalidates cached results
# when any analyzer is rebuilt. Increment the SALT when the cache format changes
# without touching the DLLs (e.g. after a bugfix in review.py's cache consumer).
_CACHE_SALT = "v1"
_CACHE_VERSION: str | None = None


def _compute_analyzer_hash() -> str:
    """Compute a combined hash of all analyzer DLLs for cache versioning.

    Returns a hex string that changes when any analyzer is rebuilt.
    Empty string if no analyzer DLLs can be read (cache disabled).
    """
    skill_dir = Path(__file__).resolve().parent.parent
    hasher = hashlib.sha256()
    hasher.update(_CACHE_SALT.encode())
    for name in ["csharp-ast-analyzer", "csharp-semantic-analyzer", "csharp-project-analyzer"]:
        dll = skill_dir / name / "bin" / "Debug" / "net6.0" / f"{name}.dll"
        if dll.exists():
            try:
                hasher.update(dll.read_bytes())
            except OSError:
                pass
    return hasher.hexdigest()[:16]


def _cache_version() -> str:
    global _CACHE_VERSION
    if _CACHE_VERSION is None:
        _CACHE_VERSION = _compute_analyzer_hash()
    return _CACHE_VERSION


def _cache_key(filepath: str) -> str:
    """Build cache key from analyzer version + file content hash."""
    h = file_hash(filepath)
    if not h:
        return ""
    return f"{_cache_version()}_{h}"


def file_hash(filepath: str) -> str:
    """SHA-256 hash of file content (used for cache key)."""
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def load_cache(cache_dir: str, filepath: str) -> list | None:
    """Load cached analysis result for a file, if hash and version match."""
    if not cache_dir:
        return None
    key = _cache_key(filepath)
    if not key:
        return None
    cache_file = Path(cache_dir) / f"{key}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        # Double-check version embedded in the cached data (belt-and-suspenders
        # against hash collisions or manual cache edits).
        if data.get("_cv") != _cache_version():
            logger.debug("Cache version mismatch for %s, ignoring", filepath)
            return None
        return data.get("issues", [])
    except (OSError, json.JSONDecodeError):
        return None


def save_cache(cache_dir: str, filepath: str, issues: list) -> None:
    """Save analysis result to cache (keyed by analyzer version + file hash)."""
    if not cache_dir:
        return
    key = _cache_key(filepath)
    if not key:
        return
    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        cache_file = Path(cache_dir) / f"{key}.json"
        cache_file.write_text(
            json.dumps({"file": filepath, "_cv": _cache_version(), "issues": issues},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
