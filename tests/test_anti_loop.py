"""Anti-loop discipline tests (brief 2.3 rule #1).

The tracker must allow up to MAX_ATTEMPTS transitions to `testing` and block the
one that would exceed it with exit code 4 / status `blocked_anti_loop`.

These tests fail if the gate is removed, the boundary changes, or the attempts
counter stops incrementing.
"""
import json

import deepseek_hypothesis_tracker as tracker


def test_max_attempts_constant_is_three():
    # Anchors the documented invariant. If this changes, the tests below adjust
    # automatically but this assertion makes the intended value explicit.
    assert tracker.MAX_ATTEMPTS_PER_HYPOTHESIS == 3


def test_attempts_under_limit_succeed(primed_hyp_file, run_action):
    # MAX_ATTEMPTS transitions to testing are allowed (attempts 1..3).
    for i in range(tracker.MAX_ATTEMPTS_PER_HYPOTHESIS):
        code = run_action(
            action="update",
            hypothesis_id="H1",
            status="testing",
            evidence=f"probe attempt {i + 1}",
            hypotheses_file=str(primed_hyp_file),
        )
        assert code == 0, f"attempt {i + 1} should succeed, got exit {code}"


def test_attempt_over_limit_blocks_with_code_4(primed_hyp_file, run_action, capsys):
    for i in range(tracker.MAX_ATTEMPTS_PER_HYPOTHESIS):
        run_action(
            action="update", hypothesis_id="H1", status="testing",
            evidence=f"probe {i + 1}", hypotheses_file=str(primed_hyp_file),
        )
    capsys.readouterr()  # discard output of the allowed attempts

    code = run_action(
        action="update", hypothesis_id="H1", status="testing",
        evidence="one attempt too many", hypotheses_file=str(primed_hyp_file),
    )
    assert code == 4, f"4th testing transition must block (exit 4), got {code}"

    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "blocked_anti_loop"
    assert envelope["result"]["current_attempts"] == tracker.MAX_ATTEMPTS_PER_HYPOTHESIS


def test_non_testing_transition_does_not_consume_attempt(primed_hyp_file, run_action):
    # status=open must NOT increment the attempts counter -> never blocks.
    for _ in range(tracker.MAX_ATTEMPTS_PER_HYPOTHESIS + 2):
        code = run_action(
            action="update", hypothesis_id="H1", status="open",
            evidence="not a testing transition", hypotheses_file=str(primed_hyp_file),
        )
        assert code == 0


class TestAttemptsCounterRoundTrip:
    def test_get_attempts_parses_log_line(self):
        t = tracker.DeepSeekHypothesisTracker()
        block = {"log": ["- created: x", "- attempts: 2", "- evidence: y"]}
        assert t._get_attempts(block) == 2

    def test_get_attempts_defaults_zero_when_absent(self):
        t = tracker.DeepSeekHypothesisTracker()
        assert t._get_attempts({"log": ["- created: x"]}) == 0

    def test_set_attempts_is_idempotent_single_entry(self):
        t = tracker.DeepSeekHypothesisTracker()
        block = {"log": ["- created: x", "- attempts: 1"]}
        t._set_attempts(block, 5)
        attempts_lines = [ln for ln in block["log"] if "attempts:" in ln]
        assert attempts_lines == ["- attempts: 5"]
        assert t._get_attempts(block) == 5
