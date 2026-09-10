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

RULE C (project CLAUDE.md governed by its curated zone): those cases use SYNTHETIC
fixtures (a temp CLAUDE.md with/without AUTO-CURATED markers), never real repo/user
paths. The accented case covers non-ASCII old_string LOCALIZATION: the fixture is read
as UTF-8 and json.dumps escapes the payload to ASCII escapes, so raw UTF-8 bytes
on stdin are NOT exercised here -- that stdin path is guaranteed only by the
byte-identical hook itself. It goes red if the file read-encoding or matching breaks.
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
HOOK_GUARD = HOOKS_DIR / "pretooluse-guard-protected-files.ps1"

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


# Rule C fixture substrings, kept stable so tests and the synthetic file agree.
# U+00F3 = 'o'+acute, U+00F1 = 'n'+tilde. Built via chr() so this .py stays
# pure-ASCII on disk while the written fixture (UTF-8) carries the real glyphs.
_O_ACUTE = chr(0x00F3)  # LATIN SMALL LETTER O WITH ACUTE
_N_TILDE = chr(0x00F1)  # LATIN SMALL LETTER N WITH TILDE
_GUARD_OUTSIDE_ASCII = "OUTSIDE doctrine line"
_GUARD_INSIDE_ASCII = "INSIDE curated entry"
_GUARD_OUTSIDE_ACCENTED = (
    "configuraci" + _O_ACUTE + "n con tilde: acci" + _O_ACUTE + "n " + _N_TILDE
)


def _synth_claudemd(with_markers=True):
    """Write a synthetic CLAUDE.md into a fresh temp dir; return its path (str).

    The temp prefix deliberately avoids the substring 'audit' (Rule C skips any
    path containing 'audit'). Basename is always CLAUDE.md — that is the whole
    discriminator Rule C keys on.

      with_markers=True  -> an OUTSIDE line (ASCII) + an OUTSIDE line (accented,
                            non-ASCII) BEFORE the START marker, the marker pair on
                            their own column-0 lines, and one line INSIDE.
      with_markers=False -> plain content, zero markers (markerless passthrough).
    """
    d = Path(tempfile.mkdtemp(prefix="claudemd_fx_"))
    path = d / "CLAUDE.md"
    if with_markers:
        content = (
            f"{_GUARD_OUTSIDE_ASCII}\n"
            f"{_GUARD_OUTSIDE_ACCENTED}\n"
            "<!-- AUTO-CURATED:START -->\n"
            f"{_GUARD_INSIDE_ASCII}\n"
            "<!-- AUTO-CURATED:END -->\n"
        )
    else:
        content = "plain line\nno markers at all here\n"
    path.write_text(content, encoding="utf-8")
    return str(path)


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
        input=payload, capture_output=True, text=True, encoding="utf-8", env=env,
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


@_skip
def test_scope_fastallow_bypass_denied():
    """E-4: a path whose PREFIX contains 'content/verse' as an unanchored
    substring (evilcontent/verse) AND whose suffix is a managed territory
    (agent_templates/*.md) must still DENY for root. The unanchored NEVER-block
    clause must not fast-allow it. RED until line 169 is anchored to a segment
    boundary."""
    bypass = str(REPO_ROOT / "evilcontent" / "verse" / "agent_templates" / "implementer.md")
    assert decision_of(run_hook(HOOK_SCOPE, _edit(bypass, None))) == "deny"


@_skip
def test_scope_real_verse_allowed():
    """Guards the segment anchor from over-narrowing: a real UEFN project
    .verse path (Content/Verse/*.verse) must still ALLOW via NEVER-block, so
    nobody anchors these clauses further and starts blocking legit Verse work."""
    real_verse = "F:\\Noobs\\MyProj\\Content\\Verse\\game.verse"
    assert decision_of(run_hook(HOOK_SCOPE, _edit(real_verse, None))) == "allow"


# --- Rule C: any CLAUDE.md governed by its declared curated zone (markers) ---
# Synthetic fixtures only (temp CLAUDE.md), never a real repo/user path. RED-first:
# these define the ported contract; today's hook only guards the USER CLAUDE.md.
# Guard contract is ASYMMETRIC vs the scope hook: DENY emits JSON on stdout, ALLOW
# is SILENT (Emit-Allow, exit 0, empty stdout). So ALLOW cases assert stdout is
# empty (same idiom as test_advisory_silent_on_py), never decision_of(...)=="allow"
# (that reads None and would pass vacuously). Pre-port RED is exactly the 2 DENY
# cases (write-with-markers, edit-inside-noncurator): with today's hook every temp
# CLAUDE.md falls through to silent Emit-Allow, so the 4 allow cases already pass
# (silent) and the 2 deny cases fail (expect "deny", get empty/None). Post-port
# both DENY cases go green via the project-CLAUDE.md Emit-Deny branch; the allows
# stay silent = still green.
@_skip
def test_guard_markerless_allow():
    """A CLAUDE.md with no AUTO-CURATED markers is passthrough -> allow."""
    md = _synth_claudemd(with_markers=False)
    assert run_hook(HOOK_GUARD, _edit(md, None)).strip() == ""


@_skip
def test_guard_write_with_markers_deny():
    """Zone: a whole-file Write over a markered CLAUDE.md -> deny (Write clobbers
    the markers + doctrine, denied for everyone)."""
    md = _synth_claudemd(with_markers=True)
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": md},
               "cwd": str(REPO_ROOT)}
    assert decision_of(run_hook(HOOK_GUARD, payload)) == "deny"


@_skip
def test_guard_edit_outside_markers_allow():
    """Zone 2: Edit whose old_string sits OUTSIDE the markers, agent absent
    (== root) -> allow. Doctrine outside the curated zone is not curator turf."""
    md = _synth_claudemd(with_markers=True)
    payload = {"tool_name": "Edit",
               "tool_input": {"file_path": md,
                              "old_string": _GUARD_OUTSIDE_ASCII, "new_string": "X"},
               "cwd": str(REPO_ROOT)}
    assert run_hook(HOOK_GUARD, payload).strip() == ""


@_skip
def test_guard_edit_inside_noncurator_deny():
    """Curated zone: Edit whose old_string sits INSIDE the markers, agent absent
    (== root, non-curator) -> deny. Only knowledge-curator edits between markers."""
    md = _synth_claudemd(with_markers=True)
    payload = {"tool_name": "Edit",
               "tool_input": {"file_path": md,
                              "old_string": _GUARD_INSIDE_ASCII, "new_string": "X"},
               "cwd": str(REPO_ROOT)}
    assert decision_of(run_hook(HOOK_GUARD, payload)) == "deny"


@_skip
def test_guard_edit_inside_curator_allow():
    """Curated zone: same INSIDE-markers Edit, but agent_type knowledge-curator
    -> allow. Baked-in discriminator: only the caller identity flips the verdict."""
    md = _synth_claudemd(with_markers=True)
    payload = {"tool_name": "Edit",
               "tool_input": {"file_path": md,
                              "old_string": _GUARD_INSIDE_ASCII, "new_string": "X"},
               "agent_type": "knowledge-curator",
               "cwd": str(REPO_ROOT)}
    assert run_hook(HOOK_GUARD, payload).strip() == ""


@_skip
def test_guard_accented_outside_allow():
    """Encoding guard: Edit whose old_string is the ACCENTED OUTSIDE line -> allow.
    Only passes if the non-ASCII old_string is located in-file (IndexOf >= 0). A
    broken UTF-8 path yields IndexOf == -1 -> 'not found' -> deny -> this goes red."""
    md = _synth_claudemd(with_markers=True)
    payload = {"tool_name": "Edit",
               "tool_input": {"file_path": md,
                              "old_string": _GUARD_OUTSIDE_ACCENTED, "new_string": "X"},
               "cwd": str(REPO_ROOT)}
    assert run_hook(HOOK_GUARD, payload).strip() == ""


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
    g("scope fast-allow bypass -> DENY", test_scope_fastallow_bypass_denied)
    g("scope real .verse -> ALLOW", test_scope_real_verse_allowed)

    print("\nRule C (project CLAUDE.md by curated zone) cases:")
    g("guard markerless -> ALLOW", test_guard_markerless_allow)
    g("guard Write w/ markers -> DENY", test_guard_write_with_markers_deny)
    g("guard Edit outside markers -> ALLOW", test_guard_edit_outside_markers_allow)
    g("guard Edit inside non-curator -> DENY", test_guard_edit_inside_noncurator_deny)
    g("guard Edit inside curator -> ALLOW", test_guard_edit_inside_curator_allow)
    g("guard accented outside -> ALLOW", test_guard_accented_outside_allow)

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
