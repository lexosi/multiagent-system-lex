"""deepseek_doc_writer.py — Grunt-work doc generator backed by DeepSeek API.

Propósito: generar documentación a partir de spec + (opcional) template.
Soporta tipos: postmortem, daily-log, tech-debt, api-doc, agent-run-final-report,
bugs-summary-append, generic.

CLI:
    --task-id AR_<id>            (required) — regex ^AR_[A-Za-z0-9_-]+$
    --doc-type TYPE              (required) — uno de DOC_TYPES (postmortem|...)
    --spec-file PATH             (required) — archivo .md con la spec/contexto
    --output-template PATH       (optional) — plantilla base .md
    --output-file PATH           (required) — dónde escribir el doc generado
    --force                      (optional) — sobrescribir output-file si existe
    --append                     (optional) — append al output-file existente
                                    (mutually exclusive con --force).
                                    Modo obligatorio para doc-type bugs-summary-append.
    --max-output-tokens N        (optional, default 393216 = API max)
    --model MODEL                (optional, default deepseek-v4-flash)
    --smoke-test                 — caso canónico minimal

Output: JSON envelope en stdout (ver _deepseek_wrapper_base.py).
Audit:  <root>/docs/agent_runs/<task_id>/deepseek_doc_writer_<UTCstamp>.md
"""
import argparse
import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _deepseek_wrapper_base import WrapperBase, get_agent_params, resolve_model_for_agent  # noqa: E402
from _common_regex import TASK_ID_RE  # noqa: E402

try:
    from openai import APIError, APIConnectionError, RateLimitError
except ImportError:
    APIError = APIConnectionError = RateLimitError = Exception


# Module-level params load (fail-loud at import per B3.0 <user> decision #5).
_AGENT_PARAMS = get_agent_params("doc_writer")
MAX_INPUT_BYTES = _AGENT_PARAMS.get("max_input_bytes", 500 * 1024)
DOC_TYPES = ("postmortem", "daily-log", "tech-debt", "api-doc", "agent-run-final-report", "bugs-summary-append", "generic")
APPEND_ONLY_DOC_TYPES = ("bugs-summary-append",)


SYSTEM_PROMPTS = {
    "postmortem": (
        "Eres un technical writer. Genera un postmortem en español siguiendo el "
        "template si se proporciona. Estructura típica: contexto → trigger → root "
        "cause → impacto → fix → lecciones. Estilo: caveman (sin relleno), bullets "
        "concisos, tablas si aplica. Output máximo {max_tokens} tokens. "
        "Si la spec no cubre alguna sección del template, escribe "
        "'_(pendiente — completar manualmente)_'."
    ),
    "daily-log": (
        "Eres un technical writer. Genera un daily log en español siguiendo "
        "convención DL_YYYY-MM-DD_<TICKET>_<author>.md. Estructura: sprints cerrados "
        "→ commits del día → archivos tocados → notas/bloqueos. Estilo: bullets cortos. "
        "Si template se proporciona, respetar bloques AUTO vs MANUAL. Output máximo "
        "{max_tokens} tokens."
    ),
    "tech-debt": (
        "Eres un technical writer. Genera ticket de deuda técnica formato "
        "TD-NNN-<short-slug>.md en español. Estructura: location → pattern → "
        "why it's debt → suggested fix → priority (High/Med/Low) → discovered during. "
        "Estilo conciso. Output máximo {max_tokens} tokens."
    ),
    "api-doc": (
        "Eres un technical writer especializado en API docs.\n\n"
        "REGLAS INQUEBRANTABLES (anti-hallucination):\n"
        "1. NO inventes funciones, métodos, parámetros, return types ni excepciones "
        "que no aparezcan EXPLÍCITAMENTE en spec o template.\n"
        "2. Si la spec menciona una función sin firma completa, escribe "
        "'_(firma incompleta en spec — verificar contra código fuente)_' en lugar de "
        "adivinar.\n"
        "3. Si la spec no documenta una excepción posible, NO la inventes.\n"
        "4. Si dudas sobre comportamiento de un método, escribe "
        "'_(comportamiento no especificado en spec)_'.\n"
        "5. Cada bloque de código de ejemplo debe ser cita literal de la spec o "
        "claramente marcado como '_(ejemplo ilustrativo, no testeado)_'.\n\n"
        "Estilo: caveman, bullets concisos, tablas para listas de params/returns. "
        "Output máximo {max_tokens} tokens."
    ),
    "agent-run-final-report": (
        "Eres un technical writer. Genera el final report estructurado de un Agent Run.\n\n"
        "Estructura obligatoria:\n"
        "1. **Resumen** (2-3 líneas: qué se hizo, resultado)\n"
        "2. **Status final** (closed-ok / closed-failed / closed-partial)\n"
        "3. **Hipótesis probadas** (lista: hipótesis, evidencia, resultado)\n"
        "4. **Cambios aplicados** (lista: archivo, qué cambió, por qué)\n"
        "5. **Verificación** (test results, output log evidence, etc.)\n"
        "6. **Tech debt detectada** (refs a TD-* tickets generados)\n"
        "7. **Lecciones para knowledge base** (qué debe leer knowledge-curator)\n"
        "8. **Tiempo total** (estimación)\n\n"
        "Estilo: caveman, bullets, sin relleno. Si una sección no aplica, "
        "'_(no aplica)_'. NO inventes datos. Solo lo que esté en la spec. "
        "Output máximo {max_tokens} tokens."
    ),
    "bugs-summary-append": (
        "Eres un technical writer. Genera UNA SOLA entrada nueva para append a un "
        "archivo `<Project>_bugs_fixes_summary.md` existente.\n\n"
        "REGLAS INQUEBRANTABLES:\n"
        "1. Output = SOLO la entrada nueva. NO regeneres el archivo. NO incluyas "
        "header del archivo, ni front matter, ni separador `---` previo.\n"
        "2. Empieza el output con `## <N>. <Title>` donde `<N>` = último número en "
        "el archivo existente + 1 (deduce del SUMMARY EXISTING que recibes en spec).\n"
        "3. Estructura obligatoria de la entrada (4 bullets exactos):\n"
        "   - `- **AR**: \\`AR_<id>\\``\n"
        "   - `- **Bug**: <descripción 1-2 líneas máx>`\n"
        "   - `- **Causa**: <root cause + archivo:línea si aplica>`\n"
        "   - `- **Fix**: <descripción concisa, opcional bloque diff>`\n"
        "4. Estilo: caveman, sin relleno, máximo 10 líneas por entrada.\n"
        "5. NO inventes contenido. Solo extrae de la spec (final_report.md).\n"
        "6. Si la spec menciona varios bugs en un AR, agrúpalos como UN entry con "
        "subbullets, NO generes múltiples entries.\n"
        "7. NO añadas separador `---` ni líneas en blanco extra al final.\n\n"
        "Output máximo {max_tokens} tokens."
    ),
    "generic": (
        "Eres un technical writer. Genera documentación en español según spec + "
        "template (si se proporciona). Estilo: bullets, tablas para decisiones, sin "
        "relleno. Output máximo {max_tokens} tokens."
    ),
}


class DeepSeekDocWriter(WrapperBase):
    """DocWriter wrapper — generación de docs a partir de spec + opcional template."""

    def __init__(self):
        super().__init__(wrapper_name="deepseek_doc_writer")
        self.args = None  # Set por main() antes de run().
        self._selftest_prompt_construction()

    def _selftest_prompt_construction(self) -> None:
        """Verify all SYSTEM_PROMPTS .format() calls succeed for every doc-type."""
        for key, prompt in SYSTEM_PROMPTS.items():
            try:
                _ = prompt.format(max_tokens=1)
            except (KeyError, IndexError, ValueError) as e:
                self._emit_result(
                    status="error",
                    summary=f"prompt construction failed for doc-type {key}: {type(e).__name__}",
                    result={"doc_type": key, "prompt_key": "SYSTEM_PROMPTS"},
                    error={"type": type(e).__name__, "message": str(e), "doc_type": key},
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

    def _validate_doc_type(self, doc_type: str) -> None:
        if doc_type not in DOC_TYPES:
            self._emit_result(
                status="error",
                summary=f"invalid doc-type: {doc_type}",
                result={"valid_types": list(DOC_TYPES)},
                error=f"doc-type must be one of {DOC_TYPES}, got: {doc_type!r}",
                exit_code=1,
            )

    def _validate_input_file(self, path: Path, label: str) -> None:
        if not path.exists():
            self._emit_result(
                status="error",
                summary=f"{label} not found: {path}",
                result=None,
                error=f"{label} does not exist: {path}",
                exit_code=1,
            )
        if path.suffix.lower() != ".md":
            self._emit_result(
                status="error",
                summary=f"{label} must be .md: {path}",
                result=None,
                error=f"{label} must have .md extension, got: {path.suffix}",
                exit_code=1,
            )

    def _validate_output_file(self, path: Path, force: bool, append: bool = False) -> None:
        if not path.parent.exists():
            self._emit_result(
                status="error",
                summary=f"output parent dir does not exist: {path.parent}",
                result=None,
                error=f"output parent dir does not exist: {path.parent}",
                exit_code=1,
            )
        if append:
            if not path.exists():
                self._emit_result(
                    status="error",
                    summary=f"--append requires output-file to exist: {path}",
                    result=None,
                    error=f"output-file does not exist (cannot append): {path}",
                    exit_code=1,
                )
            return
        if path.exists() and not force:
            self._emit_result(
                status="error",
                summary=f"output file already exists (use --force to overwrite): {path}",
                result={"existing_file": str(path)},
                error=f"output file exists and --force not set: {path}",
                exit_code=1,
            )

    def _load_text(self, path: Path, label: str) -> str:
        """Read UTF-8 .md file. Bails out on UnicodeDecodeError."""
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            self._emit_result(
                status="error",
                summary=f"non-UTF8 {label}: {path}",
                result=None,
                error=f"UnicodeDecodeError on {path}: {e}",
                exit_code=1,
            )

    def _check_input_size(self, spec_text: str, template_text: str) -> None:
        total = len(spec_text.encode("utf-8")) + len(template_text.encode("utf-8"))
        if total > MAX_INPUT_BYTES:
            msg = (
                f"input size exceeded limit ({MAX_INPUT_BYTES} bytes). "
                f"spec + template = {total} bytes. split request into smaller batches."
            )
            self._emit_result(
                status="error",
                summary=msg,
                result={"accumulated_bytes": total, "limit_bytes": MAX_INPUT_BYTES},
                error=msg,
                exit_code=1,
            )

    def _build_user_prompt(
        self,
        doc_type: str,
        spec_text: str,
        template_text: str,
        existing_summary_tail: str = "",
    ) -> str:
        parts = [f"DOC TYPE: {doc_type}", "", f"SPEC:\n{spec_text}"]
        if template_text:
            parts += ["", f"OUTPUT TEMPLATE:\n{template_text}"]
        if existing_summary_tail:
            parts += ["", f"SUMMARY EXISTING (tail, para deducir próximo N + formato):\n{existing_summary_tail}"]
        parts += ["", "Genera el documento ahora."]
        return "\n".join(parts)

    def _build_audit_content(
        self,
        doc_type: str,
        spec_path: Path,
        template_path: Path | None,
        output_path: Path,
        system_prompt: str,
        user_prompt: str,
        completion: str,
        model: str,
        max_tokens: int,
    ) -> str:
        tpl_line = f"- template: `{template_path}`" if template_path else "- template: _(none)_"
        return (
            f"# DocWriter audit — task_id `{self.args.task_id}`\n\n"
            f"## Inputs\n\n"
            f"- doc_type: `{doc_type}`\n"
            f"- spec: `{spec_path}`\n"
            f"{tpl_line}\n"
            f"- output: `{output_path}`\n\n"
            f"## Model\n\n- requested: `{model}`\n- max_output_tokens: {max_tokens}\n\n"
            f"## System prompt\n\n```\n{system_prompt}\n```\n\n"
            f"## User prompt (full)\n\n```\n{user_prompt}\n```\n\n"
            f"## Completion\n\n{completion}\n"
        )

    def run(self) -> None:
        a = self.args
        self._validate_task_id(a.task_id)
        self._validate_doc_type(a.doc_type)
        # bugs-summary-append exige --append.
        if a.doc_type in APPEND_ONLY_DOC_TYPES and not a.append:
            self._emit_result(
                status="error",
                summary=f"doc-type {a.doc_type} requires --append flag",
                result=None,
                error=f"doc-type {a.doc_type} is append-only, must use --append (not --force or default)",
                exit_code=1,
            )
        if a.append and a.force:
            self._emit_result(
                status="error",
                summary="--append and --force are mutually exclusive",
                result=None,
                error="cannot use --append and --force together",
                exit_code=1,
            )
        spec_path = Path(a.spec_file)
        self._validate_input_file(spec_path, "spec-file")
        template_path = Path(a.output_template) if a.output_template else None
        if template_path:
            self._validate_input_file(template_path, "output-template")
        output_path = Path(a.output_file)
        self._validate_output_file(output_path, a.force, a.append)

        spec_text = self._load_text(spec_path, "spec-file")
        template_text = self._load_text(template_path, "output-template") if template_path else ""

        # En modo append, también leer tail del archivo existente para que el modelo
        # vea formato + último N + el sentido del archivo.
        existing_summary_tail = ""
        if a.append:
            full_existing = self._load_text(output_path, "output-file (append target)")
            # Tail: últimos ~4000 bytes (ya cubre formato + última entry, evita saturar prompt).
            existing_summary_tail = full_existing[-4000:] if len(full_existing) > 4000 else full_existing

        self._check_input_size(spec_text, template_text)

        audit_path = self._build_audit_path(a.task_id)
        system_prompt = SYSTEM_PROMPTS[a.doc_type].format(max_tokens=a.max_output_tokens)
        user_prompt = self._build_user_prompt(a.doc_type, spec_text, template_text, existing_summary_tail)
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

        # Write generated doc to output-file (UTF-8 no BOM).
        if completion is None:
            self._emit_result(
                status="error",
                summary="DeepSeek returned empty completion",
                result=None,
                error="completion is None (empty response from API). Check DeepSeek pricing/quota or finish_reason.",
                exit_code=1,
            )
        if a.append:
            # Append con separación: \n\n + completion. Asegura blank line antes de
            # la nueva entrada para no pegar al último char del archivo existente.
            existing = self._load_text(output_path, "output-file (append re-read)")
            # Strip trailing whitespace y reañadir exactamente "\n\n" antes del append.
            existing_trimmed = existing.rstrip()
            new_content = existing_trimmed + "\n\n" + completion.lstrip()
            # Si completion no termina en newline, lo añade para limpieza POSIX.
            if not new_content.endswith("\n"):
                new_content += "\n"
            if not getattr(self.args, "no_write", False):
                output_path.write_text(new_content, encoding="utf-8")
            output_bytes = len(completion.encode("utf-8"))
            self._log("INFO", f"appended to: {output_path} (+{output_bytes} bytes)")
        else:
            if not getattr(self.args, "no_write", False):
                output_path.write_text(completion, encoding="utf-8")
            output_bytes = len(completion.encode("utf-8"))
            self._log("INFO", f"output written: {output_path} ({output_bytes} bytes)")

        # Write audit
        audit_content = self._build_audit_content(
            doc_type=a.doc_type,
            spec_path=spec_path,
            template_path=template_path,
            output_path=output_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            completion=completion,
            model=a.model,
            max_tokens=a.max_output_tokens,
        )
        self._write_audit(audit_path, audit_content)

        self._emit_result(
            status="ok",
            summary=f"{a.doc_type} {'appended to' if a.append else 'generado en'}: {output_path}",
            result={
                "output_file": str(output_path),
                "output_bytes": output_bytes,
                "doc_type": a.doc_type,
                "template_used": str(template_path) if template_path else None,
                "mode": "append" if a.append else "write",
            },
            audit_path=audit_path,
            exit_code=0,
        )


def _load_paths_for_smoke() -> dict:
    """Load paths.json for smoke test. Fail clearly if missing or malformed."""
    paths_json = Path(r"<repo_root>\config\paths.json")
    if not paths_json.exists():
        raise RuntimeError("smoke test needs <repo_root>\\config\\paths.json to exist")
    with open(paths_json, encoding="utf-8") as f:
        return json.load(f)


def _prepare_smoke_inputs() -> tuple[str, str, str]:
    """Set up spec + template + output paths for smoke test.

    Creates a dummy spec file inside the agent_runs dir for smoke task.
    Returns (spec_file, output_template, output_file).
    """
    paths = _load_paths_for_smoke()
    cross_lang = paths.get("domains", {}).get("cross-language")
    if not cross_lang:
        raise RuntimeError("smoke test needs domains.cross-language in paths.json")
    template_path = Path(cross_lang) / "workflow-POSTMORTEMS_template.md"
    if not template_path.exists():
        raise RuntimeError(f"smoke test template not found: {template_path}")

    multiagent_root = paths.get("multiagent_root")
    if not multiagent_root:
        raise RuntimeError("smoke test needs multiagent_root in paths.json")

    smoke_dir = Path(multiagent_root) / "docs" / "agent_runs" / "AR_smoke_doc_writer_001"
    smoke_dir.mkdir(parents=True, exist_ok=True)

    spec_path = smoke_dir / "_spec_input.md"
    spec_path.write_text(
        "# Spec dummy para smoke test doc_writer\n\n"
        "## Incidente\n\n"
        "Smoke test del wrapper deepseek_doc_writer.py (2026-05-14, Fase 1B).\n\n"
        "## Síntoma\n\n"
        "N/A — no es un incidente real, solo verificación de pipeline.\n\n"
        "## Resolución esperada\n\n"
        "Wrapper genera postmortem siguiendo template, sin alucinar contenido.\n",
        encoding="utf-8",
    )
    output_path = smoke_dir / "_output_generated.md"
    if output_path.exists():
        output_path.unlink()  # Clean previous smoke output.
    return str(spec_path), str(template_path), str(output_path)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="deepseek_doc_writer",
        description="Generate documentation from spec + optional template via DeepSeek.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke-test", action="store_true",
                      help="run a minimal canonical case")
    mode.add_argument("--task-id", help="AR_<id> task identifier")
    p.add_argument("--doc-type", choices=DOC_TYPES)
    p.add_argument("--spec-file", help="path to .md spec/context file")
    p.add_argument("--output-template", help="optional path to .md template")
    p.add_argument("--output-file", help="path where generated doc is written")
    p.add_argument("--force", action="store_true",
                   help="overwrite output-file if it exists")
    p.add_argument("--append", action="store_true",
                   help="append to existing output-file (mutually exclusive con --force, "
                        "required para doc-type bugs-summary-append)")
    p.add_argument("--max-output-tokens", type=int, default=None,
                   help="Max output tokens. Default None = read from agents.json params.doc_writer.max_output_tokens.")
    p.add_argument("--model", default=None, help="DeepSeek model. Default None = resolved via agents.json tier.")
    p.add_argument("--no-write", action="store_true",
                   help="Skip writing output_file (smoke validation mode — avoids polluting productive namespace). Audit .md from WrapperBase still written.")
    args = p.parse_args()
    if not args.smoke_test:
        missing = [k for k in ("doc_type", "spec_file", "output_file") if not getattr(args, k)]
        if missing:
            p.error(f"missing required arg(s) in normal mode: {missing}")
    return args


def main() -> None:
    args = _parse_args()
    if args.smoke_test:
        smoke = _AGENT_PARAMS["smoke"]
        args.task_id = smoke["task_id"]
        args.doc_type = smoke["doc_type"]
        args.spec_file, args.output_template, args.output_file = _prepare_smoke_inputs()
        args.max_output_tokens = smoke["max_tokens"]
        # Smoke uses flash intentionally — validates pipeline mechanics, not output quality. Runtime defaults to pro.
        args.model = smoke["model"]
        args.force = smoke["force"]
        # TD#1 fix B6: smoke implies no-write — avoids polluting productive docs/agent_runs/ namespace.
        args.no_write = True
    else:
        if args.model is None:
            args.model = resolve_model_for_agent("doc_writer")
        if args.max_output_tokens is None:
            args.max_output_tokens = _AGENT_PARAMS.get("max_output_tokens", 65536)

    wrapper = DeepSeekDocWriter()
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
            error={
                "type": type(e).__name__,
                "message": str(e),
                "traceback": tb,
            },
            exit_code=1,
        )


if __name__ == "__main__":
    main()
