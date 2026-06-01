"""_deepseek_wrapper_base.py — Base class for DeepSeek API wrappers.

All grunt-work agent wrappers (researcher, doc_writer, hypothesis_tracker,
tech_debt_scanner) inherit from WrapperBase. Provides:
  - OpenAI client init pointing to DeepSeek (OpenAI-compatible endpoint)
  - Standard logging to stderr
  - Audit file management (writes full output to docs/agent_runs/AR_<task_id>/)
  - Cost calculation (DeepSeek pricing as of 2026-05-14)
  - Standard JSON stdout output contract

Contract: see briefs/ANTI_SYCOPHANCY_ADDENDUM.md, section "ARQUITECTURA DE MODELOS".

Pricing source: https://api-docs.deepseek.com/quick_start/pricing (verified 2026-05-14).
WARNING: deepseek-v4-pro is on 75% promotional discount expiring 2026-05-31. After
that date, re-verify pricing in PRICING dict below — base rate is 4x current.

Model name policy: use canonical IDs deepseek-v4-flash / deepseek-v4-pro.
Aliases deepseek-chat / deepseek-reasoner are deprecated by DeepSeek and
will be removed in the future.
"""
import json
import os
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv

# Cargar .env desde el root de multiagent-system
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# Force stdout to UTF-8. Windows default cp1252 fails on unicode in completion content
# or in error tracebacks. Combined with ensure_ascii=True in _emit_result for double
# defense (portable JSON for machines + utf-8 stream as belt-and-suspenders).
sys.stdout.reconfigure(encoding="utf-8")


# DeepSeek pricing per 1M tokens, USD. Cache-miss rate (no automatic caching assumed).
# Re-verify after 2026-05-31 when v4-pro promotional discount expires.
PRICING = {
    "deepseek-v4-flash": {"prompt": 0.14, "completion": 0.28},
    "deepseek-v4-pro":   {"prompt": 0.435, "completion": 0.87},  # 75% promo until 2026-05-31
}


# Multi-agent root resolution.
# Precedence: MULTIAGENT_PATHS_CONFIG env > paths.json hardcoded PROD > MULTIAGENT_ROOT env > hardcoded literal.
def _resolve_paths_json() -> Path:
    """Resolve location of paths.json to read.

    Precedence:
      1. MULTIAGENT_PATHS_CONFIG env var (override per-machine/test sandbox).
      2. Hardcoded PROD fallback: F:\\multiagent-system\\config\\paths.json.

    If env var is set but points to non-existent path, emits WARN to stderr
    and falls back to PROD path (fail-safe, not silent).
    """
    env_override = os.environ.get("MULTIAGENT_PATHS_CONFIG")
    if env_override:
        p = Path(env_override)
        if p.exists():
            return p
        print(
            f"[WARN] MULTIAGENT_PATHS_CONFIG points to non-existent {p}",
            file=sys.stderr,
            flush=True,
        )
    return Path(r"F:\multiagent-system\config\paths.json")


def _load_paths_config() -> Path:
    """Resuelve multiagent_root con precedencia:
    MULTIAGENT_PATHS_CONFIG env > paths.json hardcoded > MULTIAGENT_ROOT env > hardcoded literal.
    """
    paths_json = _resolve_paths_json()
    if paths_json.exists():
        try:
            with open(paths_json, encoding="utf-8") as f:
                data = json.load(f)
            root = data.get("multiagent_root")
            if root:
                return Path(root)
        except Exception as e:
            print(f"[WARN] paths.json load failed: {e}", file=sys.stderr, flush=True)
            # fallback to next
    return Path(os.environ.get("MULTIAGENT_ROOT", r"F:\multiagent-system"))


MULTIAGENT_ROOT = _load_paths_config()
AGENT_RUNS_DIR = MULTIAGENT_ROOT / "docs" / "agent_runs"


# ---------- B3.0 config resolution (agents.json + models.json) ----------
# Source-of-truth: F:\multiagent-system\config\agents.json + config/models.json.
# Lazy + cached module-level. Fail-loud if missing/malformed (B3.0 decision Lexosi #5).

_AGENTS_CONFIG_PATH = MULTIAGENT_ROOT / "config" / "agents.json"
_MODELS_CONFIG_PATH = MULTIAGENT_ROOT / "config" / "models.json"
_agents_cache: dict | None = None
_models_cache: dict | None = None


def _load_agents_config() -> dict:
    """Load agents.json cached. Raise FileNotFoundError if missing, json.JSONDecodeError if malformed."""
    global _agents_cache
    if _agents_cache is None:
        if not _AGENTS_CONFIG_PATH.exists():
            raise FileNotFoundError(f"agents.json not found at {_AGENTS_CONFIG_PATH}")
        with open(_AGENTS_CONFIG_PATH, encoding="utf-8") as f:
            _agents_cache = json.load(f)
    return _agents_cache


def _load_models_config() -> dict:
    """Load models.json cached. Raise FileNotFoundError if missing, json.JSONDecodeError if malformed."""
    global _models_cache
    if _models_cache is None:
        if not _MODELS_CONFIG_PATH.exists():
            raise FileNotFoundError(f"models.json not found at {_MODELS_CONFIG_PATH}")
        with open(_MODELS_CONFIG_PATH, encoding="utf-8") as f:
            _models_cache = json.load(f)
    return _models_cache


def get_agent_params(agent_name: str) -> dict:
    """Return params dict for agent. Fail-loud if not registered (B3.0 decision Lexosi #5)."""
    agents = _load_agents_config()["agents"]
    if agent_name not in agents:
        raise KeyError(
            f"agent '{agent_name}' not registered in {_AGENTS_CONFIG_PATH}. "
            f"Registered: {sorted(agents.keys())}"
        )
    return agents[agent_name].get("params", {})


def resolve_model_for_agent(agent_name: str) -> str | None:
    """Resolve tier->model via models.json. Returns None if tier=null (storage agents)."""
    agents = _load_agents_config()["agents"]
    if agent_name not in agents:
        raise KeyError(
            f"agent '{agent_name}' not registered in {_AGENTS_CONFIG_PATH}. "
            f"Registered: {sorted(agents.keys())}"
        )
    tier = agents[agent_name].get("tier")
    if tier is None:
        return None
    models = _load_models_config()["tiers"]
    if tier not in models:
        raise KeyError(
            f"tier '{tier}' for agent '{agent_name}' not in models.json. "
            f"Available tiers: {sorted(models.keys())}"
        )
    return models[tier]


def _iso_now() -> str:
    """UTC timestamp ISO format, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WrapperBase(ABC):
    """Abstract base class for DeepSeek-backed agent wrappers.

    Subclasses implement run() to do the wrapper-specific work, call
    self._call_deepseek() for LLM calls, then terminate via self._emit_result().

    Class-level defaults overridable by subclass:
      - DEFAULT_TEMPERATURE (default 0.3 — bajo para grunt work determinístico)
      - DEFAULT_TIMEOUT (default 60s — override para scans largos)
      - DEFAULT_MAX_RETRIES (default 2 — exponential backoff de la lib openai)
    """

    DEFAULT_TEMPERATURE = 0.3
    DEFAULT_TIMEOUT = 180  # bumped from 60s 2026-05-18 — v4-pro default post-Opción 1 con prompts grandes (researcher 10+ archivos .verse) excedía 60s. 180s + max_retries=2 = ~9min worst case, dentro de PowerShell tool envelope.
    DEFAULT_MAX_RETRIES = 2

    def __init__(self, wrapper_name: str):
        self.wrapper_name = wrapper_name
        self._start_time = time.monotonic()
        self._total_tokens = {"prompt": 0, "completion": 0, "total": 0}
        self._total_cost_usd = 0.0
        self._model_used: str | None = None
        self._model_requested: str | None = None

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            # Emit error envelope and exit before constructing client.
            self._emit_result(
                status="error",
                summary="DEEPSEEK_API_KEY env var not set",
                result=None,
                error="auth failed (check DEEPSEEK_API_KEY)",
                exit_code=2,
            )

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            timeout=self.DEFAULT_TIMEOUT,
            max_retries=self.DEFAULT_MAX_RETRIES,
        )
        self._log("INFO", f"wrapper initialized (timeout={self.DEFAULT_TIMEOUT}s, max_retries={self.DEFAULT_MAX_RETRIES})")

    def _log(self, level: str, msg: str) -> None:
        """Emit log line to stderr. Stdout reserved for final JSON envelope."""
        print(f"[{level}] {_iso_now()} [{self.wrapper_name}] {msg}", file=sys.stderr, flush=True)

    def _build_audit_path(self, task_id: str) -> Path:
        """Construct audit file path. Creates parent dir if missing.

        task_id is the authoritative AR_<id> identifier — used literal, no prefix added.
        """
        task_dir = AGENT_RUNS_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return task_dir / f"{self.wrapper_name}_{ts}.md"

    def _write_audit(self, audit_path: Path, content: str) -> None:
        """Write full output to audit file (UTF-8 no BOM)."""
        audit_path.write_text(content, encoding="utf-8")
        self._log("INFO", f"audit written: {audit_path}")

    def _calc_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Cost USD for one call at cache-miss pricing. Returns 0 for unknown models."""
        rates = PRICING.get(model)
        if not rates:
            self._log("WARN", f"unknown model '{model}' for pricing — cost reported as 0")
            return 0.0
        cost = (prompt_tokens * rates["prompt"] + completion_tokens * rates["completion"]) / 1_000_000
        return round(cost, 6)

    def _call_deepseek(
        self,
        messages: list[dict],
        model: str = "deepseek-v4-flash",
        max_tokens: int = 393216,
        temperature: float | None = None,
    ) -> str:
        # NOTE: max_tokens=393216 es el MAX REAL aceptado por DeepSeek API v4-pro (probed 2026-05-18).
        # Rango válido API: [1, 393216]. Above → BadRequestError 400. Lexosi directive 2026-05-18:
        # "no se vea limitado". Es CEILING (no forcing) — modelo decide cuándo terminar.
        # Costo real solo paga tokens generados (típico 2-8K en mayoría tareas, no 393K).
        """Single chat completion call. Accumulates token usage + cost across calls.

        temperature=None uses self.DEFAULT_TEMPERATURE (overridable per subclass).
        Returns assistant message content. Caller handles exceptions and routes
        to self._emit_result() with status='error'.
        """
        if temperature is None:
            temperature = self.DEFAULT_TEMPERATURE

        self._log("INFO", f"api call started, model={model}, max_tokens={max_tokens}, temperature={temperature}")
        t0 = time.monotonic()
        resp = self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        dt_ms = int((time.monotonic() - t0) * 1000)

        pt = resp.usage.prompt_tokens
        ct = resp.usage.completion_tokens
        tt = resp.usage.total_tokens
        # Cost calc uses the requested model name (PRICING dict keyed by canonical IDs).
        cost = self._calc_cost(model, pt, ct)

        self._total_tokens["prompt"] += pt
        self._total_tokens["completion"] += ct
        self._total_tokens["total"] += tt
        self._total_cost_usd += cost
        self._model_requested = model
        self._model_used = resp.model  # Actual model after alias resolution (may differ).

        if self._model_used != model:
            self._log("INFO", f"model alias resolved: requested={model} → returned={self._model_used}")

        self._log(
            "INFO",
            f"api call ok, dur_ms={dt_ms}, tokens(p/c/t)={pt}/{ct}/{tt}, cost_usd={cost:.6f}",
        )
        content = resp.choices[0].message.content
        if not content:
            raise ValueError(
                f"empty/null content from DeepSeek, finish_reason={resp.choices[0].finish_reason!r}"
            )
        return content

    def _emit_result(
        self,
        status: str,
        summary: str,
        result: Any,
        meta: dict | None = None,
        error: str | None = None,
        exit_code: int = 0,
        audit_path: Path | None = None,
    ) -> None:
        """Emit final JSON envelope to stdout, then exit.

        Builds meta from accumulators if not provided. If audit_path is None,
        meta.audit_file is null.
        """
        duration_ms = int((time.monotonic() - self._start_time) * 1000)
        auto_meta = {
            "agent": self.wrapper_name,
            "model": self._model_used,
            "model_requested": self._model_requested,
            "tokens": dict(self._total_tokens),
            "cost_usd": round(self._total_cost_usd, 6),
            "duration_ms": duration_ms,
            "audit_file": str(audit_path) if audit_path else None,
        }
        if meta is None:
            meta = auto_meta
        else:
            for k, v in auto_meta.items():
                meta.setdefault(k, v)

        envelope = {
            "status": status,
            "summary": summary,
            "result": result,
            "meta": meta,
            "error": error,
        }
        # ensure_ascii=True: escape unicode como \uXXXX. JSON portable cross-encoding.
        # Audit file (UTF-8 explícito) sigue con caracteres legibles para humano.
        print(json.dumps(envelope, ensure_ascii=True, indent=2), flush=True)
        sys.exit(exit_code)

    @abstractmethod
    def run(self) -> None:
        """Wrapper-specific logic. Must terminate via self._emit_result()."""
        ...
