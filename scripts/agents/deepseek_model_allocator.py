"""deepseek_model_allocator.py — Audit model assignments cada 72h.

Propósito: monitorear asignación modelos (Anthropic opus + DeepSeek v4-pro)
post-Opción 1 (2026-05-18). Detecta:
- Cost trends ARs ventana N horas
- parse_failed counts en wrappers DeepSeek
- Recomendaciones KEEP / DOWNGRADE (post promo) / REVIEW prompt

Output: docs/model_reviews/MR_<YYYY-MM-DD>.md
Side-effect: actualiza <repo_root>/.last_model_review timestamp.

CLI:
    --task-id AR_<id>            (required)
    --cadence-hours N            (optional, default 72)
    --force                      (skip cadence check)
    --output-dir PATH            (optional, override docs/model_reviews/)
    --max-output-tokens N        (optional, default 393216 = API max)
    --model MODEL                (optional, default deepseek-v4-flash)
    --smoke-test                 (canonical: cadence=1h, force)

EXIT CODES:
    0 = ok (review generated)
    1 = generic error
    2 = config error
    3 = API error
    6 = blocked_cadence_too_recent (last review < cadence_hours ago, no --force)
"""
import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _deepseek_wrapper_base import WrapperBase, MULTIAGENT_ROOT, AGENT_RUNS_DIR, PRICING, get_agent_params, resolve_model_for_agent  # noqa: E402
from _common_regex import TASK_ID_RE  # noqa: E402

try:
    from openai import APIError, APIConnectionError, RateLimitError
except ImportError:
    APIError = APIConnectionError = RateLimitError = Exception


# Module-level params load (fail-loud at import per B3.0 <user> decision #5).
_AGENT_PARAMS = get_agent_params("model_allocator")
LAST_REVIEW_PATH = MULTIAGENT_ROOT / ".last_model_review"
DEFAULT_OUTPUT_DIR = MULTIAGENT_ROOT / "docs" / "model_reviews"
TEMPLATES_DIR = MULTIAGENT_ROOT / "agent_templates"
WRAPPERS_DIR = MULTIAGENT_ROOT / "scripts" / "agents"
PROMO_EXPIRY_ISO = _AGENT_PARAMS.get("promo_expiry_iso", "2026-05-31")  # TD-029 resolution: read from agents.json


SYSTEM_PROMPT = (
    "Eres un model-allocator auditor. Analiza data de ARs recientes y propón "
    "ajustes de asignación de modelos.\n\n"
    "REGLAS INQUEBRANTABLES:\n"
    "1. NO inventes signals. Si data ventana es nula, output 'no data, KEEP all'.\n"
    "2. Solo 2 tiers permitidos (Opción 1 aprobada <user> 2026-05-18): Anthropic opus + DeepSeek v4-pro.\n"
    "3. NUNCA propongas sonnet ni v4-flash como upgrade (eliminados arquitectónicamente).\n"
    "4. Recomendaciones permitidas:\n"
    "   - KEEP (no signal, mantener asignación actual)\n"
    "   - DOWNGRADE_POST_PROMO (solo aplica DeepSeek tras 2026-05-31 cuando v4-pro sube 4x)\n"
    "   - REVIEW_PROMPT (problema NO es modelo — es system prompt; sugiere ajustar prompt)\n"
    "   - ADD_KB (specialist-verse retorna INSUFFICIENT — falta KB local, no modelo)\n"
    "5. Self-evaluation transparente: tú (model-allocator) eres DeepSeek v4-pro. Si tu workload es simple (parsear tablas), recomiéndate downgrade post promo.\n\n"
    "Formato output (markdown):\n"
    "# Model Review — <YYYY-MM-DD>\n"
    "## Ventana auditada\n## Tabla per agente\n## Recomendaciones\n## Self-evaluation\n## Pricing watch\n## Próximo review\n"
    "Estilo: caveman, bullets, sin filler. Output max {max_tokens} tokens."
)


class DeepSeekModelAllocator(WrapperBase):

    def __init__(self):
        super().__init__(wrapper_name="deepseek_model_allocator")
        self.args = None

    def _validate_task_id(self, task_id: str) -> None:
        if not TASK_ID_RE.match(task_id):
            self._emit_result(
                status="error",
                summary=f"invalid task-id: {task_id}",
                result=None,
                error=f"task-id must match ^AR_[A-Za-z0-9_-]+$, got: {task_id!r}",
                exit_code=1,
            )

    def _check_cadence(self) -> tuple[bool, float | None]:
        """Returns (needs_review, age_hours). If last_review file missing → always needs."""
        if self.args.force:
            return True, None
        if not LAST_REVIEW_PATH.exists():
            return True, None
        last_mtime = datetime.fromtimestamp(LAST_REVIEW_PATH.stat().st_mtime, tz=timezone.utc)
        age = (datetime.now(timezone.utc) - last_mtime).total_seconds() / 3600.0
        if age < self.args.cadence_hours:
            return False, age
        return True, age

    def _collect_anthropic_models(self) -> dict[str, str]:
        """Read agent_templates/*.md frontmatter to get current Anthropic models."""
        result = {}
        if not TEMPLATES_DIR.exists():
            return result
        for tpl in sorted(TEMPLATES_DIR.glob("*.md")):
            try:
                text = tpl.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            m = re.search(r"^model:\s*(\S+)\s*$", text, re.MULTILINE)
            if m:
                result[tpl.stem] = m.group(1)
        return result

    def _collect_deepseek_defaults(self) -> dict[str, str]:
        """Scan scripts/agents/deepseek_*.py for argparse --model default."""
        result = {}
        if not WRAPPERS_DIR.exists():
            return result
        for wrapper in sorted(WRAPPERS_DIR.glob("deepseek_*.py")):
            try:
                text = wrapper.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            m = re.search(r'add_argument\(["\']--model["\'].*?default=["\']([^"\']+)["\']', text, re.DOTALL)
            if m:
                # Wrapper name stem: deepseek_<name>
                stem = wrapper.stem.replace("deepseek_", "", 1)
                result[stem] = m.group(1)
        return result

    def _collect_ar_window_data(self, window_hours: float) -> dict:
        """Walk docs/agent_runs/AR_*/ filtering mtime >= now - window_hours.

        Returns aggregate: ar_count, deepseek_audits (per-wrapper count + cost),
        parse_failed_count, ar_ids list.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        cutoff_ts = cutoff.timestamp()
        ar_ids = []
        wrapper_stats = {}  # {wrapper_name: {count, cost, parse_failed}}

        if not AGENT_RUNS_DIR.exists():
            return {"ar_count": 0, "ar_ids": [], "wrapper_stats": {}, "parse_failed_total": 0}

        for ar_dir in AGENT_RUNS_DIR.iterdir():
            if not ar_dir.is_dir() or not ar_dir.name.startswith("AR_"):
                continue
            try:
                ar_mtime = ar_dir.stat().st_mtime
            except OSError:
                continue
            if ar_mtime < cutoff_ts:
                continue
            ar_ids.append(ar_dir.name)

            for audit_file in ar_dir.glob("deepseek_*.md"):
                # Filename pattern: deepseek_<wrapper>_<UTCstamp>.md
                m = re.match(r"deepseek_([a-z_]+)_\d{8}T\d{6}Z\.md", audit_file.name)
                if not m:
                    continue
                wrapper_name = m.group(1).rstrip("_")
                stats = wrapper_stats.setdefault(wrapper_name, {"count": 0, "cost": 0.0, "parse_failed": 0})
                stats["count"] += 1
                # Parse audit content to find cost (heurístico: línea "cost_usd: $X.XXXX")
                try:
                    content = audit_file.read_text(encoding="utf-8")
                    cost_match = re.search(r"cost_usd[:\s=]+\$?(\d+\.\d+)", content, re.IGNORECASE)
                    if cost_match:
                        stats["cost"] += float(cost_match.group(1))
                    if "parse_failed" in content.lower():
                        stats["parse_failed"] += 1
                except (UnicodeDecodeError, OSError):
                    pass

        return {
            "ar_count": len(ar_ids),
            "ar_ids": ar_ids[:20],  # cap visualization
            "wrapper_stats": wrapper_stats,
            "parse_failed_total": sum(s["parse_failed"] for s in wrapper_stats.values()),
        }

    def _build_user_prompt(self, anthropic_models: dict, deepseek_defaults: dict, ar_data: dict) -> str:
        return (
            f"DATA RECOLECTADA (ventana {self.args.cadence_hours}h):\n\n"
            f"ANTHROPIC MODELS (frontmatter agent_templates/*.md):\n{json.dumps(anthropic_models, indent=2)}\n\n"
            f"DEEPSEEK DEFAULTS (argparse scripts/agents/deepseek_*.py):\n{json.dumps(deepseek_defaults, indent=2)}\n\n"
            f"AR WINDOW DATA:\n{json.dumps(ar_data, indent=2)}\n\n"
            f"PRICING:\n{json.dumps(PRICING, indent=2)}\n\n"
            f"PROMO V4-PRO EXPIRA: {PROMO_EXPIRY_ISO}\n"
            f"FECHA HOY: {datetime.now(timezone.utc).date().isoformat()}\n\n"
            f"Genera MR_<date>.md ahora siguiendo formato del system prompt."
        )

    def _resolve_output_path(self) -> Path:
        out_dir = Path(self.args.output_dir) if self.args.output_dir else DEFAULT_OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = out_dir / f"MR_{date}.md"
        # Si ya existe, sufijo -2, -3
        if path.exists():
            for n in range(2, 100):
                cand = out_dir / f"MR_{date}-{n}.md"
                if not cand.exists():
                    return cand
        return path

    def run(self) -> None:
        a = self.args
        self._validate_task_id(a.task_id)

        # Cadence gate
        needs_review, age_hours = self._check_cadence()
        if not needs_review:
            self._emit_result(
                status="blocked_cadence_too_recent",
                summary=f"Last model review {age_hours:.1f}h ago < cadence {a.cadence_hours}h. Use --force to override.",
                result={
                    "age_hours": age_hours,
                    "cadence_hours": a.cadence_hours,
                    "last_review_path": str(LAST_REVIEW_PATH),
                },
                error=f"cadence not met (age={age_hours:.1f}h < {a.cadence_hours}h)",
                exit_code=6,
            )

        # Collect data
        anthropic_models = self._collect_anthropic_models()
        deepseek_defaults = self._collect_deepseek_defaults()
        ar_data = self._collect_ar_window_data(a.cadence_hours)
        self._log("INFO", f"collected: {len(anthropic_models)} anthropic, {len(deepseek_defaults)} deepseek, {ar_data['ar_count']} ARs in window")

        # Build prompts
        system_prompt = SYSTEM_PROMPT.format(max_tokens=a.max_output_tokens)
        user_prompt = self._build_user_prompt(anthropic_models, deepseek_defaults, ar_data)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Call DeepSeek
        try:
            completion = self._call_deepseek(
                messages=messages,
                model=a.model,
                max_tokens=a.max_output_tokens,
            )
        except RateLimitError as e:
            self._emit_result(status="error", summary="DeepSeek rate limit", result=None, error=f"RateLimitError: {e}", exit_code=3)
        except APIConnectionError as e:
            self._emit_result(status="error", summary="DeepSeek connection error", result=None, error=f"APIConnectionError: {e}", exit_code=1)
        except APIError as e:
            self._emit_result(status="error", summary="DeepSeek API error", result=None, error=f"APIError: {e}", exit_code=1)

        # Write MR file
        output_path = self._resolve_output_path()
        output_path.write_text(completion, encoding="utf-8")
        output_bytes = len(completion.encode("utf-8"))
        self._log("INFO", f"MR written: {output_path} ({output_bytes} bytes)")

        # Update .last_model_review timestamp
        try:
            LAST_REVIEW_PATH.write_text(_iso_now_strict(), encoding="utf-8")
            self._log("INFO", f"updated {LAST_REVIEW_PATH}")
        except OSError as e:
            self._log("WARN", f"failed to update last_model_review: {e}")

        # Write audit
        audit_path = self._build_audit_path(a.task_id)
        audit_content = (
            f"# Model Allocator audit — task_id `{a.task_id}`\n\n"
            f"## Inputs\n- cadence_hours: {a.cadence_hours}\n- force: {a.force}\n- output: `{output_path}`\n\n"
            f"## Anthropic models inventory\n```json\n{json.dumps(anthropic_models, indent=2)}\n```\n\n"
            f"## DeepSeek defaults inventory\n```json\n{json.dumps(deepseek_defaults, indent=2)}\n```\n\n"
            f"## AR window data\n```json\n{json.dumps(ar_data, indent=2)}\n```\n\n"
            f"## System prompt\n```\n{system_prompt}\n```\n\n"
            f"## User prompt\n```\n{user_prompt}\n```\n\n"
            f"## Completion (MR generated)\n\n{completion}\n"
        )
        self._write_audit(audit_path, audit_content)

        self._emit_result(
            status="ok",
            summary=f"model review generated: {output_path}",
            result={
                "output_file": str(output_path),
                "output_bytes": output_bytes,
                "anthropic_agent_count": len(anthropic_models),
                "deepseek_wrapper_count": len(deepseek_defaults),
                "ar_window_count": ar_data["ar_count"],
                "parse_failed_total": ar_data["parse_failed_total"],
            },
            audit_path=audit_path,
            exit_code=0,
        )


def _iso_now_strict() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="deepseek_model_allocator",
        description="Audit model assignments cada 72h, generate MR_*.md.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke-test", action="store_true",
                      help="canonical: cadence=1h + force")
    mode.add_argument("--task-id", help="AR_<id>")
    p.add_argument("--cadence-hours", type=float, default=_AGENT_PARAMS.get("cadence_hours_default", 72.0),
                   help="hours since last review required (default from agents.json params.cadence_hours_default)")
    p.add_argument("--force", action="store_true",
                   help="skip cadence check, force review now")
    p.add_argument("--output-dir", help="override default docs/model_reviews/")
    p.add_argument("--max-output-tokens", type=int, default=None,
                   help="Max output tokens. Default None = read from agents.json params.model_allocator.max_output_tokens.")
    p.add_argument("--model", default=None, help="DeepSeek model. Default None = resolved via agents.json tier.")
    args = p.parse_args()
    return args


def main() -> None:
    args = _parse_args()
    if args.smoke_test:
        smoke = _AGENT_PARAMS["smoke"]
        args.task_id = smoke["task_id"]
        args.cadence_hours = smoke["cadence_hours"]
        args.force = smoke["force"]
        args.max_output_tokens = smoke["max_tokens"]
        # Smoke uses flash intentionally — validates pipeline mechanics, not output quality. Runtime defaults to pro.
        args.model = smoke["model"]
    else:
        if args.model is None:
            args.model = resolve_model_for_agent("model_allocator")
        if args.max_output_tokens is None:
            args.max_output_tokens = _AGENT_PARAMS.get("max_output_tokens", 65536)

    wrapper = DeepSeekModelAllocator()
    wrapper.args = args
    try:
        wrapper.run()
    except SystemExit:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        wrapper._log("ERROR", f"unexpected exception: {e}")
        wrapper._log("ERROR", tb)
        wrapper._emit_result(
            status="error",
            summary=f"Unexpected error: {type(e).__name__}",
            result=None,
            error={"type": type(e).__name__, "message": str(e), "traceback": tb},
            exit_code=1,
        )


if __name__ == "__main__":
    main()
