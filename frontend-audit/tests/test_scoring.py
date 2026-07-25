"""Tests for the scoring model: per-dimension penalties, grade bands, dedup."""
from __future__ import annotations

from audit.models import Finding
from audit.scoring import calculate_score, count_by_severity, dedup_findings


def _f(rule="X", severity="error", dimension="security", file="a.js", line=1):
    return Finding(file=file, line=line, severity=severity, dimension=dimension, rule=rule)


class TestCalculateScore:
    def test_no_findings_is_perfect(self):
        s = calculate_score([])
        assert s["overall"] == 100.0
        assert s["grade"] == "A"
        assert all(s[d] == 100 for d in ("security", "reliability", "best-practice", "arch", "deps"))

    def test_security_errors_drop_security_dimension_only(self):
        s = calculate_score([_f(dimension="security", severity="error")])
        # one error = -10 → security 90, others stay 100
        assert s["security"] == 90
        assert s["reliability"] == 100
        # overall weighted: 0.35*90 + 0.20*100*4 = 31.5 + 80 = 96.5? recompute below
        assert s["overall"] < 100

    def test_grade_bands(self):
        assert calculate_score([])["grade"] == "A"
        # 11 errors in security → security 0, overall = 0.35*0 + 0.65*100 = 65 → D
        many = [_f(dimension="security", severity="error", line=i) for i in range(11)]
        g = calculate_score(many)["grade"]
        assert g == "D"
        # overwhelming errors everywhere → F
        all_dims = [
            _f(dimension=d, severity="error", file=f"{d}.js", line=i)
            for d in ("security", "reliability", "best-practice", "arch", "deps")
            for i in range(15)
        ]
        assert calculate_score(all_dims)["grade"] == "F"

    def test_eslint_findings_folded_into_best_practice(self):
        f = Finding(file="a.js", line=1, severity="error", dimension="security", rule="r", source="eslint")
        s = calculate_score([f])
        # source=eslint → scored as best-practice, not security
        assert s["security"] == 100
        assert s["best-practice"] == 90


class TestCountBySeverity:
    def test_counts(self):
        fs = [
            _f(severity="error"),
            _f(severity="error"),
            _f(severity="warning"),
            _f(severity="info", line=2),
        ]
        c = count_by_severity(fs)
        assert c == {"error": 2, "warning": 1, "info": 1}


class TestDedup:
    def test_same_file_line_rule_collapsed(self):
        a = _f(rule="R", file="a.js", line=5, severity="warning")
        b = _f(rule="R", file="a.js", line=5, severity="error")  # more severe wins
        out = dedup_findings([a, b])
        assert len(out) == 1
        assert out[0].severity == "error"

    def test_different_line_kept(self):
        out = dedup_findings([_f(line=1), _f(line=2)])
        assert len(out) == 2
