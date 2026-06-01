"""deepseek_tester.py — Test execution + log parsing.

Propósito: ejecutar tests (cuando aplicable), parsear logs UEFN Output Log o
test framework outputs, emitir verdict PASS / FAIL / NOT_EXECUTABLE / INCONCLUSIVE.

NUNCA fabrica resultados. Si no hay logs reales → reporta NOT_EXECUTABLE.
TEST-GATE humano UEFN sigue siendo OBLIGATORIO — este wrapper solo asiste.

CLI:
    --task-id AR_<id>            (required)
    --log-file PATH              (optional) — archivo log a parsear
    --log-text TEXT              (optional) — log content inline
    --expected-outcome TEXT      (optional) — criterio éxito esperado
    --test-command CMD           (optional) — comando shell a ejecutar (Python/Bun/Rust). NO UEFN.
    --output-file PATH           (optional) — default test_report.md en AR dir
    --max-output-tokens N        (optional, default 393216 = API max)
    --model MODEL                (optional, default deepseek-v4-flash)
    --smoke-test                 (canónico log dummy)

EXIT CODES:
    0 = ok (verdict emitted)
    1 = generic error
    2 = config error
    3 = API error
"""
import argparse
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _deepseek_wrapper_base import WrapperBase, MULTIAGENT_ROOT, AGENT_RUNS_DIR, get_agent_params, resolve_model_for_agent  # noqa: E402
from _common_regex import TASK_ID_RE  # noqa: E402

try:
    from openai import APIError, APIConnectionError, RateLimitError
except ImportError:
    APIError = APIConnectionError = RateLimitError = Exception


# Module-level params load (fail-loud at import per B3.0 <user> decision #5).
_AGENT_PARAMS = get_agent_params("tester")
MAX_LOG_BYTES = _AGENT_PARAMS.get("max_log_bytes", 200 * 1024)
TEST_VERDICTS = tuple(_AGENT_PARAMS.get("test_verdicts", ["PASS", "FAIL", "NOT_EXECUTABLE", "INCONCLUSIVE"]))
TEST_COMMAND_TIMEOUT_SECONDS = _AGENT_PARAMS.get("test_command_timeout_seconds", 300)
PATHS_JSON = MULTIAGENT_ROOT / "config" / "paths.json"


def _resolve_uefn_log_dir() -> Path | None:
    """Read paths.json + expand %LOCALAPPDATA% → absolute Path. None si no configurado."""
    if not PATHS_JSON.exists():
        return None
    try:
        with open(PATHS_JSON, encoding="utf-8") as f:
            config = json.load(f)
        raw = config.get("uefn_output_log")
        if not raw:
            return None
        expanded = os.path.expandvars(raw)
        p = Path(expanded)
        return p if p.exists() else None
    except (json.JSONDecodeError, OSError):
        return None


def _pick_latest_uefn_log(log_dir: Path) -> Path | None:
    """Glob *.log in log_dir, return mtime-newest. None if dir empty."""
    candidates = list(log_dir.glob("*.log"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


SYSTEM_PROMPT = (
    "Eres un test analyzer. Recibes log de test execution + criterio esperado y "
    "emites verdict.\n\n"
    "REGLAS INQUEBRANTABLES:\n"
    "1. NUNCA fabriques resultado. Si log es vacío/missing/no concluyente → NOT_EXECUTABLE.\n"
    "2. Verdicts permitidos: PASS, FAIL, NOT_EXECUTABLE, INCONCLUSIVE.\n"
    "3. PASS solo si log contiene EVIDENCIA EXPLÍCITA de éxito vs expected-outcome.\n"
    "4. FAIL solo si log muestra error/exception/test failed.\n"
    "5. NOT_EXECUTABLE = falta entorno (UEFN no abierto, dependency missing, etc.).\n"
    "6. INCONCLUSIVE = log presente pero ambiguo (no permite decidir PASS/FAIL).\n"
    "7. Cita lines exactas del log (line: <num>: <content>) como evidencia.\n"
    "8. NO inventes 'pasos sugeridos para fixear' — eso es trabajo del implementer.\n\n"
    "Formato output (markdown):\n"
    "# Test Report — <task_id>\n"
    "**Verdict**: PASS|FAIL|NOT_EXECUTABLE|INCONCLUSIVE\n"
    "## Evidencia (lines citadas del log)\n## Detalle del análisis\n## Recomendación al root\n"
    "Estilo: caveman, bullets, sin filler. Output max {max_tokens} tokens."
)


class DeepSeekTester(WrapperBase):

    def __init__(self):
        super().__init__(wrapper_name="deepseek_tester")
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

    def _resolve_log(self) -> str:
        """Resolves log content from --log-file, --log-text, --test-command, or --uefn-log-auto-discover."""
        a = self.args
        if a.log_text:
            return a.log_text[:MAX_LOG_BYTES]
        if a.uefn_log_auto_discover:
            # Auto-discover most recent UEFN log via paths.json
            log_dir = _resolve_uefn_log_dir()
            if log_dir is None:
                self._emit_result(
                    status="error",
                    summary="uefn_output_log no configurado o dir no existe",
                    result={"paths_json": str(PATHS_JSON)},
                    error="paths.json missing uefn_output_log key or path does not exist on disk",
                    exit_code=1,
                )
            latest = _pick_latest_uefn_log(log_dir)
            if latest is None:
                self._emit_result(
                    status="error",
                    summary=f"no *.log files in {log_dir}",
                    result={"log_dir": str(log_dir)},
                    error=f"empty UEFN log dir: {log_dir}",
                    exit_code=1,
                )
            self._log("INFO", f"uefn-log-auto-discover: picked {latest} (mtime newest)")
            a.log_file = str(latest)  # mutate for downstream audit
        if a.log_file:
            log_path = Path(a.log_file)
            if not log_path.exists():
                self._emit_result(
                    status="error",
                    summary=f"log-file not found: {log_path}",
                    result=None,
                    error=f"--log-file does not exist: {log_path}",
                    exit_code=1,
                )
            try:
                content = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                self._emit_result(
                    status="error",
                    summary=f"read log failed: {log_path}",
                    result=None,
                    error=f"OSError reading {log_path}: {e}",
                    exit_code=1,
                )
            return content[-MAX_LOG_BYTES:] if len(content) > MAX_LOG_BYTES else content
        if a.test_command:
            # Execute test command, capture stdout+stderr
            try:
                result = subprocess.run(
                    a.test_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=TEST_COMMAND_TIMEOUT_SECONDS,
                )
                combined = f"--- STDOUT ---\n{result.stdout}\n--- STDERR ---\n{result.stderr}\n--- EXIT: {result.returncode} ---"
                return combined[:MAX_LOG_BYTES]
            except subprocess.TimeoutExpired:
                return "--- TEST COMMAND TIMEOUT (300s) ---"
            except Exception as e:
                return f"--- TEST COMMAND ERROR: {type(e).__name__}: {e} ---"
        return ""  # ninguna fuente de log

    def _resolve_output_path(self) -> Path:
        if self.args.output_file:
            return Path(self.args.output_file)
        return AGENT_RUNS_DIR / self.args.task_id / "test_report.md"

    def _build_user_prompt(self, log_content: str) -> str:
        parts = [
            f"TASK_ID: {self.args.task_id}",
            f"EXPECTED OUTCOME: {self.args.expected_outcome or '(not specified — infer from context)'}",
            "",
            "LOG CONTENT:",
            "```",
            log_content if log_content else "(empty log — possibly NOT_EXECUTABLE)",
            "```",
            "",
            "Emit verdict ahora siguiendo formato system prompt.",
        ]
        return "\n".join(parts)

    def run(self) -> None:
        a = self.args
        self._validate_task_id(a.task_id)

        log_content = self._resolve_log()

        output_path = self._resolve_output_path()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Early exit: empty log AND no test command → NOT_EXECUTABLE without API call
        if not log_content and not a.test_command:
            verdict_text = (
                f"# Test Report — {a.task_id}\n\n"
                f"**Verdict**: NOT_EXECUTABLE\n\n"
                f"## Evidencia\n_(ninguna — log no provisto, test-command no provisto)_\n\n"
                f"## Detalle\nTester invocado sin fuentes de log ni comando ejecutable. "
                f"TEST-GATE humano UEFN obligatorio para este AR.\n\n"
                f"## Recomendación\n<user> ejecuta test manual en UEFN editor y pasa output log "
                f"vía --log-text o --log-file en re-invocación.\n"
            )
            output_path.write_text(verdict_text, encoding="utf-8")
            self._emit_result(
                status="ok",
                summary=f"NOT_EXECUTABLE (no log source). Report: {output_path}",
                result={
                    "output_file": str(output_path),
                    "verdict": "NOT_EXECUTABLE",
                    "deepseek_called": False,
                },
                exit_code=0,
            )

        system_prompt = SYSTEM_PROMPT.format(max_tokens=a.max_output_tokens)
        user_prompt = self._build_user_prompt(log_content)
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
            self._emit_result(status="error", summary="rate limit", result=None, error=f"RateLimitError: {e}", exit_code=3)
        except APIConnectionError as e:
            self._emit_result(status="error", summary="connection error", result=None, error=f"APIConnectionError: {e}", exit_code=1)
        except APIError as e:
            self._emit_result(status="error", summary="API error", result=None, error=f"APIError: {e}", exit_code=1)

        # Extract verdict from completion (first match)
        verdict = "INCONCLUSIVE"
        m = re.search(r"\*\*Verdict\*\*:\s*(PASS|FAIL|NOT_EXECUTABLE|INCONCLUSIVE)", completion)
        if m:
            verdict = m.group(1)

        output_path.write_text(completion, encoding="utf-8")
        output_bytes = len(completion.encode("utf-8"))
        self._log("INFO", f"test report written: {output_path} ({output_bytes} bytes), verdict={verdict}")

        audit_path = self._build_audit_path(a.task_id)
        audit_content = (
            f"# Tester audit — task_id `{a.task_id}`\n\n"
            f"## Inputs\n- log_file: `{a.log_file}`\n- log_text: {'inline' if a.log_text else 'none'}\n"
            f"- test_command: `{a.test_command}`\n- expected_outcome: `{a.expected_outcome}`\n- output: `{output_path}`\n\n"
            f"## Log content (truncated 5000 chars)\n```\n{log_content[:5000]}\n```\n\n"
            f"## System prompt\n```\n{system_prompt}\n```\n\n"
            f"## User prompt\n```\n{user_prompt}\n```\n\n"
            f"## Completion (verdict={verdict})\n\n{completion}\n"
        )
        self._write_audit(audit_path, audit_content)

        self._emit_result(
            status="ok",
            summary=f"test report verdict={verdict}: {output_path}",
            result={
                "output_file": str(output_path),
                "output_bytes": output_bytes,
                "verdict": verdict,
                "deepseek_called": True,
            },
            audit_path=audit_path,
            exit_code=0,
        )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="deepseek_tester",
        description="Test analyzer — parse logs, emit verdict.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke-test", action="store_true")
    mode.add_argument("--task-id", help="AR_<id>")
    p.add_argument("--log-file", help="path to log file")
    p.add_argument("--log-text", help="inline log content")
    p.add_argument("--expected-outcome", help="criterio éxito esperado")
    p.add_argument("--test-command", help="shell command a ejecutar (NO UEFN)")
    p.add_argument("--uefn-log-auto-discover", action="store_true",
                   help="auto-discover most recent *.log in paths.json uefn_output_log dir "
                        "(expandiendo %%LOCALAPPDATA%%)")
    p.add_argument("--output-file", help="override default test_report.md")
    p.add_argument("--max-output-tokens", type=int, default=None,
                   help="Max output tokens. Default None = read from agents.json params.tester.max_output_tokens.")
    p.add_argument("--model", default=None, help="DeepSeek model. Default None = resolved via agents.json tier.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.smoke_test:
        smoke = _AGENT_PARAMS["smoke"]
        args.task_id = smoke["task_id"]
        args.log_text = smoke["log_text_dummy"]
        args.expected_outcome = smoke["expected_outcome"]
        args.log_file = None
        args.test_command = None
        args.uefn_log_auto_discover = False
        args.output_file = None
        args.max_output_tokens = smoke["max_tokens"]
        # Smoke uses flash intentionally — validates pipeline mechanics, not output quality. Runtime defaults to pro.
        args.model = smoke["model"]
    else:
        if args.model is None:
            args.model = resolve_model_for_agent("tester")
        if args.max_output_tokens is None:
            args.max_output_tokens = _AGENT_PARAMS.get("max_output_tokens", 65536)

    wrapper = DeepSeekTester()
    wrapper.args = args
    try:
        wrapper.run()
    except SystemExit:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        wrapper._log("ERROR", f"unexpected exception: {e}")
        wrapper._emit_result(
            status="error",
            summary=f"Unexpected error: {type(e).__name__}",
            result=None,
            error={"type": type(e).__name__, "message": str(e), "traceback": tb},
            exit_code=1,
        )


if __name__ == "__main__":
    main()
