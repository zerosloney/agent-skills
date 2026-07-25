"""AST + regex visitors that produce findings.

Two tiers, selected automatically:

1. **tree-sitter (preferred)**: when the optional ``tree_sitter`` package and
   language grammars are importable, JS/TS/TSX are parsed to a real AST and
   rules that need structural context (e.g. "argument is not a literal") are
   accurate.
2. **regex (fallback)**: a conservative pattern matcher that catches the
   same surface signals. Marked ``intentional-simple`` — it trades a few
   false negatives (e.g. spread-argument cases) for zero native deps so the
   skill runs anywhere Python does.

Each visitor returns ``list[Finding]``.
"""
from __future__ import annotations

import bisect
import logging
import re
from pathlib import Path

from .models import Finding
from .rules import get_spec

logger = logging.getLogger("frontend-audit")

# Files we consider JS/TS source for the regex tier.
_JS_TS_GLOBS = ("*.js", "*.jsx", "*.ts", "*.tsx", "*.mjs", "*.cjs", "*.vue", "*.svelte")


# ============================================================
# tree-sitter tier (preferred)
# ============================================================

_TS_PARSER = None  # (parser_js, parser_tsx)


def _try_init_tree_sitter():
    """Lazily build tree-sitter parsers. Returns (js_parser, tsx_parser) or None."""
    global _TS_PARSER
    if _TS_PARSER is not None:
        return _TS_PARSER
    try:
        import tree_sitter as ts  # type: ignore
        import tree_sitter_javascript as ts_js  # type: ignore
        import tree_sitter_typescript as ts_ts  # type: ignore

        js_lang = ts.Language(ts_js.language())
        tsx_lang = ts.Language(ts_ts.language_tsx())

        js_parser = ts.Parser(js_lang) if hasattr(ts, "Parser") else ts.Parser()
        try:
            js_parser.language = js_lang
        except Exception:
            js_parser.set_language(js_lang)

        tsx_parser = ts.Parser(tsx_lang) if hasattr(ts, "Parser") else ts.Parser()
        try:
            tsx_parser.language = tsx_lang
        except Exception:
            tsx_parser.set_language(tsx_lang)

        _TS_PARSER = (js_parser, tsx_parser)
        return _TS_PARSER
    except Exception as e:  # ImportError or grammar load failure
        logger.debug("tree-sitter unavailable, falling back to regex: %s", e)
        _TS_PARSER = False  # marker: tried and failed
        return None


def tree_sitter_available() -> bool:
    return bool(_try_init_tree_sitter())


# ============================================================
# Regex tier (always-available fallback)
# ============================================================

# Each rule contributes one or more compiled patterns. Patterns use named groups
# where useful. ``severity``/``dimension`` come from the rule spec; the pattern
# only decides *where* it fires.
#
# intentional-simple: regex cannot track data flow, so "non-literal argument"
# rules approximate by flagging the call/property whenever the suspicious sink
# is present *and* the immediate vicinity is not an obvious literal. This is
# conservative (few false positives, possible false negatives on multi-line
# expressions). Upgrade path: the tree-sitter tier replaces these with precise
# AST checks.

# SEC-REACT-001: dangerouslySetInnerHTML whose __html value is not a string literal.
_RE_DANGEROUSLY = re.compile(
    r"dangerouslySetInnerHTML\s*=\s*\{\{\s*__html\s*:\s*([^}]+?)\s*\}\}",
    re.MULTILINE,
)
# SEC-REACT-002: bare __html key in an object literal (the XSS vector when
# constructing the {__html: ...} object outside the JSX dangerouslySetInnerHTML
# form, e.g. `const obj = {__html: userInput}`). SEC-REACT-001 claims __html
# offsets it already covers; scan_text skips those, so this regex matches any
# __html: and relies on that dedup rather than a fragile lookbehind.
_RE_BARE_HTML = re.compile(r"\b__html\s*:\s*([^,}\n]+)")
# SEC-JS-001: eval / new Function with a non-literal argument.
_RE_EVAL = re.compile(
    r"\b(?:eval|Function)\s*\(\s*([^)]+?)\s*\)",
)
# SEC-JS-002: document.write
_RE_DOC_WRITE = re.compile(
    r"document\.write(?:ln)?\s*\(\s*([^)]+?)\s*\)",
)
# SEC-JS-003: .innerHTML assignment (right-hand side captured up to ; or newline).
# Greedy (not +?) so the captured expression is the full RHS — a non-greedy
# quantifier here would capture only the first character, judging "e" from
# "escapeHtml(bio)" instead of the whole call.
_RE_INNER_HTML = re.compile(
    r"\.innerHTML\s*=\s*([^;\n]+)",
)
# SEC-JS-004: window.location assignment (open redirect heuristic).
# Greedy capture of the RHS (see _RE_INNER_HTML comment for why not +?).
_RE_LOCATION_ASSIGN = re.compile(
    r"(?:window|document)\.location(?:\.href)?\s*=\s*([^;\n]+)",
)
# SEC-JS-005: postMessage call (heuristic; flagged only when called in the same
# scope as addEventListener('message') without an obvious origin check is hard
# via regex — so we surface a low-confidence finding for agent_verify).
_RE_POST_MESSAGE = re.compile(
    r"\.postMessage\s*\(",
)
# RELI-JS-002: addEventListener without a nearby removeEventListener.
_RE_ADD_EVENT = re.compile(
    r"\.addEventListener\s*\(\s*['\"](\w+)['\"]",
)
_RE_REMOVE_EVENT = re.compile(
    r"\.removeEventListener\s*\(\s*['\"](\w+)['\"]",
)
# RELI-JS-001: await inside useEffect without try/catch is hard via regex; we
# instead flag async callbacks passed to useEffect (a strong precursor signal).
_RE_ASYNC_USE_EFFECT = re.compile(
    r"useEffect\s*\(\s*async\s*(?:function\s*)?\(",
)


def _is_literal(expr: str) -> bool:
    """Crude literal detector for the regex tier.

    A string literal (quotes/backticks), a number, ``true``/``false``/``null``,
    or a template without interpolation counts as literal. Everything else
    (identifiers, member access, calls) is treated as non-literal.
    """
    expr = expr.strip()
    if not expr:
        return False
    if expr[0] in "\"'`":
        # template literal with ${...} interpolation is NOT a literal
        if expr[0] == "`" and "${" in expr:
            return False
        return True
    if re.fullmatch(r"-?\d+(\.\d+)?", expr):
        return True
    if expr in ("true", "false", "null", "undefined"):
        return True
    return False


# Known sanitization/escaping functions. When a sink's value is wrapped in one
# of these, the data-flow risk is considered mitigated at this tier and the
# finding is suppressed.
# intentional-simple: regex tier only matches a single wrapping call; nested
# or aliased sanitizers (e.g. `const s = sanitize; s(x)`) are not recognized.
# Upgrade path: the tree-sitter tier resolves call targets precisely.
_SANITIZER_RE = re.compile(
    r"^(?:[\w$]+\.)?(?:sanitize|escapeHtml|escape_html|encodeHTML|encodeURI"
    r"|escape|purge|stripTags|textContent)\s*\(",
    re.IGNORECASE,
)


def _is_sanitized(expr: str) -> bool:
    """True when ``expr`` is a call to a known sanitizer/escaper.

    Used by sink rules (SEC-REACT-001, SEC-JS-002/003) to suppress findings
    whose value has already passed through a recognized净化 point — without it,
    ``sanitize(bio)`` would still be flagged, contradicting the rule's own fix
    advice ("用 DOMPurify.sanitize() 净化").
    """
    return bool(_SANITIZER_RE.match(expr.strip()))


# Line-offset table cache (B3): scanning a 20k-line file with thousands of
# findings used to be O(n²) because each _line_of call recounted newlines from
# the start. We now build a sorted list of newline offsets once per text and
# binary-search it. Cache keyed by id(text) — safe within one scan_text call
# (the text string is alive there); evicted when the string is GC'd.
_LINE_TABLE_CACHE: dict[int, list[int]] = {}


def _line_table(text: str) -> list[int]:
    tid = id(text)
    tbl = _LINE_TABLE_CACHE.get(tid)
    if tbl is None:
        # intentional-simple: building the table is O(n) on the text length,
        # paid once per file; subsequent lookups are O(log n). Good for files
        # up to ~1M lines; beyond that consider a per-file LineIndex object.
        tbl = [i for i, c in enumerate(text) if c == "\n"]
        _LINE_TABLE_CACHE[tid] = tbl
        # bound the cache so a long-lived process scanning many files does not
        # accumulate entries forever.
        if len(_LINE_TABLE_CACHE) > 64:
            _LINE_TABLE_CACHE.clear()
    return tbl


def _line_of(text: str, offset: int) -> int:
    # number of newlines strictly before `offset`, plus 1 for 1-based lines
    return bisect.bisect_left(_line_table(text), offset) + 1


def _make_finding(rule_id: str, file: str, line: int, evidence: str) -> Finding:
    spec = get_spec(rule_id)
    return Finding(
        file=file,
        line=line,
        severity=spec.severity if spec else "warning",
        dimension=spec.dimension if spec else "best-practice",
        rule=rule_id,
        message=(spec.title if spec else rule_id),
        source="custom",
        evidence=evidence.strip()[:200],
        confidence=spec.confidence if spec else "medium",
        fix_hint=spec.fix_hint if spec else "",
        triage=spec.triage if spec else "deterministic",
    )


def scan_text(text: str, file: str) -> list[Finding]:
    """Run all regex-tier rules against a single file's text."""
    findings: list[Finding] = []

    # A sink value is "safe" at this tier if it is a literal OR already wrapped
    # in a recognized sanitizer. Sink rules share this guard so the rule's own
    # fix advice (sanitize the value) actually clears the finding.
    def _unsafe(expr: str) -> bool:
        return not _is_literal(expr) and not _is_sanitized(expr)

    # SEC-REACT-001 — record the offset of every __html it consumed so 002
    # can skip them (avoids double-reporting the same sink).
    consumed_html_offsets: set[int] = set()
    for m in _RE_DANGEROUSLY.finditer(text):
        # locate the __html key inside this match so 002 can skip it
        html_idx = m.group(0).find("__html")
        if html_idx >= 0:
            consumed_html_offsets.add(m.start() + html_idx)
        if _unsafe(m.group(1)):
            findings.append(_make_finding("SEC-REACT-001", file, _line_of(text, m.start()), m.group(0)))

    # SEC-REACT-002: bare __html key in an object literal (the XSS vector when
    # constructing {__html: ...} outside the JSX form). Skip any __html already
    # claimed by SEC-REACT-001 — fixed lookbehind can't reliably tell the two
    # apart because whitespace inside {{ __html: ... }} breaks it.
    for m in _RE_BARE_HTML.finditer(text):
        if m.start() in consumed_html_offsets:
            continue
        if _unsafe(m.group(1)):
            findings.append(_make_finding("SEC-REACT-002", file, _line_of(text, m.start()), m.group(0)))

    # SEC-JS-001 (eval / Function). Also include SEC-REACT-002 if __html appears bare.
    for m in _RE_EVAL.finditer(text):
        # `new Function` matched by the Function branch; both fine here.
        callee = "eval" if text[m.start():].startswith("eval") else "Function"
        if _unsafe(m.group(1)):
            findings.append(_make_finding("SEC-JS-001", file, _line_of(text, m.start()), m.group(0)))
            # also record the callee for the evidence
            findings[-1].evidence = f"{callee}({m.group(1)})"
            _ = callee

    # SEC-JS-002 document.write
    for m in _RE_DOC_WRITE.finditer(text):
        if _unsafe(m.group(1)):
            findings.append(_make_finding("SEC-JS-002", file, _line_of(text, m.start()), m.group(0)))

    # SEC-JS-003 innerHTML
    for m in _RE_INNER_HTML.finditer(text):
        if _unsafe(m.group(1)):
            findings.append(_make_finding("SEC-JS-003", file, _line_of(text, m.start()), m.group(0)))

    # SEC-JS-004 open-redirect (window.location = X)
    for m in _RE_LOCATION_ASSIGN.finditer(text):
        if not _is_literal(m.group(1)):
            findings.append(_make_finding("SEC-JS-004", file, _line_of(text, m.start()), m.group(0)))

    # SEC-JS-005 postMessage: low-confidence, agent_verify (regex can't prove missing origin check)
    for m in _RE_POST_MESSAGE.finditer(text):
        f = _make_finding("SEC-JS-005", file, _line_of(text, m.start()), m.group(0))
        f.confidence = "low"
        f.triage = "agent_verify"
        findings.append(f)

    # RELI-JS-001 async useEffect
    for m in _RE_ASYNC_USE_EFFECT.finditer(text):
        f = _make_finding("RELI-JS-001", file, _line_of(text, m.start()), m.group(0))
        f.confidence = "medium"
        findings.append(f)

    # RELI-JS-002 addEventListener without matching removeEventListener (file-level)
    added = {m.group(1) for m in _RE_ADD_EVENT.finditer(text)}
    removed = {m.group(1) for m in _RE_REMOVE_EVENT.finditer(text)}
    leaked = added - removed
    if leaked:
        # report once per leaked event, at the first occurrence
        first_match = None
        for m in _RE_ADD_EVENT.finditer(text):
            if m.group(1) in leaked:
                first_match = m
                break
        if first_match is not None:
            f = _make_finding(
                "RELI-JS-002", file, _line_of(text, first_match.start()), first_match.group(0)
            )
            f.message = f"addEventListener({', '.join(sorted(leaked))}) without matching removeEventListener"
            f.confidence = "medium"
            f.triage = "agent_verify"
            findings.append(f)

    return findings


# Credential-word check for SEC-SECRET-004 (H5): the regex only captures the
# assignment; whether the variable name actually looks like a credential is
# decided here so the rule fires on `apiKey`/`password` but not `mockX`.
# Words are stored in flattened form (no underscore) because the variable name
# is lowercased — `accessToken` → `accesstoken`, `api_key` → `api_key` → both
# need to match, so we strip non-alphanumerics from the name before checking.
_CRED_WORDS = ("password", "passwd", "secret", "apikey", "accesstoken", "authtoken")
# Names that look like test fixtures — these get the rule dismissed even if
# the variable name contains a credential word.
_MOCK_PREFIXES = ("mock", "fake", "dummy", "test", "example", "sample", "fixture")


def _looks_like_credential_var(name: str) -> bool:
    """True when ``name`` looks like a real credential variable.

    Heuristic: the name (lowercased, separators stripped so `api_key` and
    `apiKey` both flatten to `apikey`) must contain a credential word, AND
    must not start with a test/mock prefix. So `apiKey`/`MY_PASSWORD`/
    `accessToken` fire but `mockApiKey`/`fakePassword`/`testSecret` do not.
    """
    lower = re.sub(r"[^a-z0-9]", "", name.lower())
    if not any(w in lower for w in _CRED_WORDS):
        return False
    return not any(lower.startswith(p) for p in _MOCK_PREFIXES)


def scan_secrets(text: str, file: str, secret_patterns: list[tuple[str, "re.Pattern[str]"]]) -> list[Finding]:
    """Run the supplied secret patterns. ``secret_patterns`` is [(id, regex), ...]."""
    findings = []
    for rule_id, pattern in secret_patterns:
        for m in pattern.finditer(text):
            # SEC-SECRET-004 post-filter (H5): only fire when the captured
            # variable name actually looks like a credential, not a mock.
            if rule_id == "SEC-SECRET-004":
                name = m.groupdict().get("name", "")
                if not _looks_like_credential_var(name):
                    continue
            f = _make_finding(rule_id, file, _line_of(text, m.start()), m.group(0))
            # mask the captured secret in the evidence
            f.evidence = re.sub(pattern, lambda mm: mm.group(0)[:6] + "...REDACTED", m.group(0))
            findings.append(f)
    return findings


def discover_files(root: str | Path, respect_gitignore: bool = True) -> list[Path]:
    """Yield JS/TS source files under ``root``, skipping node_modules and build dirs."""
    root = Path(root)
    skip_dirs = {"node_modules", ".git", "dist", "build", ".next", ".nuxt", "coverage", ".cache"}
    lockfiles = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
    valid_exts = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")
    out = []
    # H6: use os.walk with followlinks=False so a symlinked directory inside
    # the project cannot pull in files from outside the target tree (the audit
    # must not follow a malicious symlink into ~/.ssh etc. and emit secrets).
    import os

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # prune skipped dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            if name.lower() in lockfiles:
                continue
            if not name.lower().endswith(valid_exts):
                continue
            out.append(Path(dirpath, name))
    return sorted(out)
