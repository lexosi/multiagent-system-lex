"""Class-jump validation tests.

A class-jump must carry a rationale of at least MIN_CLASS_JUMP_RATIONALE_CHARS
characters (the escalation can't be a rubber stamp). Tests fail if the length
gate is removed or the threshold loosened.
"""
import json

import deepseek_hypothesis_tracker as tracker

MIN = tracker.MIN_CLASS_JUMP_RATIONALE_CHARS


def test_min_rationale_constant_is_thirty():
    assert MIN == 30


def test_short_rationale_rejected_with_code_1(primed_hyp_file, run_action, capsys):
    rationale = "x" * (MIN - 1)  # one char short
    assert len(rationale) < MIN
    code = run_action(
        action="class-jump",
        from_hyp="H1",
        hypothesis_text="reformulada en capa de abstraccion distinta",
        rationale=rationale,
        hypotheses_file=str(primed_hyp_file),
    )
    assert code == 1, f"short rationale must be rejected (exit 1), got {code}"
    envelope = json.loads(capsys.readouterr().out)
    assert "rationale" in (envelope["error"] or "").lower()


def test_exact_threshold_rationale_accepted(primed_hyp_file, run_action):
    rationale = "y" * MIN  # exactly at the boundary
    assert len(rationale) == MIN
    code = run_action(
        action="class-jump",
        from_hyp="H1",
        hypothesis_text="reformulada en capa de abstraccion distinta",
        rationale=rationale,
        hypotheses_file=str(primed_hyp_file),
    )
    assert code == 0, f"rationale at threshold must be accepted, got exit {code}"


def test_missing_required_args_rejected(primed_hyp_file, run_action):
    # class-jump requires from_hyp + rationale + hypothesis_text.
    code = run_action(
        action="class-jump",
        from_hyp="H1",
        rationale="z" * (MIN + 5),
        # hypothesis_text omitted on purpose
        hypotheses_file=str(primed_hyp_file),
    )
    assert code == 1


def test_whitespace_padded_short_rationale_still_rejected(primed_hyp_file, run_action):
    # Leading/trailing whitespace must not be counted toward the minimum.
    rationale = "  " + ("a" * (MIN - 4)) + "  "
    code = run_action(
        action="class-jump",
        from_hyp="H1",
        hypothesis_text="nueva hipotesis",
        rationale=rationale,
        hypotheses_file=str(primed_hyp_file),
    )
    assert code == 1
