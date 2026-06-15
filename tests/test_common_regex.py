"""Unit tests for the shared regex constants and the hypothesis-id pattern.

Each test asserts BOTH accepted and rejected inputs, so loosening or breaking a
pattern fails the suite (no trivially-always-pass assertions).
"""
import pytest

import _common_regex as cr
import deepseek_hypothesis_tracker as tracker


class TestTaskIdRe:
    @pytest.mark.parametrize("valid", [
        "AR_x",
        "AR_2026-05-19_B2-coherence-auditor",
        "AR_smoke_test_001",
        "AR_a-b_c-D-9",
    ])
    def test_accepts_valid_ar_ids(self, valid):
        assert cr.TASK_ID_RE.match(valid), f"should accept {valid!r}"

    @pytest.mark.parametrize("invalid", [
        "",                 # empty
        "AR_",              # prefix only, needs >=1 body char
        "ar_lowercase",     # wrong prefix case
        "BR_wrong_prefix",  # not AR_
        "AR_with space",    # space not allowed
        "AR_with/slash",    # slash not allowed
        " AR_leading",      # leading whitespace
    ])
    def test_rejects_invalid_ar_ids(self, invalid):
        assert not cr.TASK_ID_RE.match(invalid), f"should reject {invalid!r}"


class TestAttemptsLogRe:
    @pytest.mark.parametrize("line,expected", [
        ("- attempts: 0", "0"),
        ("- attempts: 3", "3"),
        ("- attempts: 12", "12"),
        ("-   attempts:   7  ", "7"),  # tolerant of surrounding whitespace
    ])
    def test_captures_count(self, line, expected):
        m = cr.ATTEMPTS_LOG_RE.match(line)
        assert m is not None, f"should match {line!r}"
        assert m.group(1) == expected

    @pytest.mark.parametrize("line", [
        "attempts: 3",        # missing leading dash
        "- attempts:",        # missing number
        "- attempts: x",      # non-numeric
        "- tries: 3",         # wrong key
        "- attempts: 3 extra",  # trailing junk
    ])
    def test_rejects_malformed(self, line):
        assert cr.ATTEMPTS_LOG_RE.match(line) is None, f"should reject {line!r}"


class TestHypIdRe:
    @pytest.mark.parametrize("valid", ["H1", "H2", "H12", "H99"])
    def test_accepts_valid(self, valid):
        assert tracker.HYP_ID_RE.match(valid), f"should accept {valid!r}"

    @pytest.mark.parametrize("invalid", [
        "H0",     # must start 1-9
        "H01",    # no leading zero
        "h1",     # lowercase
        "H",      # missing number
        "HX",     # non-numeric
        "1",      # missing prefix
        "H1 ",    # trailing space
    ])
    def test_rejects_invalid(self, invalid):
        assert not tracker.HYP_ID_RE.match(invalid), f"should reject {invalid!r}"
