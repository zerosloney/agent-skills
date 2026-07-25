"""Unit tests for the self-authored security / reliability / secret rules.

Each rule is tested for:
- positive detection (the dangerous pattern fires)
- negative detection (the safe literal variant does NOT fire)
- correct severity / dimension / triage propagation from the rule catalog.
"""
from __future__ import annotations

from audit.models import Finding
from audit.ruledefs.secrets import SECRET_PATTERNS
from audit.visitors import _is_literal, scan_secrets, scan_text


def _ids(findings: list[Finding]) -> list[str]:
    return [f.rule for f in findings]


# ───────────────────────── literal detector ─────────────────────────

class TestIsLiteral:
    def test_string_literal(self):
        assert _is_literal('"hello"') is True
        assert _is_literal("'hi'") is True

    def test_number(self):
        assert _is_literal("42") is True
        assert _is_literal("-3.14") is True

    def test_keyword_literals(self):
        assert _is_literal("true") is True
        assert _is_literal("null") is True

    def test_identifier_is_not_literal(self):
        assert _is_literal("props.bio") is False
        assert _is_literal("foo") is False

    def test_template_with_interpolation_is_not_literal(self):
        assert _is_literal("`hello ${name}`") is False


# ───────────────────────── line lookup (B3) ─────────────────────────

class TestLineLookup:
    """B3 regression: _line_of must stay O(log n) and report correct 1-based
    lines. Previously it recounted newlines from offset 0 on every call,
    making a 20k-line file with thousands of findings take 2s+ (O(n²))."""

    def test_correct_line_numbers(self):
        code = "a\nb\neval(x);\nd\n"
        # eval is on line 3
        from audit.visitors import _line_of
        assert _line_of(code, code.index("eval")) == 3
        assert _line_of(code, 0) == 1
        assert _line_of(code, len(code) - 1) == 4

    def test_many_findings_scale_near_linearly(self):
        # 10k findings should complete well under the old O(n²) cost.
        # We assert a generous bound (3s) — the old code took ~0.5s at 10k
        # but exploded at 20k+; this guards the regression.
        import time

        code = "\n".join(f"function f{i}(){{ eval(x); }}" for i in range(10000))
        t0 = time.time()
        fs = scan_text(code, "big.js")
        elapsed = time.time() - t0
        assert len(fs) == 10000
        assert elapsed < 3.0, f"scan took {elapsed:.2f}s, expected < 3s (B3 regression)"


# ───────────────────────── SEC-REACT-001 ─────────────────────────

class TestDangerouslySetInnerHTML:
    def test_flags_non_literal(self):
        code = '<div dangerouslySetInnerHTML={{__html: bio}} />'
        fs = scan_text(code, "a.tsx")
        assert "SEC-REACT-001" in _ids(fs)

    def test_does_not_flag_literal(self):
        code = '<div dangerouslySetInnerHTML={{__html: "<b>safe</b>"}} />'
        fs = scan_text(code, "a.tsx")
        assert "SEC-REACT-001" not in _ids(fs)

    def test_does_not_flag_sanitized(self):
        # value passed through a recognized sanitizer is suppressed — this is
        # the rule's own fix advice, so it must clear the finding.
        for call in ("sanitize(bio)", "DOMPurify.sanitize(bio)", "escapeHtml(bio)"):
            code = f"<div dangerouslySetInnerHTML={{{{__html: {call}}}}} />"
            assert "SEC-REACT-001" not in _ids(scan_text(code, "a.tsx")), call

    def test_flags_unrecognized_wrapper(self):
        # a non-sanitizer call must still be flagged (regression guard).
        code = "<div dangerouslySetInnerHTML={{__html: format(bio)}} />"
        assert "SEC-REACT-001" in _ids(scan_text(code, "a.tsx"))


# ───────────────────────── SEC-REACT-002 (bare __html) ─────────────────────────

class TestBareHtmlKey:
    """B2 regression: SEC-REACT-002 was registered + documented but had no
    detection logic. These tests pin the now-implemented behavior."""

    def test_flags_bare_object_literal(self):
        fs = scan_text("const obj = {__html: userInput};", "a.tsx")
        assert "SEC-REACT-002" in _ids(fs)

    def test_does_not_flag_literal(self):
        fs = scan_text('const obj = {__html: "<b>safe</b>"};', "a.tsx")
        assert "SEC-REACT-002" not in _ids(fs)

    def test_does_not_flag_sanitized(self):
        fs = scan_text("const obj = {__html: sanitize(x)};", "a.tsx")
        assert "SEC-REACT-002" not in _ids(fs)

    def test_does_not_duplicate_react_001(self):
        # the {{__html: ...}} form is SEC-REACT-001's domain; 002's lookbehind
        # must exclude it so the same sink isn't reported twice.
        fs = scan_text("<div dangerouslySetInnerHTML={{__html: bio}} />", "a.tsx")
        assert "SEC-REACT-001" in _ids(fs)
        assert "SEC-REACT-002" not in _ids(fs)


# ───────────────────────── SEC-JS-001 (eval) ─────────────────────────

class TestEval:
    def test_flags_eval_with_variable(self):
        fs = scan_text("eval(userInput);", "a.js")
        assert "SEC-JS-001" in _ids(fs)

    def test_does_not_flag_eval_with_literal(self):
        fs = scan_text('eval("1+1");', "a.js")
        assert "SEC-JS-001" not in _ids(fs)


# ───────────────────────── SEC-JS-002 (document.write) ─────────────────────────

class TestDocumentWrite:
    def test_flags_non_literal(self):
        fs = scan_text("document.write(req.body);", "a.js")
        assert "SEC-JS-002" in _ids(fs)

    def test_does_not_flag_literal(self):
        fs = scan_text('document.write("<h1>hi</h1>");', "a.js")
        assert "SEC-JS-002" not in _ids(fs)


# ───────────────────────── SEC-JS-003 (innerHTML) ─────────────────────────

class TestInnerHTML:
    def test_flags_non_literal(self):
        fs = scan_text("el.innerHTML = userInput;", "a.js")
        assert "SEC-JS-003" in _ids(fs)

    def test_does_not_flag_literal(self):
        fs = scan_text('el.innerHTML = "<b>ok</b>";', "a.js")
        assert "SEC-JS-003" not in _ids(fs)

    def test_does_not_flag_sanitized(self):
        # regression guard for the净化抑制 (mirrors SEC-REACT-001 behavior).
        for call in ("sanitize(x)", "DOMPurify.sanitize(x)", "escapeHtml(x)"):
            assert "SEC-JS-003" not in _ids(scan_text(f"el.innerHTML = {call};", "a.js")), call

    def test_evidence_captures_full_rhs(self):
        # L2 regression: greedy capture must include the whole RHS, not just
        # its first character (previously ".innerHTML = f" from "foo(bio)").
        fs = scan_text("el.innerHTML = foo(bio);", "a.js")
        matches = [f for f in fs if f.rule == "SEC-JS-003"]
        assert matches and "foo(bio)" in matches[0].evidence


# ───────────────────────── SEC-JS-004 (open redirect) ─────────────────────────

class TestOpenRedirect:
    def test_flags_location_from_variable(self):
        fs = scan_text("window.location = redirectUrl;", "a.js")
        assert "SEC-JS-004" in _ids(fs)

    def test_does_not_flag_literal_url(self):
        fs = scan_text('window.location = "/dashboard";', "a.js")
        assert "SEC-JS-004" not in _ids(fs)


# ───────────────────────── SEC-JS-005 (postMessage) ─────────────────────────

class TestPostMessage:
    def test_flags_with_low_confidence_agent_verify(self):
        fs = scan_text("iframe.postMessage(data, '*');", "a.js")
        matches = [f for f in fs if f.rule == "SEC-JS-005"]
        assert len(matches) == 1
        assert matches[0].confidence == "low"
        assert matches[0].triage == "agent_verify"


# ───────────────────────── RELI-JS-001 (async useEffect) ─────────────────────────

class TestAsyncUseEffect:
    def test_flags_async_callback(self):
        fs = scan_text("useEffect(async () => { await fetch('/x'); }, []);", "a.tsx")
        assert "RELI-JS-001" in _ids(fs)

    def test_does_not_flag_sync_callback(self):
        fs = scan_text("useEffect(() => { fetch('/x'); }, []);", "a.tsx")
        assert "RELI-JS-001" not in _ids(fs)


# ───────────────────────── RELI-JS-002 (event leak) ─────────────────────────

class TestEventListenerLeak:
    def test_flags_unmatched_add(self):
        fs = scan_text('el.addEventListener("click", h);', "a.js")
        assert "RELI-JS-002" in _ids(fs)

    def test_balanced_add_remove_not_flagged(self):
        code = 'el.addEventListener("click", h); el.removeEventListener("click", h);'
        fs = scan_text(code, "a.js")
        assert "RELI-JS-002" not in _ids(fs)


# ───────────────────────── secrets ─────────────────────────

class TestSecrets:
    def test_aws_key_detected(self):
        fs = scan_secrets('const k = "AKIAIOSFODNN7EXAMPLE";', "a.js", SECRET_PATTERNS)
        assert "SEC-SECRET-001" in _ids(fs)

    def test_github_token_detected(self):
        # canonical classic PAT: ghp_ + 36 chars
        token = "ghp_" + "a" * 36
        fs = scan_secrets(f'const t = "{token}";', "a.js", SECRET_PATTERNS)
        assert "SEC-SECRET-002" in _ids(fs)

    def test_google_key_detected(self):
        # canonical google api key: AIza + 35 chars
        key = "AIza" + "a" * 35
        fs = scan_secrets(f'const g = "{key}";', "a.js", SECRET_PATTERNS)
        assert "SEC-SECRET-003" in _ids(fs)

    def test_secret_evidence_is_redacted(self):
        fs = scan_secrets('const k = "AKIAIOSFODNN7EXAMPLE";', "a.js", SECRET_PATTERNS)
        matches = [f for f in fs if f.rule == "SEC-SECRET-001"]
        assert len(matches) == 1
        assert "EXAMPLE" not in matches[0].evidence  # the tail must be redacted
        assert "REDACTED" in matches[0].evidence

    def test_no_false_positive_on_plain_text(self):
        fs = scan_secrets('const greeting = "hello world";', "a.js", SECRET_PATTERNS)
        assert _ids(fs) == []

    # ── H5: SEC-SECRET-004 credential-variable heuristic ──

    def test_secret004_fires_on_real_credential_names(self):
        for decl in (
            'const apiKey = "sk-test-1234567890";',
            'const MY_PASSWORD = "hunter2";',
            'const accessToken = "abc123def";',
            'const api_key = "k_123";',
        ):
            fs = scan_secrets(decl, "a.js", SECRET_PATTERNS)
            assert "SEC-SECRET-004" in _ids(fs), decl

    def test_secret004_suppressed_on_mock_test_names(self):
        for decl in (
            'const mockApiKey = "fake";',
            'const fakePassword = "x";',
            'const testSecret = "y";',
            'const dummyToken = "z";',
        ):
            fs = scan_secrets(decl, "a.js", SECRET_PATTERNS)
            assert "SEC-SECRET-004" not in _ids(fs), decl

    def test_secret004_triage_is_agent_only(self):
        from audit.rules import get_spec
        assert get_spec("SEC-SECRET-004").triage == "agent_only"


# ───────────────────────── rule metadata propagation ─────────────────────────

class TestRuleMetadataPropagation:
    def test_finding_inherits_severity_and_dimension(self):
        fs = scan_text("eval(x);", "a.js")
        f = [x for x in fs if x.rule == "SEC-JS-001"][0]
        assert f.severity == "error"
        assert f.dimension == "security"
        assert f.triage == "deterministic"
