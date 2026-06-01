"""deepseek_tech_debt_scanner.py — Scan code/docs for tech debt, generate TD-NNN tickets.

Propósito: detectar deuda técnica CONCRETA y generar tickets TD-NNN.md.
NO incluye: estilo, naming, sugerencias subjetivas, tareas inventadas.
SÍ incluye: TODOs/FIXMEs sin ticket, inconsistencias, antipatrones conocidos,
            code paths muertos, falta de tests donde claramente debería haberlos.

CLI:
    --task-id AR_<id>            (required)
    --scan-path PATH             (required) — folder o archivo a escanear
    --scan-mode MODE             (required) — code | docs | mixed
    --severity-threshold SEV     (optional, default medium) — low|medium|high|critical
    --max-findings N             (optional, default 20) — cap tickets generados
    --output-dir PATH            (optional) — default <root>/docs/tech_debt/
    --max-files N                (optional, default 50) — cap files escaneados en folder mode
    --model MODEL                (optional, default deepseek-v4-flash)
    --smoke-test                 — caso canónico minimal
"""
import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _deepseek_wrapper_base import WrapperBase, MULTIAGENT_ROOT, get_agent_params, resolve_model_for_agent  # noqa: E402
from _common_regex import TASK_ID_RE  # noqa: E402

try:
    from openai import APIError, APIConnectionError, RateLimitError
except ImportError:
    APIError = APIConnectionError = RateLimitError = Exception


# Module-level params load (fail-loud at import per B3.0 Lexosi decision #5).
_AGENT_PARAMS = get_agent_params("tech_debt_scanner")
SCAN_MODES = ("code", "docs", "mixed")
SEVERITY_LEVELS = ("low", "medium", "high", "critical")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_LEVELS)}
DEFAULT_OUTPUT_SUBDIR = "docs/tech_debt"

CODE_EXTS = tuple(_AGENT_PARAMS.get("code_exts", [".py", ".verse", ".rs", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".c", ".cpp", ".h", ".hpp"]))
DOCS_EXTS = tuple(_AGENT_PARAMS.get("docs_exts", [".md"]))
MAX_FILE_BYTES = _AGENT_PARAMS.get("max_file_bytes", 100 * 1024)
MIN_DESCRIPTION_CHARS = _AGENT_PARAMS.get("min_description_chars", 30)
ESTIMATED_COST_PER_FILE_USD = _AGENT_PARAMS.get("estimated_cost_per_file_usd", 0.005)


SCANNER_SYSTEM_PROMPT = (
    "Eres un tech-debt scanner experto. Detecta deuda técnica CONCRETA en el código/doc "
    "que se te proporciona.\n\n"
    "REGLAS INQUEBRANTABLES (anti-sycophancy / anti-hallucination):\n"
    "1. NO incluyas comentarios de estilo (variable naming, formatting, spacing).\n"
    "2. NO incluyas sugerencias subjetivas de mejora (\"podría refactorizarse\").\n"
    "3. NO inventes findings. Solo lo que veas literal en el contenido.\n"
    "4. NO emitas findings vagos sin file+line+description concreta.\n"
    "5. Si el archivo está limpio, devuelve array vacío [].\n"
    "6. SCOPE limitado a archivo. NO reportes \"undefined identifier\" sin verificar cross-file. "
    "Si un símbolo (clase, función, field, message) NO está definido en el archivo escaneado pero "
    "el código asume su existencia → asume que está definido en otro archivo del mismo módulo "
    "(válido para Verse `<internal>`, Python module imports, Rust `pub(crate)`, etc.). "
    "SOLO reporta undefined si el símbolo es claramente local o privado-archivo.\n"
    "7. VERSE COMMENT SYNTAX: `<# ... #>` es block-comment multi-línea. TODO código dentro de "
    "`<# ... #>` es comentario INTENCIONAL, NO bug. NO emitas findings sobre líneas dentro "
    "de bloques `<# ... #>`. Verifica si la línea reportada está enclosed por estos delimitadores.\n"
    "8. INTERFACE/TRAIT INHERITANCE: si una clase declara `class<concrete>(InterfaceName)` (Verse), "
    "`impl Trait for X` (Rust), `extends InterfaceName` (Java/TS), `: BaseClass` (C#), etc. — "
    "los fields/métodos heredados están en scope. NO reportes undefined si símbolo viene de interface/trait padre.\n\n"
    "SÍ incluye:\n"
    "- TODOs / FIXMEs / XXX explícitos sin ticket asociado.\n"
    "- Inconsistencias entre archivos (refs rotas, naming divergente).\n"
    "- Antipatrones conocidos: deep nesting (>4 niveles), function bombs (>100 LOC), "
    "magic numbers sin constante nombrada.\n"
    "- Dependencias obsoletas, imports muertos.\n"
    "- Falta de tests donde claramente debería haberlos (función crítica sin test_*).\n"
    "- En docs: refs a archivos que no existen, secciones marcadas como deprecated.\n\n"
    "OUTPUT FORMAT (estricto):\n"
    "Responde SOLO con un JSON array. Cada finding tiene este schema:\n"
    "{{\n"
    '  "severity": "low" | "medium" | "high" | "critical",\n'
    '  "title": "<short title, max 80 chars>",\n'
    '  "file": "<path relativo o absoluto recibido>",\n'
    '  "line": <int o null si no aplica>,\n'
    '  "description": "<descripción concreta, máx 300 chars>",\n'
    '  "suggested_fix": "<fix accionable, máx 200 chars>"\n'
    "}}\n\n"
    "Sin texto fuera del JSON. Si no hay findings, devuelve: []\n"
    "Máximo {max_findings_per_call} findings por llamada."
)


class DeepSeekTechDebtScanner(WrapperBase):
    """Tech-debt scanner — detecta deuda en code/docs, genera TD-NNN tickets."""

    DEFAULT_TEMPERATURE = _AGENT_PARAMS.get("default_temperature", 0.2)  # bajo para consistencia clasificación severity.

    def __init__(self):
        super().__init__(wrapper_name="deepseek_tech_debt_scanner")
        self.args = None
        # Accumulators populated during scan loop, surfaced in envelope.warnings.
        self._run_warnings: list[str] = []
        self._truncated_files: list[tuple[str, int]] = []  # (path, original_bytes)
        self._parse_failed_files: list[str] = []
        self._selftest_prompt_construction()

    def _selftest_prompt_construction(self) -> None:
        """Verify all .format() calls in this wrapper succeed. Catches stray {literals}."""
        try:
            _ = SCANNER_SYSTEM_PROMPT.format(max_findings_per_call=1)
        except (KeyError, IndexError, ValueError) as e:
            self._emit_result(
                status="error",
                summary=f"prompt construction failed: {type(e).__name__}",
                result={"prompt": "SCANNER_SYSTEM_PROMPT"},
                error={"type": type(e).__name__, "message": str(e)},
                exit_code=2,
            )

    # ---------- Validación ----------

    def _validate_task_id(self, task_id: str) -> None:
        if not TASK_ID_RE.match(task_id):
            self._emit_result(
                status="error",
                summary=f"invalid task-id: {task_id}",
                result=None,
                error=f"task-id must match ^AR_[A-Za-z0-9_-]+$, got: {task_id!r}",
                exit_code=1,
            )

    def _validate_scan_path(self, path: Path) -> None:
        if not path.exists():
            self._emit_result(
                status="error",
                summary=f"scan-path does not exist: {path}",
                result=None,
                error=f"scan-path not found: {path}",
                exit_code=1,
            )

    def _validate_output_dir(self, path: Path) -> None:
        if not path.parent.exists():
            self._emit_result(
                status="error",
                summary=f"output-dir parent does not exist: {path.parent}",
                result=None,
                error=f"output-dir parent not found: {path.parent}",
                exit_code=1,
            )
        path.mkdir(parents=True, exist_ok=True)

    # ---------- File discovery ----------

    def _ext_filter(self, scan_mode: str) -> tuple:
        if scan_mode == "code":
            return CODE_EXTS
        if scan_mode == "docs":
            return DOCS_EXTS
        return CODE_EXTS + DOCS_EXTS  # mixed

    def _collect_files(self, scan_path: Path, scan_mode: str, max_files: int) -> list[Path]:
        exts = self._ext_filter(scan_mode)
        if scan_path.is_file():
            if scan_path.suffix.lower() in exts:
                return [scan_path]
            self._emit_result(
                status="error",
                summary=f"scan-path file extension not in mode {scan_mode}",
                result={"file": str(scan_path), "valid_exts": list(exts)},
                error=f"file {scan_path.suffix} not in {exts} for scan-mode {scan_mode}",
                exit_code=1,
            )
        # Directory: recursive collection.
        files = []
        for ext in exts:
            files.extend(scan_path.rglob(f"*{ext}"))
        files = sorted(set(files))[:max_files]
        return files

    # ---------- Scanning ----------

    def _next_td_number(self, output_dir: Path) -> int:
        """Find max existing TD-NNN-*.md number in output_dir + 1."""
        max_n = 0
        pattern = re.compile(r"^TD-(\d+)-")
        for f in output_dir.glob("TD-*.md"):
            m = pattern.match(f.name)
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
        return max_n + 1

    def _scan_file(self, file_path: Path, max_findings_per_call: int) -> tuple[list[dict], int]:
        """Scan one file. Returns (findings_list, bytes_read).

        Truncates file content if > MAX_FILE_BYTES (logs warn).
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            self._log("WARN", f"non-UTF8 file, skipping: {file_path}")
            return [], 0
        size = len(content.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            self._log(
                "WARN",
                f"File {file_path} truncated: {size} bytes → {MAX_FILE_BYTES} bytes. "
                f"Findings may miss content beyond cap.",
            )
            self._truncated_files.append((str(file_path), size))
            content = content.encode("utf-8")[:MAX_FILE_BYTES].decode("utf-8", errors="ignore")

        system_prompt = SCANNER_SYSTEM_PROMPT.format(max_findings_per_call=max_findings_per_call)
        user_prompt = f"FILE: {file_path}\n\n=== CONTENT ===\n{content}\n=== END ===\n\nReturn JSON array of findings."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = self._call_deepseek(messages=messages, model=self.args.model, max_tokens=self.args.max_output_tokens)

        # Parse JSON array from response. DeepSeek may wrap in code fences sometimes.
        findings = self._parse_findings_json(response, file_path)
        return findings, size

    def _parse_findings_json(self, response: str, file_path: Path) -> list[dict]:
        """Parse LLM response as JSON array. Tolerant to code-fence wrapping."""
        if response is None:
            self._log(
                "WARN",
                f"LLM response is None for {file_path} (likely empty completion). Skipping file.",
            )
            self._parse_failed_files.append(str(file_path))
            return []
        raw = response.strip()
        # Strip code fences if present.
        if raw.startswith("```"):
            lines = raw.splitlines()
            # Drop first ```... and last ``` if present.
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            preview = raw[:200].replace("\n", "\\n")
            self._log(
                "WARN",
                f"non-JSON response from LLM for {file_path}: {e}. "
                f"Response preview (first 200 chars): {preview!r}. Skipping file (no retry).",
            )
            self._parse_failed_files.append(str(file_path))
            return []
        if not isinstance(data, list):
            self._log("WARN", f"LLM response not a JSON array for {file_path}, got {type(data).__name__}. Skipping.")
            return []
        # Validate each finding has required keys.
        valid = []
        required_keys = ("severity", "title", "file", "description", "suggested_fix")
        for i, finding in enumerate(data):
            if not isinstance(finding, dict):
                self._log("WARN", f"finding {i} for {file_path} not a dict, skipping")
                continue
            missing = [k for k in required_keys if k not in finding]
            if missing:
                self._log("WARN", f"finding {i} for {file_path} missing keys {missing}, skipping")
                continue
            if finding["severity"] not in SEVERITY_LEVELS:
                self._log("WARN", f"finding {i} for {file_path} invalid severity {finding['severity']!r}, skipping")
                continue
            # Anti-sycophancy filter: vague findings with too-short description.
            if not finding.get("description") or len(finding["description"]) < MIN_DESCRIPTION_CHARS:
                self._log(
                    "WARN",
                    f"finding {i} for {file_path} too vague (description <{MIN_DESCRIPTION_CHARS} chars), skipping",
                )
                continue
            valid.append(finding)
        return valid

    def _filter_by_threshold(self, findings: list[dict], threshold: str) -> list[dict]:
        min_rank = SEVERITY_RANK[threshold]
        return [f for f in findings if SEVERITY_RANK.get(f["severity"], -1) >= min_rank]

    def _generate_td_ticket(self, td_number: int, finding: dict, task_id: str, output_dir: Path) -> Path:
        """Write TD-NNN-<slug>.md ticket file. Returns path."""
        slug = re.sub(r"[^a-z0-9-]+", "-", finding["title"].lower()).strip("-")[:40] or "untitled"
        td_id = f"TD-{td_number:03d}"
        path = output_dir / f"{td_id}-{slug}.md"
        if getattr(self.args, "no_write", False):
            return path
        line_info = f" L{finding['line']}" if finding.get("line") else ""
        content = (
            f"# {td_id} — {finding['title']}\n\n"
            f"**Severity**: {finding['severity']}\n"
            f"**Discovered during**: `{task_id}`\n\n"
            f"## Location\n\n"
            f"`{finding['file']}`{line_info}\n\n"
            f"## Description\n\n"
            f"{finding['description']}\n\n"
            f"## Suggested fix\n\n"
            f"{finding['suggested_fix']}\n"
        )
        path.write_text(content, encoding="utf-8")
        return path

    def _build_summary_index(
        self,
        task_id: str,
        scan_path: Path,
        findings: list[dict],
        tickets: list[Path],
        files_scanned: int,
        output_dir: Path,
    ) -> Path:
        """Build TD_SUMMARY_<task_id>.md with table of TDs."""
        summary_path = output_dir / f"TD_SUMMARY_{task_id}.md"
        if getattr(self.args, "no_write", False):
            return summary_path
        rows = []
        for finding, ticket_path in zip(findings, tickets):
            line_info = str(finding["line"]) if finding.get("line") else "—"
            rows.append(
                f"| [{ticket_path.stem}](./{ticket_path.name}) | {finding['severity']} | "
                f"`{finding['file']}` | {line_info} | {finding['title']} |"
            )
        content = (
            f"# Tech-Debt Summary — task_id `{task_id}`\n\n"
            f"- Scan path: `{scan_path}`\n"
            f"- Files scanned: {files_scanned}\n"
            f"- Tickets generated: {len(tickets)}\n"
            f"- Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n"
            f"## Tickets\n\n"
            f"| Ticket | Severity | File | Line | Title |\n"
            f"|---|---|---|---|---|\n"
            + ("\n".join(rows) if rows else "_(no findings above threshold)_")
            + "\n"
        )
        summary_path.write_text(content, encoding="utf-8")
        return summary_path

    def _build_audit_content(
        self,
        scan_path: Path,
        files_scanned: int,
        findings_raw: int,
        findings_filtered: int,
        tickets: list[Path],
        summary_path: Path,
    ) -> str:
        ticket_list = "\n".join(f"- `{p}`" for p in tickets) if tickets else "_(none)_"
        return (
            f"# TechDebtScanner audit — task_id `{self.args.task_id}`\n\n"
            f"## Scan parameters\n\n"
            f"- scan_path: `{scan_path}`\n"
            f"- scan_mode: `{self.args.scan_mode}`\n"
            f"- severity_threshold: `{self.args.severity_threshold}`\n"
            f"- max_findings: {self.args.max_findings}\n"
            f"- max_files: {self.args.max_files}\n\n"
            f"## Results\n\n"
            f"- files_scanned: {files_scanned}\n"
            f"- findings_raw: {findings_raw}\n"
            f"- findings_above_threshold: {findings_filtered}\n"
            f"- tickets_generated: {len(tickets)}\n"
            f"- summary_file: `{summary_path}`\n\n"
            f"## Tickets\n\n{ticket_list}\n"
        )

    # ---------- Entry point ----------

    def run(self) -> None:
        a = self.args
        self._validate_task_id(a.task_id)
        if a.scan_mode not in SCAN_MODES:
            self._emit_result(
                status="error",
                summary=f"invalid scan-mode: {a.scan_mode}",
                result={"valid_modes": list(SCAN_MODES)},
                error=f"scan-mode must be one of {SCAN_MODES}",
                exit_code=1,
            )
        if a.severity_threshold not in SEVERITY_LEVELS:
            self._emit_result(
                status="error",
                summary=f"invalid severity-threshold: {a.severity_threshold}",
                result={"valid_levels": list(SEVERITY_LEVELS)},
                error=f"severity-threshold must be one of {SEVERITY_LEVELS}",
                exit_code=1,
            )

        scan_path = Path(a.scan_path)
        self._validate_scan_path(scan_path)
        output_dir = Path(a.output_dir) if a.output_dir else (MULTIAGENT_ROOT / DEFAULT_OUTPUT_SUBDIR)
        self._validate_output_dir(output_dir)
        audit_path = self._build_audit_path(a.task_id)

        files = self._collect_files(scan_path, a.scan_mode, a.max_files)
        self._log("INFO", f"scanning {len(files)} file(s) in mode {a.scan_mode}")

        # Preview cost warning for large scans.
        if len(files) > 30:
            est_low = len(files) * ESTIMATED_COST_PER_FILE_USD
            est_high = est_low * 3
            self._log(
                "WARN",
                f"folder scan: {len(files)} files queued "
                f"(~${est_low:.2f}-${est_high:.2f} estimated cost). "
                f"Use --max-files=N or Ctrl+C to abort.",
            )

        all_findings: list[dict] = []
        for f in files:
            try:
                findings, _bytes = self._scan_file(f, max_findings_per_call=a.max_findings)
            except RateLimitError as e:
                self._emit_result(
                    status="error",
                    summary="DeepSeek rate limit / quota hit during scan",
                    result={"files_scanned_so_far": len(all_findings)},
                    error=f"RateLimitError on {f}: {e}",
                    exit_code=3,
                )
            except (APIConnectionError, APIError) as e:
                self._log("WARN", f"API error on {f}, skipping file: {type(e).__name__}: {e}")
                continue
            all_findings.extend(findings)

        findings_filtered = self._filter_by_threshold(all_findings, a.severity_threshold)
        # Cap to max_findings.
        findings_filtered = findings_filtered[:a.max_findings]

        # Generate tickets.
        next_n = self._next_td_number(output_dir)
        tickets: list[Path] = []
        for i, finding in enumerate(findings_filtered):
            ticket_path = self._generate_td_ticket(next_n + i, finding, a.task_id, output_dir)
            tickets.append(ticket_path)
            self._log("INFO", f"generated ticket: {ticket_path}")

        summary_path = self._build_summary_index(
            task_id=a.task_id,
            scan_path=scan_path,
            findings=findings_filtered,
            tickets=tickets,
            files_scanned=len(files),
            output_dir=output_dir,
        )

        audit_content = self._build_audit_content(
            scan_path=scan_path,
            files_scanned=len(files),
            findings_raw=len(all_findings),
            findings_filtered=len(findings_filtered),
            tickets=tickets,
            summary_path=summary_path,
        )
        self._write_audit(audit_path, audit_content)

        # Aggregate warnings collected during scan.
        warnings: list[str] = list(self._run_warnings)
        for path, original_bytes in self._truncated_files:
            warnings.append(
                f"file_truncated: {path} ({original_bytes} bytes → {MAX_FILE_BYTES} bytes cap)"
            )
        for path in self._parse_failed_files:
            warnings.append(f"parse_failed: {path}")

        status = "warning" if warnings else "ok"
        summary_text = f"{len(tickets)} tech-debt tickets generated from {scan_path}"
        if warnings:
            summary_text += f" (with {len(warnings)} warning(s))"

        self._emit_result(
            status=status,
            summary=summary_text,
            result={
                "scan_path": str(scan_path),
                "files_scanned": len(files),
                "findings_total": len(all_findings),
                "findings_above_threshold": len(findings_filtered),
                "tickets_generated": [p.name for p in tickets],
                "summary_file": str(summary_path),
                "warnings": warnings,
            },
            audit_path=audit_path,
            exit_code=0,
        )


# ---------- CLI plumbing ----------

def _resolve_smoke_scan_path() -> str:
    paths_json = Path(r"F:\multiagent-system\config\paths.json")
    if not paths_json.exists():
        raise RuntimeError("smoke test needs F:\\multiagent-system\\config\\paths.json")
    with open(paths_json, encoding="utf-8") as f:
        data = json.load(f)
    domain = data.get("domains", {}).get("verse-uefn")
    if not domain:
        raise RuntimeError("smoke needs domains.verse-uefn in paths.json")
    p = Path(domain) / "docs" / "template_PERSISTENCE_MAP.md"
    if not p.exists():
        raise RuntimeError(f"smoke target not found: {p}")
    return str(p)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="deepseek_tech_debt_scanner",
        description="Scan code/docs for tech debt via DeepSeek. Generates TD-NNN tickets.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke-test", action="store_true",
                      help="run minimal canonical case")
    mode.add_argument("--task-id", help="AR_<id>")
    p.add_argument("--scan-path", help="folder or file to scan")
    p.add_argument("--scan-mode", choices=SCAN_MODES)
    p.add_argument("--severity-threshold", choices=SEVERITY_LEVELS, default="medium")
    p.add_argument("--max-findings", type=int, default=20)
    p.add_argument("--output-dir", help="override default tech_debt dir")
    p.add_argument("--max-files", type=int, default=50)
    p.add_argument("--model", default=None, help="DeepSeek model. Default None = resolved via agents.json tier.")
    p.add_argument("--max-output-tokens", type=int, default=None,
                   help="Max output tokens. Default None = read from agents.json params.tech_debt_scanner.max_output_tokens.")
    p.add_argument("--no-write", action="store_true",
                   help="Skip writing TD tickets and TD_SUMMARY (smoke validation mode — avoids polluting productive docs/tech_debt/ namespace). Audit .md from WrapperBase still written.")
    args = p.parse_args()
    if not args.smoke_test:
        missing = [k for k in ("scan_path", "scan_mode") if not getattr(args, k)]
        if missing:
            p.error(f"missing required arg(s) in normal mode: {missing}")
    return args


def main() -> None:
    args = _parse_args()
    if args.smoke_test:
        smoke = _AGENT_PARAMS["smoke"]
        args.task_id = smoke["task_id"]
        args.scan_path = _resolve_smoke_scan_path()
        args.scan_mode = smoke["scan_mode"]
        args.severity_threshold = smoke["severity_threshold"]
        args.max_findings = smoke["max_findings"]
        args.max_files = smoke["max_files"]
        args.output_dir = None
        # Smoke uses flash intentionally — validates pipeline mechanics, not output quality. Runtime defaults to pro.
        args.model = smoke["model"]
        if args.max_output_tokens is None:
            args.max_output_tokens = _AGENT_PARAMS.get("max_output_tokens", 65536)
        # TD#1 fix B6: smoke implies no-write — avoids polluting productive docs/tech_debt/ namespace.
        args.no_write = True
    else:
        if args.model is None:
            args.model = resolve_model_for_agent("tech_debt_scanner")
        if args.max_output_tokens is None:
            args.max_output_tokens = _AGENT_PARAMS.get("max_output_tokens", 65536)

    wrapper = DeepSeekTechDebtScanner()
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
