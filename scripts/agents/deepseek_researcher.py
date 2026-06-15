"""deepseek_researcher.py — Grunt-work researcher backed by DeepSeek API.

Propósito: extraer contexto relevante de docs/knowledge base para un task.
NO inventa. NO usa conocimiento externo. Si la info no está en los context files,
lo dice explícitamente.

CLI:
    --task-id AR_<id>          (required) — ID del task, regex ^AR_[A-Za-z0-9_-]+$
    --query "<text>"           (required) — pregunta/criterio de extracción
    --context-files p1,p2,...  (required) — paths .md, separados por coma
    --max-output-tokens N      (optional, default 393216 = API max) — cap completion
    --model MODEL              (optional, default deepseek-v4-pro)
    --smoke-test               — corre caso minimal canónico

Output: JSON envelope en stdout (ver _deepseek_wrapper_base.py).
Audit:  <root>/docs/agent_runs/AR_<task_id>/deepseek_researcher_<UTCstamp>.md
"""
import argparse
import json
import sys
import traceback
from pathlib import Path

# Mismo directorio que el base.
sys.path.insert(0, str(Path(__file__).parent))
from _deepseek_wrapper_base import WrapperBase, get_agent_params, resolve_model_for_agent  # noqa: E402
from _common_regex import TASK_ID_RE  # noqa: E402

try:
    from openai import APIError, APIConnectionError, RateLimitError
except ImportError:
    # Fallback si la lib cambia nombres de exception.
    APIError = APIConnectionError = RateLimitError = Exception


# Module-level params load (fail-loud at import per B3.0 <user> decision #5).
_AGENT_PARAMS = get_agent_params("researcher")
MAX_CONTEXT_BYTES = _AGENT_PARAMS.get("max_context_bytes", 500 * 1024)


SYSTEM_PROMPT = (
    "Eres un research assistant. Lee SOLO los context files que se te proporcionan. "
    "Extrae info relevante a la query. NO inventes. NO uses conocimiento externo. "
    "Si la info no está en los context files, dilo explícitamente. "
    "Output máximo {max_tokens} tokens. "
    "Formato: bullets concisos, paths/nombres concretos cuando aparezcan."
)


class DeepSeekResearcher(WrapperBase):
    """Researcher wrapper — extracción de contexto desde context files."""

    def __init__(self):
        super().__init__(wrapper_name="deepseek_researcher")
        self.args = None  # Set por main() antes de run().
        self._selftest_prompt_construction()

    def _selftest_prompt_construction(self) -> None:
        """Verify all .format() calls in this wrapper succeed. Catches stray {literals}."""
        try:
            _ = SYSTEM_PROMPT.format(max_tokens=1)
        except (KeyError, IndexError, ValueError) as e:
            self._emit_result(
                status="error",
                summary=f"prompt construction failed: {type(e).__name__}",
                result={"prompt": "SYSTEM_PROMPT"},
                error={"type": type(e).__name__, "message": str(e)},
                exit_code=2,
            )

    def _validate_task_id(self, task_id: str) -> None:
        if not TASK_ID_RE.match(task_id):
            self._emit_result(
                status="error",
                summary=f"invalid task-id format: {task_id}",
                result=None,
                error=f"task-id must match ^AR_[A-Za-z0-9_-]+$, got: {task_id!r}",
                exit_code=1,
            )

    def _validate_context_files(self, paths: list[Path]) -> None:
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            self._emit_result(
                status="error",
                summary=f"{len(missing)} context file(s) missing",
                result={"missing": missing},
                error=f"missing context files: {missing}",
                exit_code=1,
            )

    def _load_context(self, paths: list[Path]) -> tuple[str, int]:
        """Read all context files, concat with separators. Returns (text, total_bytes).

        Bails out if any file is non-UTF8 or if total exceeds MAX_CONTEXT_BYTES.
        """
        parts = []
        total_bytes = 0
        for p in paths:
            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                self._emit_result(
                    status="error",
                    summary=f"non-UTF8 context file: {p}",
                    result=None,
                    error=f"UnicodeDecodeError on {p}: {e}",
                    exit_code=1,
                )
            file_bytes = len(content.encode("utf-8"))
            total_bytes += file_bytes
            if total_bytes > MAX_CONTEXT_BYTES:
                msg = (
                    f"context size exceeded limit ({MAX_CONTEXT_BYTES} bytes) when loading file {p}. "
                    f"accumulated size at that point: {total_bytes} bytes. "
                    f"split request into smaller batches."
                )
                self._emit_result(
                    status="error",
                    summary=msg,
                    result={
                        "accumulated_bytes": total_bytes,
                        "limit_bytes": MAX_CONTEXT_BYTES,
                        "file_that_overflowed": str(p),
                    },
                    error=msg,
                    exit_code=1,
                )
            parts.append(f"===== FILE: {p} =====\n{content}\n")
        return "\n".join(parts), total_bytes

    def _build_audit_content(
        self,
        query: str,
        context_files: list[Path],
        context_bytes: int,
        system_prompt: str,
        user_prompt: str,
        completion: str,
        model: str,
        max_tokens: int,
    ) -> str:
        """Markdown audit file con prompt + query + context list + completion + meta."""
        files_listing = "\n".join(f"- `{p}`" for p in context_files)
        return (
            f"# Researcher audit — task_id `{self.args.task_id}`\n\n"
            f"## Query\n\n{query}\n\n"
            f"## Context files ({len(context_files)} files, {context_bytes} bytes)\n\n"
            f"{files_listing}\n\n"
            f"## Model\n\n- requested: `{model}`\n- max_output_tokens: {max_tokens}\n\n"
            f"## System prompt\n\n```\n{system_prompt}\n```\n\n"
            f"## User prompt (full, includes concatenated context)\n\n"
            f"```\n{user_prompt}\n```\n\n"
            f"## Completion\n\n{completion}\n"
        )

    def run(self) -> None:
        a = self.args
        self._validate_task_id(a.task_id)
        context_paths = [Path(p.strip()) for p in a.context_files.split(",") if p.strip()]
        if not context_paths:
            self._emit_result(
                status="error",
                summary="--context-files empty after parsing",
                result=None,
                error="provide at least one path in --context-files",
                exit_code=1,
            )
        self._validate_context_files(context_paths)

        audit_path = self._build_audit_path(a.task_id)
        self._log("INFO", f"loading {len(context_paths)} context file(s)")
        context_text, context_bytes = self._load_context(context_paths)
        self._log("INFO", f"context loaded: {context_bytes} bytes")

        system_prompt = SYSTEM_PROMPT.format(max_tokens=a.max_output_tokens)
        user_prompt = f"QUERY: {a.query}\n\nCONTEXT FILES:\n{context_text}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            completion = self._call_deepseek(
                messages=messages,
                model=a.model,
                max_tokens=a.max_output_tokens,
            )
        except RateLimitError as e:
            self._emit_result(
                status="error",
                summary="DeepSeek rate limit / quota hit",
                result=None,
                error=f"RateLimitError: {e}",
                exit_code=3,
            )
        except APIConnectionError as e:
            self._emit_result(
                status="error",
                summary="DeepSeek API connection error",
                result=None,
                error=f"APIConnectionError: {e}",
                exit_code=1,
            )
        except APIError as e:
            self._emit_result(
                status="error",
                summary="DeepSeek API error",
                result=None,
                error=f"APIError: {e}",
                exit_code=1,
            )

        audit_content = self._build_audit_content(
            query=a.query,
            context_files=context_paths,
            context_bytes=context_bytes,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            completion=completion,
            model=a.model,
            max_tokens=a.max_output_tokens,
        )
        self._write_audit(audit_path, audit_content)

        summary = completion[:200] + ("..." if len(completion) > 200 else "")
        self._emit_result(
            status="ok",
            summary=summary,
            result={
                "extraction": completion,
                "context_files_used": [str(p) for p in context_paths],
                "context_bytes": context_bytes,
            },
            audit_path=audit_path,
            exit_code=0,
        )


def _resolve_smoke_context_path() -> str:
    """Resuelve path de smoke test desde paths.json. Falla claro si no está."""
    paths_json = Path(r"<repo_root>\config\paths.json")
    if not paths_json.exists():
        raise RuntimeError("smoke test needs <repo_root>\\config\\paths.json to exist")
    with open(paths_json, encoding="utf-8") as f:
        data = json.load(f)
    domain = data.get("domains", {}).get("verse-uefn")
    if not domain:
        raise RuntimeError("smoke test needs domains.verse-uefn in paths.json")
    smoke_path = Path(domain) / "docs" / "template_PERSISTENCE_MAP.md"
    if not smoke_path.exists():
        raise RuntimeError(f"smoke test target file not found: {smoke_path}")
    return str(smoke_path)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="deepseek_researcher",
        description="Extract relevant context from .md files via DeepSeek.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke-test", action="store_true",
                      help="run a minimal canonical case")
    mode.add_argument("--task-id", help="AR_<id> task identifier")
    # Args adicionales para normal mode (no required en parser, validación manual post):
    p.add_argument("--query", help="research question / extraction criterion")
    p.add_argument("--context-files", help="comma-separated paths to .md files")
    p.add_argument("--max-output-tokens", type=int, default=None,
                   help="Max output tokens. Default None = read from agents.json params.researcher.max_output_tokens.")
    p.add_argument("--model", default=None, help="DeepSeek model. Default None = resolved via agents.json tier (medium -> deepseek-v4-pro).")
    args = p.parse_args()
    if not args.smoke_test:
        if not args.query or not args.context_files:
            p.error("--query y --context-files son obligatorios en modo normal")
    return args


def main() -> None:
    args = _parse_args()
    if args.smoke_test:
        # Caso canónico minimal: extrae sobre option-version del template PERSISTENCE_MAP.
        smoke = _AGENT_PARAMS["smoke"]
        args.task_id = smoke["task_id"]
        args.query = smoke["query"]
        args.context_files = _resolve_smoke_context_path()
        args.max_output_tokens = smoke["max_tokens"]
        # Smoke uses flash intentionally — validates pipeline mechanics, not output quality. Runtime defaults to pro.
        args.model = smoke["model"]
    else:
        if args.model is None:
            args.model = resolve_model_for_agent("researcher")
        if args.max_output_tokens is None:
            args.max_output_tokens = _AGENT_PARAMS.get("max_output_tokens", 65536)

    wrapper = DeepSeekResearcher()
    wrapper.args = args
    try:
        wrapper.run()
    except SystemExit:
        raise  # Allow normal sys.exit from _emit_result.
    except Exception as e:
        # Programmer error o algo no esperado. Reporta tb completo + envelope error.
        tb = traceback.format_exc()
        wrapper._log("ERROR", f"unexpected exception: {e}")
        wrapper._log("ERROR", tb)
        wrapper._emit_result(
            status="error",
            summary=f"Unexpected error: {type(e).__name__}",
            result=None,
            error={
                "type": type(e).__name__,
                "message": str(e),
                "traceback": tb,
            },
            exit_code=1,
        )


if __name__ == "__main__":
    main()
