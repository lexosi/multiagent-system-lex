"""Pytest config for hermetic unit tests of the agent wrappers.

These tests exercise *pure logic* (regex, tier resolution, anti-loop counter,
class-jump validation) with **zero API calls**:

- `openai` is stubbed in `sys.modules` so importing the wrapper base does not
  require the real SDK or a network.
- `DEEPSEEK_API_KEY` is set to a dummy value so `WrapperBase.__init__` passes its
  presence check (it never calls the API for the storage actions under test).
- `MULTIAGENT_ROOT` points at the repo root so `config/*.json` resolves to the
  real committed configs (tier-resolution tests assert against them).

Everything must be set BEFORE the wrapper modules are imported, hence it lives at
module top-level in conftest (pytest imports conftest before the test modules).
"""
import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "scripts" / "agents"

# --- 1. Make the wrapper modules importable ---
sys.path.insert(0, str(AGENTS_DIR))

# --- 2. Stub `openai` so `from openai import OpenAI` works without the real SDK ---
if "openai" not in sys.modules:
    _fake = types.ModuleType("openai")

    class _StubOpenAI:  # pragma: no cover - never invoked (no API calls in tests)
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    _fake.OpenAI = _StubOpenAI
    sys.modules["openai"] = _fake

# Stub `python-dotenv` too: `load_dotenv()` is a no-op here (tests set env directly).
if "dotenv" not in sys.modules:
    _fake_dotenv = types.ModuleType("dotenv")
    _fake_dotenv.load_dotenv = lambda *a, **k: False
    sys.modules["dotenv"] = _fake_dotenv

# --- 3. Env the wrapper base reads at import / init time ---
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy-test-key-not-used")
os.environ["MULTIAGENT_ROOT"] = str(REPO_ROOT)

# --- 4. Helpers / fixtures for the storage-action tests ---
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

_ARG_DEFAULTS = dict(
    task_id="AR_test",
    action=None,
    hypothesis_text=None,
    hypothesis_id=None,
    evidence=None,
    status=None,
    hypotheses_file=None,
    from_hyp=None,
    rationale=None,
    premise_rechecked=False,
    force=False,
)


def run_tracker(**overrides):
    """Run one tracker action in-process; return its process exit code.

    Each wrapper action terminates via `_emit_result(...)` -> `sys.exit(code)`,
    so we catch SystemExit and surface the code (mirrors one real CLI invocation).
    """
    from deepseek_hypothesis_tracker import DeepSeekHypothesisTracker

    t = DeepSeekHypothesisTracker()
    args = dict(_ARG_DEFAULTS)
    args.update(overrides)
    t.args = SimpleNamespace(**args)
    try:
        t.run()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


@pytest.fixture
def run_action():
    return run_tracker


@pytest.fixture
def primed_hyp_file(tmp_path):
    """A hypotheses.md initialized with a single hypothesis H1 (attempts=0)."""
    hf = tmp_path / "hypotheses.md"
    assert run_tracker(action="init", hypotheses_file=str(hf)) == 0
    assert run_tracker(
        action="add",
        hypothesis_text="el bug esta en el modulo de persistencia",
        hypotheses_file=str(hf),
    ) == 0
    return hf
