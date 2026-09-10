#!/usr/bin/env python3
"""Contract tests for the PowerShell hooks — dual-mode (pytest + stdlib script).

WHY: the hooks are the enforcement mechanism, yet no test exercises one. A guard
nobody runs is a claim, not a guarantee. This file runs the hook as CC runs it
(payload on stdin, decision on stdout) and asserts the DECISION.

TWO WAYS TO RUN, ZERO DIVERGENCE:
  - pytest:  `pytest tests/test_hooks_contract.py`   (public repo CI already does this)
  - script:  `python tests/test_hooks_contract.py`   (private repo has no pytest)

HOW IT FINDS THE HOOKS (no hardcode, no cwd reliance):
  repo root = Path(__file__).resolve().parent.parent  (this file lives in tests/)
  hooks dir = <repo>/hooks/                            (same idiom as tests/conftest.py)
  Optional out-of-tree override for local runs only: env HOOKS_REPO_ROOT.

HOW IT CALLS POWERSHELL:
  `pwsh` (PowerShell Core) — the only shell on ubuntu-latest CI, and present on
  the dev box. `powershell.exe` (5.1, Windows-only) is never used. If pwsh is
  absent the tests SKIP (never false-fail).

CONTRACT REMINDER (why assertions never read the exit code):
  Every hook exits 0 ALWAYS. The decision travels in stdout JSON:
    PreToolUse -> {"hookSpecificOutput":{"permissionDecision":"deny"|"allow", ...}}
  Asserting returncode==0 would pass for BOTH deny and allow -> proves nothing.

HERMETIC: env MULTIAGENT_PATHS_CONFIG points at a temp fixture so disk-scanning
branches (sentinel scan) hit an empty fixture, not the real repo/user files.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Optional pytest integration (private repo has no pytest). Import guarded at top
# to satisfy ruff E402 (no module-level import after code).
try:
    import pytest  # type: ignore
except ImportError:  # script mode without pytest
    pytest = None

# --- repo/hooks resolution: __file__-relative, cwd-independent, no hardcode ---
_OVERRIDE = os.environ.get("HOOKS_REPO_ROOT")  # local out-of-tree runs only
REPO_ROOT = Path(_OVERRIDE).resolve() if _OVERRIDE else Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
HOOK_ADVISORY = HOOKS_DIR / "pretooluse-verse-kb-advisory.ps1"
HOOK_SCOPE = HOOKS_DIR / "pretooluse-block-scope-territory.ps1"

PWSH = shutil.which("pwsh")

# Real target from today's deny (deny-evidence-2026-09-10.json) so the exercised
# envelope matches the deny that actually fired against a real caller.
SCOPE_TARGET = str(REPO_ROOT / "agent_templates" / "implementer.md")


# --- skip decorator: pytest.mark.skipif when pytest present, else no-op ---
if pytest is not None:
    _skip = pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell Core) not found")
else:
    def _skip(fn):  # no-op decorator for script mode
        return fn


# --- helpers ---
def _fixture_root():
    """Temp fixture repo: RepoRoot->fixture, AgentRunsDir empty (no sentinel)."""
    root = Path(tempfile.mkdtemp(prefix="hooks_fx_"))
    (root / "config").mkdir()
    (root / "docs" / "agent_runs").mkdir(parents=True)
    (root / "hooks").mkdir()
    (root / "config" / "paths.json").write_text(
        json.dumps({"knowledge_base": "F:\\knowledge"}), encoding="utf-8")
    return root


def run_hook(hook_path, payload_dict):
    """Feed payload JSON to the hook via pwsh stdin. Return raw stdout (str).

    Payload built with json.dumps -> correct backslash escaping (never hand-typed).
    """
    payload = json.dumps(payload_dict)
    env = dict(os.environ)
    fx = _fixture_root()
    env["MULTIAGENT_PATHS_CONFIG"] = str(fx / "config" / "paths.json")
    proc = subprocess.run(
        [PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(hook_path)],
        input=payload, capture_output=True, text=True, env=env,
    )
    return proc.stdout


def decision_of(stdout):
    """stdout JSON -> permissionDecision, or None. NEVER reads exit code."""
    s = (stdout or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    return (obj.get("hookSpecificOutput") or {}).get("permissionDecision")


def advisory_of(stdout):
    s = (stdout or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    return (obj.get("hookSpecificOutput") or {}).get("additionalContext")


def _edit(file_path, agent_type=None):
    p = {"tool_name": "Edit",
         "tool_input": {"file_path": file_path, "old_string": "a", "new_string": "b"},
         "cwd": str(REPO_ROOT)}
    if agent_type is not None:
        p["agent_type"] = agent_type  # absent == root
    return p


# --- tests (collected by pytest; also called by __main__) ---
@_skip
def test_advisory_emitted_on_verse():
    ctx = advisory_of(run_hook(HOOK_ADVISORY, _edit("F:\\Noobs\\X\\foo.verse", "implementer")))
    assert ctx is not None and "ADVISORY" in ctx


@_skip
def test_advisory_silent_on_py():
    out = run_hook(HOOK_ADVISORY, _edit("F:\\proj\\foo.py", "implementer"))
    assert out.strip() == ""


@_skip
def test_scope_root_denied():
    assert decision_of(run_hook(HOOK_SCOPE, _edit(SCOPE_TARGET, None))) == "deny"


@_skip
def test_scope_implementer_allowed():
    assert decision_of(run_hook(HOOK_SCOPE, _edit(SCOPE_TARGET, "implementer"))) == "allow"


@_skip
def test_scope_discriminates():
    """Baked-in 'seen red' guard: same target, only agent_type differs, verdict flips."""
    root_dec = decision_of(run_hook(HOOK_SCOPE, _edit(SCOPE_TARGET, None)))
    impl_dec = decision_of(run_hook(HOOK_SCOPE, _edit(SCOPE_TARGET, "implementer")))
    assert root_dec == "deny"
    assert impl_dec == "allow"
    assert root_dec != impl_dec  # not both trivially passing


# --- script mode: run all + prove the forced reds are really red ---
def _main():
    if PWSH is None:
        print("SKIP: pwsh (PowerShell Core) not found on PATH.")
        return 0
    print(f"# repo_root={REPO_ROOT}")
    print(f"# hooks={HOOKS_DIR}")
    print(f"# pwsh={PWSH}\n")

    greens = []

    def g(label, fn):
        try:
            fn()
            greens.append(True)
            print(f"  [GREEN] {label}")
        except AssertionError as e:
            greens.append(False)
            print(f"  [RED  ] {label}: {e}")

    print("GREEN cases:")
    g("advisory emitted on .verse", test_advisory_emitted_on_verse)
    g("advisory silent on .py", test_advisory_silent_on_py)
    g("scope root -> DENY", test_scope_root_denied)
    g("scope implementer -> ALLOW", test_scope_implementer_allowed)
    g("scope discriminates (deny != allow)", test_scope_discriminates)

    # Forced reds (technique A): wrong expectations MUST fail. If any of these
    # does NOT fail, the assertion is inert (e.g. reading exit code) -> suite lies.
    print("\nForced reds (MUST be red):")
    reds_ok = True
    deny_out = run_hook(HOOK_SCOPE, _edit(SCOPE_TARGET, None))
    if decision_of(deny_out) == "allow":
        print("  [BUG ] R1 deny-payload matched ALLOW (assertion inert!)")
        reds_ok = False
    else:
        print(f"  [RED  ] R1 deny-payload asserted ALLOW -> correctly fails (got {decision_of(deny_out)!r})")
    verse_out = run_hook(HOOK_ADVISORY, _edit("F:\\Noobs\\X\\foo.verse", "implementer"))
    if verse_out.strip() == "":
        print("  [BUG ] R2 .verse advisory matched silent (assertion inert!)")
        reds_ok = False
    else:
        print("  [RED  ] R2 .verse asserted silent -> correctly fails (got advisory JSON)")

    ok = all(greens) and reds_ok
    print(f"\nGREEN {sum(greens)}/{len(greens)} | reds behaved: {reds_ok}")
    print("RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
