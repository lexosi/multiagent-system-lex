"""Unit tests for tier -> model resolution against the committed config JSON.

Asserts the real `config/agents.json` + `config/models.json` wiring. Fails if a
tier is renamed, a model reassigned, or an Anthropic/DeepSeek split is introduced
that contradicts the documented invariant (claude_md => high => opus only).
"""
import json
from pathlib import Path

import pytest

import _deepseek_wrapper_base as base

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestResolveModelForAgent:
    def test_claude_md_agent_resolves_to_opus_high(self):
        # planner is a claude_md / tier=high agent -> opus
        assert base.resolve_model_for_agent("planner") == "claude-opus-4.8"

    def test_medium_tier_resolves_to_deepseek_pro(self):
        assert base.resolve_model_for_agent("researcher") == "deepseek-v4-pro"

    def test_low_tier_resolves_to_deepseek_flash(self):
        assert base.resolve_model_for_agent("doc_writer") == "deepseek-v4-flash"

    def test_null_tier_storage_agent_returns_none(self):
        # hypothesis_tracker is storage-only (tier=null) -> no model
        assert base.resolve_model_for_agent("hypothesis_tracker") is None

    def test_unregistered_agent_raises_keyerror(self):
        with pytest.raises(KeyError):
            base.resolve_model_for_agent("does-not-exist")


class TestModelsConfigInvariant:
    def test_tier_to_model_mapping_exact(self):
        models = json.loads((REPO_ROOT / "config" / "models.json").read_text())["tiers"]
        # Documented invariant: high=opus (Anthropic), medium/low=DeepSeek.
        assert models["high"] == "claude-opus-4.8"
        assert models["medium"] == "deepseek-v4-pro"
        assert models["low"] == "deepseek-v4-flash"

    def test_high_tier_is_anthropic_opus_only(self):
        models = json.loads((REPO_ROOT / "config" / "models.json").read_text())["tiers"]
        # Guard: high tier must never resolve to a deepseek model.
        assert "deepseek" not in models["high"].lower()
        assert "opus" in models["high"].lower()

    def test_every_claude_md_agent_is_high_tier(self):
        agents = json.loads((REPO_ROOT / "config" / "agents.json").read_text())["agents"]
        for name, spec in agents.items():
            if spec.get("type") == "claude_md":
                assert spec.get("tier") == "high", f"{name} is claude_md but tier={spec.get('tier')}"


class TestKbTiersStructure:
    def test_verse_uefn_has_tier1_always_files(self):
        kb = json.loads((REPO_ROOT / "config" / "kb_tiers.json").read_text())["domains"]
        assert "verse-uefn" in kb
        assert len(kb["verse-uefn"]["tier_1_always"]) >= 1

    def test_every_domain_declares_three_tiers(self):
        kb = json.loads((REPO_ROOT / "config" / "kb_tiers.json").read_text())["domains"]
        for domain, tiers in kb.items():
            for key in ("tier_1_always", "tier_2_bug_fix", "tier_3_project_init"):
                assert key in tiers, f"{domain} missing {key}"
                assert isinstance(tiers[key], list)
