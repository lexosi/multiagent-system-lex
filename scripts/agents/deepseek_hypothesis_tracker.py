"""deepseek_hypothesis_tracker.py — Manage hypotheses.md during debugging.

Propósito: mantener log estructurado de hipótesis durante debugging.
Acciones: init, add, update, falsify, list, class-jump.

ARQUITECTURA hybrid (since B2 2026-05-19, Opción C, AR_2026-05-19_B2-coherence-auditor-rebuild-reasoning):
Wrapper NO llama DeepSeek. Pure storage + anti-loop runtime.
- init, add, update, falsify, list, class-jump: file ops + anti-loop counter (Python).
- Reasoning (duplicate_check + falsify_eval) migrado a Claude .md agent `hypothesis-reasoning`.
- add + falsify emiten `result.llm_data_stub` para que caller invoque hypothesis-reasoning con data.
- Anti-sycophancy preserved: falsify aplica regardless verdict downstream (human authority).
- TD-026 (max_tokens=30 hardcoded) cerrado por construcción Step 6 B2.

ANTI-LOOP ENFORCEMENT (since 2026-05-18, brief §2.3 regla #1):
- Cada hipótesis tracking attempts en log line `- attempts: N`.
- Cada update con status=testing incrementa attempts.
- En 4ª transición a testing → exit_code=4 status=blocked_anti_loop.
- Override exige action `class-jump` con `--from-hyp` + `--rationale` (≥30 chars).

ANTI-FP-CASCADE (since 2026-05-18, regla #9 nueva):
- add con ≥2 hipótesis falsified previas en mismo AR → exit_code=5 status=blocked_anti_fp_cascade.
- Override exige flag `--premise-rechecked`.

CLI:
    --task-id AR_<id>            (required)
    --action ACTION              (required) — init|add|update|falsify|list|class-jump
    --hypothesis-id H<N>         (required para update/falsify; opcional para add → autoasigna)
    --hypothesis-text TEXT       (required para add y class-jump)
    --evidence TEXT              (required para update/falsify)
    --status STATUS              (required para update) — open|testing|confirmed|falsified|blocked
    --from-hyp H<N>              (required para class-jump) — hipótesis origen que se class-jumpea
    --rationale TEXT             (required para class-jump) — ≥30 chars, persistido en doc
    --premise-rechecked          (override anti-FP-cascade — requires Lexosi explícito)
    --hypotheses-file PATH       (optional) — default: <root>/docs/agent_runs/<task_id>/hypotheses.md
    --smoke-test                 — secuencia canónica de 7 pasos

EXIT CODES:
    0 = ok
    1 = generic error
    2 = config error
    4 = blocked_anti_loop (3 attempts reached, class-jump required)
    5 = blocked_anti_fp_cascade (≥2 falsified, premise re-check required)
"""
import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _deepseek_wrapper_base import WrapperBase, MULTIAGENT_ROOT, get_agent_params  # noqa: E402
from _common_regex import TASK_ID_RE, ATTEMPTS_LOG_RE  # noqa: E402


# Module-level params load (fail-loud at import per B3.0 Lexosi decision #5).
# hypothesis_tracker is storage-only (tier=null) — no model resolution.
_AGENT_PARAMS = get_agent_params("hypothesis_tracker")
HYP_ID_RE = re.compile(r"^H[1-9][0-9]*$")
ACTIONS = tuple(_AGENT_PARAMS.get("actions", ["init", "add", "update", "falsify", "list", "class-jump"]))
SECTIONS = tuple(_AGENT_PARAMS.get("sections", ["Open", "Testing", "Confirmed", "Falsified", "Blocked"]))
EMPTY_SECTION_MARKER = "_(none)_"
MAX_ATTEMPTS_PER_HYPOTHESIS = _AGENT_PARAMS.get("max_attempts_per_hypothesis", 3)  # brief §2.3 regla #1
ANTI_FP_CASCADE_THRESHOLD = _AGENT_PARAMS.get("anti_fp_cascade_threshold", 2)     # regla #9
MIN_CLASS_JUMP_RATIONALE_CHARS = _AGENT_PARAMS.get("min_class_jump_rationale_chars", 30)
STATUS_TO_SECTION = {
    "open": "Open",
    "testing": "Testing",
    "confirmed": "Confirmed",
    "falsified": "Falsified",
    "blocked": "Blocked",
}
SECTION_TO_STATUS = {v: k for k, v in STATUS_TO_SECTION.items()}


HEADER_TEMPLATE = "# Hypotheses — {task_id}\n\nGenerado por `deepseek_hypothesis_tracker`. NO editar a mano fuera de cada bloque hipótesis.\n\n"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DeepSeekHypothesisTracker(WrapperBase):
    """Hypothesis tracker — gestiona hypotheses.md por task. Pure storage post-B2 hybrid arch."""

    def __init__(self):
        super().__init__(wrapper_name="deepseek_hypothesis_tracker")
        self.args = None

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

    def _validate_hyp_id(self, hyp_id: str) -> None:
        if not HYP_ID_RE.match(hyp_id):
            self._emit_result(
                status="error",
                summary=f"invalid hypothesis-id: {hyp_id}",
                result=None,
                error=f"hypothesis-id must match ^H[1-9][0-9]*$, got: {hyp_id!r}",
                exit_code=1,
            )

    def _validate_action_args(self, a) -> None:
        action = a.action
        if action not in ACTIONS:
            self._emit_result(
                status="error",
                summary=f"invalid action: {action}",
                result={"valid_actions": list(ACTIONS)},
                error=f"action must be one of {ACTIONS}, got: {action!r}",
                exit_code=1,
            )
        # Specific requirements per action.
        if action == "add":
            if not a.hypothesis_text:
                self._emit_result(
                    status="error",
                    summary="add requires --hypothesis-text",
                    result=None,
                    error="add action requires --hypothesis-text",
                    exit_code=1,
                )
        elif action == "update":
            if not a.hypothesis_id or not a.evidence or not a.status:
                self._emit_result(
                    status="error",
                    summary="update requires --hypothesis-id, --evidence, --status",
                    result=None,
                    error="update requires all three: --hypothesis-id, --evidence, --status",
                    exit_code=1,
                )
            self._validate_hyp_id(a.hypothesis_id)
            if a.status not in STATUS_TO_SECTION:
                self._emit_result(
                    status="error",
                    summary=f"invalid status: {a.status}",
                    result={"valid_status": list(STATUS_TO_SECTION.keys())},
                    error=f"status must be one of {list(STATUS_TO_SECTION.keys())}",
                    exit_code=1,
                )
        elif action == "falsify":
            if not a.hypothesis_id or not a.evidence:
                self._emit_result(
                    status="error",
                    summary="falsify requires --hypothesis-id and --evidence",
                    result=None,
                    error="falsify requires both --hypothesis-id and --evidence",
                    exit_code=1,
                )
            self._validate_hyp_id(a.hypothesis_id)
        elif action == "class-jump":
            if not a.from_hyp or not a.rationale or not a.hypothesis_text:
                self._emit_result(
                    status="error",
                    summary="class-jump requires --from-hyp, --rationale, --hypothesis-text",
                    result=None,
                    error="class-jump requires --from-hyp (H<N> source), --rationale (≥30 chars), --hypothesis-text (new hypothesis at different abstraction layer)",
                    exit_code=1,
                )
            self._validate_hyp_id(a.from_hyp)
            if len(a.rationale.strip()) < MIN_CLASS_JUMP_RATIONALE_CHARS:
                self._emit_result(
                    status="error",
                    summary=f"class-jump rationale too short (min {MIN_CLASS_JUMP_RATIONALE_CHARS} chars)",
                    result={"rationale_length": len(a.rationale.strip()), "min_required": MIN_CLASS_JUMP_RATIONALE_CHARS},
                    error=f"rationale must explain abstraction layer change in ≥{MIN_CLASS_JUMP_RATIONALE_CHARS} chars",
                    exit_code=1,
                )
        # init, list: no required args beyond task-id.

    # ---------- File parsing ----------

    def _resolve_hyp_file(self, a) -> Path:
        if a.hypotheses_file:
            return Path(a.hypotheses_file)
        return MULTIAGENT_ROOT / "docs" / "agent_runs" / a.task_id / "hypotheses.md"

    def _parse_hypotheses_file(self, path: Path) -> tuple[dict[str, list[dict]], list[tuple[int, str]]]:
        """Parse hypotheses.md into ({section: [{id, text, log}]}, unparsed_lines).

        Block format expected:
            ### H<N> — <text>
            - created: <timestamp>
            - <evidence/log lines>

        Parser is permissive: never crashes. Lines that can't be classified are
        collected in unparsed_lines = [(line_number, first_50_chars)]. Header
        section (before first `## <Section>`) is treated as document header
        and excluded from unparsed.
        """
        result = {s: [] for s in SECTIONS}
        unparsed: list[tuple[int, str]] = []
        if not path.exists():
            return result, unparsed
        content = path.read_text(encoding="utf-8")
        current_section: str | None = None
        current_block: dict | None = None
        in_header = True  # Before first ## <Section>: ignore lines.
        for lineno, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            sec_match = re.match(r"^## (\w+)$", stripped)
            if sec_match and sec_match.group(1) in SECTIONS:
                if current_block:
                    result[current_section].append(current_block)
                    current_block = None
                current_section = sec_match.group(1)
                in_header = False
                continue
            hyp_match = re.match(r"^### (H[1-9][0-9]*) — (.+)$", line)
            if hyp_match and current_section:
                if current_block:
                    result[current_section].append(current_block)
                current_block = {"id": hyp_match.group(1), "text": hyp_match.group(2), "log": []}
                continue
            if current_block is not None and stripped:
                current_block["log"].append(line)
                continue
            # Line not classified.
            if in_header or not stripped:
                # Header lines (file-level) or blank lines: skip silently.
                continue
            if stripped == EMPTY_SECTION_MARKER:
                # Own sentinel for empty sections — not unparseable content.
                continue
            # We have a non-empty line that isn't a section header, hypothesis, or block-content.
            unparsed.append((lineno, line[:50]))
        if current_block:
            result[current_section].append(current_block)
        return result, unparsed

    def _maybe_add_parser_warnings(self, unparsed: list, warnings: list) -> None:
        """Append parser warning to warnings list if unparsed_lines is non-empty."""
        if unparsed:
            sample = unparsed[:5]
            warnings.append(
                f"hypotheses.md tiene {len(unparsed)} línea(s) no parseable(s) "
                f"(sample, line_no:content): {sample}"
            )

    def _serialize_hypotheses(self, data: dict[str, list[dict]], task_id: str) -> str:
        out = [HEADER_TEMPLATE.format(task_id=task_id).rstrip(), ""]
        for section in SECTIONS:
            out.append(f"## {section}")
            out.append("")
            blocks = data.get(section, [])
            if not blocks:
                out.append(EMPTY_SECTION_MARKER)
                out.append("")
                continue
            for b in blocks:
                out.append(f"### {b['id']} — {b['text']}")
                for log_line in b.get("log", []):
                    out.append(log_line)
                out.append("")
        return "\n".join(out) + "\n"

    def _next_hyp_id(self, data: dict[str, list[dict]]) -> str:
        max_n = 0
        for blocks in data.values():
            for b in blocks:
                n = int(b["id"][1:])
                if n > max_n:
                    max_n = n
        return f"H{max_n + 1}"

    def _find_hypothesis(self, data: dict, hyp_id: str) -> tuple[str | None, dict | None]:
        """Returns (section, block) or (None, None) if not found."""
        for section, blocks in data.items():
            for b in blocks:
                if b["id"] == hyp_id:
                    return section, b
        return None, None

    def _get_attempts(self, block: dict) -> int:
        """Parse current attempts count from block log lines. 0 if absent."""
        for log_line in block.get("log", []):
            m = ATTEMPTS_LOG_RE.match(log_line.strip())
            if m:
                return int(m.group(1))
        return 0

    def _set_attempts(self, block: dict, count: int) -> None:
        """Update or insert `- attempts: N` log line. Keeps single canonical entry."""
        new_log = []
        replaced = False
        for log_line in block.get("log", []):
            if ATTEMPTS_LOG_RE.match(log_line.strip()):
                new_log.append(f"- attempts: {count}")
                replaced = True
            else:
                new_log.append(log_line)
        if not replaced:
            # Insert after `- created:` line if present, else append at start.
            inserted = False
            final_log = []
            for log_line in new_log:
                final_log.append(log_line)
                if not inserted and log_line.strip().startswith("- created:"):
                    final_log.append(f"- attempts: {count}")
                    inserted = True
            if not inserted:
                final_log.insert(0, f"- attempts: {count}")
            new_log = final_log
        block["log"] = new_log

    def _count_falsified_in_ar(self, data: dict) -> int:
        """Count hypotheses in Falsified section."""
        return len(data.get("Falsified", []))

    # ---------- Actions ----------

    def _action_init(self, hyp_file: Path) -> None:
        if hyp_file.exists() and not self.args.force:
            self._emit_result(
                status="error",
                summary=f"hypotheses.md ya existe. NO uses init para AR en progreso — usa add/update/falsify/list.",
                result={
                    "existing_file": str(hyp_file),
                    "workflow_hint": {
                        "ver_estado": "--action list",
                        "añadir_nueva_hipotesis_post_FAIL": "--action add --hypothesis-text '<texto>'",
                        "marcar_hipotesis_falsified_por_TEST_GATE_FAIL": "--action update --hypothesis-id H<N> --status falsified --evidence '<TEST-GATE verbatim>'",
                        "transicionar_a_testing": "--action update --hypothesis-id H<N> --status testing --evidence '<probe diseñado>'",
                        "class_jump_post_3_attempts": "--action class-jump --from-hyp H<N> --rationale '<≥30 chars cambio capa abstracción>' --hypothesis-text '<nueva en otra capa>'",
                        "sobrescribir_intencional_solo_si_AR_reiniciado": "--force (peligroso, pierde histórico)",
                    },
                },
                error=f"init refuses to overwrite existing file without --force: {hyp_file}",
                exit_code=1,
            )
        hyp_file.parent.mkdir(parents=True, exist_ok=True)
        data = {s: [] for s in SECTIONS}
        hyp_file.write_text(self._serialize_hypotheses(data, self.args.task_id), encoding="utf-8")
        self._log("INFO", f"initialized hypotheses.md: {hyp_file}" + (" (forced overwrite)" if self.args.force else ""))
        self._emit_result(
            status="ok",
            summary=f"init hypotheses.md for {self.args.task_id}" + (" (forced)" if self.args.force else ""),
            result={
                "action": "init",
                "hypothesis_id": None,
                "hypotheses_file": str(hyp_file),
                "forced_overwrite": bool(self.args.force and hyp_file.exists()),
                "warnings": [],
            },
            audit_path=None,
            exit_code=0,
        )

    def _action_add(self, hyp_file: Path) -> None:
        if not hyp_file.exists():
            self._emit_result(
                status="error",
                summary=f"hypotheses.md does not exist (run init first): {hyp_file}",
                result=None,
                error=f"add requires existing hypotheses.md, run init first: {hyp_file}",
                exit_code=1,
            )
        data, unparsed = self._parse_hypotheses_file(hyp_file)
        hyp_id = self.args.hypothesis_id or self._next_hyp_id(data)
        if not HYP_ID_RE.match(hyp_id):
            self._emit_result(
                status="error",
                summary=f"invalid hypothesis-id: {hyp_id}",
                result=None,
                error=f"hypothesis-id must match ^H[1-9][0-9]*$, got: {hyp_id!r}",
                exit_code=1,
            )
        # Check no duplicate ID.
        if self._find_hypothesis(data, hyp_id) != (None, None):
            self._emit_result(
                status="error",
                summary=f"hypothesis-id already exists: {hyp_id}",
                result=None,
                error=f"hypothesis-id {hyp_id} already exists in {hyp_file}",
                exit_code=1,
            )

        warnings = []
        self._maybe_add_parser_warnings(unparsed, warnings)

        # ANTI-FP-CASCADE GATE (regla #9 since 2026-05-18).
        falsified_count = self._count_falsified_in_ar(data)
        if falsified_count >= ANTI_FP_CASCADE_THRESHOLD and not self.args.premise_rechecked:
            self._emit_result(
                status="blocked_anti_fp_cascade",
                summary=(
                    f"BLOCKED anti-FP-cascade: {falsified_count} hipótesis falsified en AR "
                    f"{self.args.task_id}. Re-verifica premisa antes de generar nueva hipótesis."
                ),
                result={
                    "action": "add",
                    "task_id": self.args.task_id,
                    "hypothesis_id_proposed": hyp_id,
                    "falsified_count": falsified_count,
                    "threshold": ANTI_FP_CASCADE_THRESHOLD,
                    "required_actions": [
                        "(a) Re-ejecutar [PREMISE-CHECK]: ¿síntoma sigue reproducible? ¿build deployado? ¿mecánica intencional vs bug?",
                        "(b) Preguntar a Lexosi verbatim: 'H<X>+H<Y> falsificadas. ¿Confirmas que el síntoma original sigue ocurriendo? ¿Has cambiado algo entre repros?'",
                        "(c) Override solo con --premise-rechecked y autorización explícita Lexosi.",
                    ],
                },
                error=f"anti-FP-cascade triggered (falsified={falsified_count}, threshold={ANTI_FP_CASCADE_THRESHOLD})",
                exit_code=5,
            )
        if self.args.premise_rechecked and falsified_count >= ANTI_FP_CASCADE_THRESHOLD:
            warnings.append(
                f"anti-FP-cascade OVERRIDE: --premise-rechecked usado con {falsified_count} hipótesis falsified. "
                f"Lexosi authorization implícita."
            )

        # Build llm_data_stub for hypothesis-reasoning Claude .md agent (duplicate_check mode).
        # Caller (root) extracts stub from envelope and invokes hypothesis-reasoning post-hoc.
        existing_hypotheses_stub = [
            {"id": b["id"], "section": section, "text": b["text"]}
            for section, blocks in data.items() for b in blocks
        ]

        # Append to Open section (initialize with attempts=0).
        block = {
            "id": hyp_id,
            "text": self.args.hypothesis_text,
            "log": [
                f"- created: {_iso_now()}",
                f"- attempts: 0",
                f"- status: open",
            ],
        }
        data["Open"].append(block)
        hyp_file.write_text(self._serialize_hypotheses(data, self.args.task_id), encoding="utf-8")
        self._log("INFO", f"added {hyp_id} to Open section")

        status = "warning" if warnings else "ok"
        self._emit_result(
            status=status,
            summary=f"add {hyp_id} on {self.args.task_id}" + (" (with warnings)" if warnings else ""),
            result={
                "action": "add",
                "hypothesis_id": hyp_id,
                "hypotheses_file": str(hyp_file),
                "llm_data_stub": {
                    "mode": "duplicate_check",
                    "new_text": self.args.hypothesis_text,
                    "existing_hypotheses": existing_hypotheses_stub,
                },
                "warnings": warnings,
            },
            audit_path=None,
            exit_code=0,
        )

    def _action_update(self, hyp_file: Path) -> None:
        if not hyp_file.exists():
            self._emit_result(
                status="error",
                summary=f"hypotheses.md does not exist: {hyp_file}",
                result=None,
                error=f"update requires existing hypotheses.md: {hyp_file}",
                exit_code=1,
            )
        data, unparsed = self._parse_hypotheses_file(hyp_file)
        section, block = self._find_hypothesis(data, self.args.hypothesis_id)
        if block is None:
            self._emit_result(
                status="error",
                summary=f"hypothesis not found: {self.args.hypothesis_id}",
                result=None,
                error=f"hypothesis {self.args.hypothesis_id} not in {hyp_file}",
                exit_code=1,
            )
        new_section = STATUS_TO_SECTION[self.args.status]
        warnings: list[str] = []
        self._maybe_add_parser_warnings(unparsed, warnings)

        # ANTI-LOOP GATE (brief §2.3 regla #1): transición a testing incrementa attempts.
        # Si attempts alcanzaría 4 → block exit_code=4.
        current_attempts = self._get_attempts(block)
        new_attempts = current_attempts
        if self.args.status == "testing":
            new_attempts = current_attempts + 1
            if new_attempts > MAX_ATTEMPTS_PER_HYPOTHESIS:
                self._emit_result(
                    status="blocked_anti_loop",
                    summary=(
                        f"BLOCKED anti-loop: {self.args.hypothesis_id} reached "
                        f"{MAX_ATTEMPTS_PER_HYPOTHESIS} attempts. Class-jump required."
                    ),
                    result={
                        "action": "update",
                        "task_id": self.args.task_id,
                        "hypothesis_id": self.args.hypothesis_id,
                        "current_attempts": current_attempts,
                        "max_attempts": MAX_ATTEMPTS_PER_HYPOTHESIS,
                        "required_actions": [
                            f"(a) Falsify {self.args.hypothesis_id} con probe específico (action=falsify).",
                            f"(b) Escalar a Lexosi con class-jump rationale verbatim.",
                            f"(c) Reformular como nueva hipótesis en capa de abstracción distinta "
                            f"(action=class-jump --from-hyp {self.args.hypothesis_id} --rationale '...' --hypothesis-text '...').",
                        ],
                    },
                    error=f"anti-loop triggered ({self.args.hypothesis_id}: {current_attempts}→{new_attempts}, max={MAX_ATTEMPTS_PER_HYPOTHESIS})",
                    exit_code=4,
                )

        # Remove from old section.
        data[section] = [b for b in data[section] if b["id"] != self.args.hypothesis_id]
        # Apply attempts update.
        if new_attempts != current_attempts:
            self._set_attempts(block, new_attempts)
        # Append update log entries.
        block["log"].append(f"- updated: {_iso_now()} → status={self.args.status}")
        block["log"].append(f"- evidence: {self.args.evidence}")
        data[new_section].append(block)
        hyp_file.write_text(self._serialize_hypotheses(data, self.args.task_id), encoding="utf-8")
        self._log("INFO", f"updated {self.args.hypothesis_id}: {section} → {new_section}, attempts={new_attempts}")
        status = "warning" if warnings else "ok"
        status = "warning" if warnings else "ok"
        self._emit_result(
            status=status,
            summary=f"update {self.args.hypothesis_id} {section}→{new_section} on {self.args.task_id} (attempts={new_attempts})" + (" (with warnings)" if warnings else ""),
            result={
                "action": "update",
                "hypothesis_id": self.args.hypothesis_id,
                "hypotheses_file": str(hyp_file),
                "from_section": section,
                "to_section": new_section,
                "attempts": new_attempts,
                "max_attempts": MAX_ATTEMPTS_PER_HYPOTHESIS,
                "warnings": warnings,
            },
            audit_path=None,
            exit_code=0,
        )

    def _action_class_jump(self, hyp_file: Path) -> None:
        """Class-jump: crear nueva hipótesis en capa de abstracción distinta tras 3 attempts.

        Persiste rationale en sección dedicada `## Class-jumps` y crea H<N+1> en Open.
        from_hyp original NO se mueve — sigue donde estaba (típicamente Testing post-block).
        """
        if not hyp_file.exists():
            self._emit_result(
                status="error",
                summary=f"hypotheses.md does not exist: {hyp_file}",
                result=None,
                error=f"class-jump requires existing hypotheses.md: {hyp_file}",
                exit_code=1,
            )
        data, unparsed = self._parse_hypotheses_file(hyp_file)
        warnings = []
        self._maybe_add_parser_warnings(unparsed, warnings)

        # Verify from_hyp exists.
        from_section, from_block = self._find_hypothesis(data, self.args.from_hyp)
        if from_block is None:
            self._emit_result(
                status="error",
                summary=f"class-jump source hypothesis not found: {self.args.from_hyp}",
                result=None,
                error=f"--from-hyp {self.args.from_hyp} does not exist in {hyp_file}",
                exit_code=1,
            )

        # Allocate new hypothesis ID.
        new_hyp_id = self.args.hypothesis_id or self._next_hyp_id(data)
        if not HYP_ID_RE.match(new_hyp_id):
            self._emit_result(
                status="error",
                summary=f"invalid hypothesis-id: {new_hyp_id}",
                result=None,
                error=f"hypothesis-id must match ^H[1-9][0-9]*$, got: {new_hyp_id!r}",
                exit_code=1,
            )
        if self._find_hypothesis(data, new_hyp_id) != (None, None):
            self._emit_result(
                status="error",
                summary=f"hypothesis-id already exists: {new_hyp_id}",
                result=None,
                error=f"hypothesis-id {new_hyp_id} already exists in {hyp_file}",
                exit_code=1,
            )

        # Create new hypothesis with class-jump metadata in log.
        new_block = {
            "id": new_hyp_id,
            "text": self.args.hypothesis_text,
            "log": [
                f"- created: {_iso_now()}",
                f"- attempts: 0",
                f"- status: open",
                f"- class-jump-from: {self.args.from_hyp}",
                f"- class-jump-rationale: {self.args.rationale.strip()}",
            ],
        }
        data["Open"].append(new_block)

        # Persist serialized file + append Class-jumps section.
        serialized = self._serialize_hypotheses(data, self.args.task_id)
        # Append `## Class-jumps` section if not present.
        cj_marker = "## Class-jumps"
        if cj_marker not in serialized:
            serialized = serialized.rstrip() + f"\n\n{cj_marker}\n\n"
        # Append entry.
        cj_entry = (
            f"### From {self.args.from_hyp} → {new_hyp_id}\n"
            f"- date: {_iso_now()}\n"
            f"- rationale: {self.args.rationale.strip()}\n"
            f"\n"
        )
        # Insert entry just after `## Class-jumps` header.
        idx = serialized.find(cj_marker)
        if idx >= 0:
            insertion_point = serialized.find("\n", idx) + 1
            # Skip one blank line if present after header.
            if serialized[insertion_point:insertion_point + 1] == "\n":
                insertion_point += 1
            serialized = serialized[:insertion_point] + cj_entry + serialized[insertion_point:]
        hyp_file.write_text(serialized, encoding="utf-8")
        self._log("INFO", f"class-jump from {self.args.from_hyp} → {new_hyp_id}")

        status = "warning" if warnings else "ok"
        self._emit_result(
            status=status,
            summary=f"class-jump {self.args.from_hyp} → {new_hyp_id} on {self.args.task_id}" + (" (with warnings)" if warnings else ""),
            result={
                "action": "class-jump",
                "hypothesis_id": new_hyp_id,
                "from_hyp": self.args.from_hyp,
                "rationale_chars": len(self.args.rationale.strip()),
                "hypotheses_file": str(hyp_file),
                "warnings": warnings,
            },
            audit_path=None,
            exit_code=0,
        )

    def _action_falsify(self, hyp_file: Path) -> None:
        if not hyp_file.exists():
            self._emit_result(
                status="error",
                summary=f"hypotheses.md does not exist: {hyp_file}",
                result=None,
                error=f"falsify requires existing hypotheses.md: {hyp_file}",
                exit_code=1,
            )
        data, unparsed = self._parse_hypotheses_file(hyp_file)
        section, block = self._find_hypothesis(data, self.args.hypothesis_id)
        if block is None:
            self._emit_result(
                status="error",
                summary=f"hypothesis not found: {self.args.hypothesis_id}",
                result=None,
                error=f"hypothesis {self.args.hypothesis_id} not in {hyp_file}",
                exit_code=1,
            )

        warnings = []
        self._maybe_add_parser_warnings(unparsed, warnings)

        # Move to Falsified (anti-sycophancy: human authority — falsify applies regardless reasoning verdict downstream).
        # Caller invokes hypothesis-reasoning Claude .md agent post-hoc with llm_data_stub for advisory verdict.
        falsify_data_stub = {
            "mode": "falsify_eval",
            "hypothesis_text": block["text"],
            "evidence": self.args.evidence,
        }
        data[section] = [b for b in data[section] if b["id"] != self.args.hypothesis_id]
        block["log"].append(f"- falsified: {_iso_now()}")
        block["log"].append(f"- evidence: {self.args.evidence}")
        data["Falsified"].append(block)
        hyp_file.write_text(self._serialize_hypotheses(data, self.args.task_id), encoding="utf-8")
        self._log("INFO", f"falsified {self.args.hypothesis_id} from {section}")

        status = "warning" if warnings else "ok"
        self._emit_result(
            status=status,
            summary=f"falsify {self.args.hypothesis_id} on {self.args.task_id}" + (" (with warnings)" if warnings else ""),
            result={
                "action": "falsify",
                "hypothesis_id": self.args.hypothesis_id,
                "hypotheses_file": str(hyp_file),
                "from_section": section,
                "llm_data_stub": falsify_data_stub,
                "warnings": warnings,
            },
            audit_path=None,
            exit_code=0,
        )

    def _action_list(self, hyp_file: Path) -> None:
        if not hyp_file.exists():
            self._emit_result(
                status="ok",
                summary=f"hypotheses.md does not exist: {hyp_file}",
                result={
                    "action": "list",
                    "hypothesis_id": None,
                    "hypotheses_file": str(hyp_file),
                    "exists": False,
                    "sections": {s: [] for s in SECTIONS},
                    "warnings": [],
                },
                audit_path=None,
                exit_code=0,
            )
        data, unparsed = self._parse_hypotheses_file(hyp_file)
        # Strip log content from result for brevity (keep id + text per section).
        compact = {
            section: [{"id": b["id"], "text": b["text"], "log_lines": len(b["log"])} for b in blocks]
            for section, blocks in data.items()
        }
        warnings: list[str] = []
        self._maybe_add_parser_warnings(unparsed, warnings)
        status = "warning" if warnings else "ok"
        self._emit_result(
            status=status,
            summary=f"list hypotheses for {self.args.task_id}: " + ", ".join(
                f"{s}={len(compact[s])}" for s in SECTIONS
            ) + (" (with warnings)" if warnings else ""),
            result={
                "action": "list",
                "hypothesis_id": None,
                "hypotheses_file": str(hyp_file),
                "exists": True,
                "sections": compact,
                "warnings": warnings,
            },
            audit_path=None,
            exit_code=0,
        )

    # ---------- Entry point ----------

    def run(self) -> None:
        a = self.args
        self._validate_task_id(a.task_id)
        self._validate_action_args(a)
        hyp_file = self._resolve_hyp_file(a)
        action = a.action
        if action == "init":
            self._action_init(hyp_file)
        elif action == "add":
            self._action_add(hyp_file)
        elif action == "update":
            self._action_update(hyp_file)
        elif action == "falsify":
            self._action_falsify(hyp_file)
        elif action == "list":
            self._action_list(hyp_file)
        elif action == "class-jump":
            self._action_class_jump(hyp_file)


# ---------- Smoke test driver ----------

def _smoke_test() -> None:
    """Run 7-step canonical sequence. Each step's JSON envelope to stderr.

    Final stdout = summary envelope with status, all steps' summaries.
    Steps are independent invocations sharing the same hypotheses.md file.
    """
    import subprocess
    task_id = "AR_smoke_hyptest_001"
    hyp_dir = MULTIAGENT_ROOT / "docs" / "agent_runs" / task_id
    hyp_file = hyp_dir / "hypotheses.md"
    # Cleanup previous smoke run.
    if hyp_file.exists():
        hyp_file.unlink()

    script = Path(__file__).resolve()
    python_exe = sys.executable

    steps = [
        ["--task-id", task_id, "--action", "init"],
        ["--task-id", task_id, "--action", "add",
         "--hypothesis-text", "el bug está en el módulo de persistencia"],
        ["--task-id", task_id, "--action", "add",
         "--hypothesis-text", "el bug está en validación de input"],
        ["--task-id", task_id, "--action", "update",
         "--hypothesis-id", "H1", "--status", "testing",
         "--evidence", "compilado, sin error en logs"],
        ["--task-id", task_id, "--action", "falsify",
         "--hypothesis-id", "H1",
         "--evidence", "test_persistence pasa con éxito en aislamiento"],
        ["--task-id", task_id, "--action", "list"],
    ]
    # Note: 6 sub-invocations (init + 2 add + update + falsify + list).
    # Lexosi spec listó 7 con cleanup; cleanup es no-op (queremos retain file para review).

    print("[SMOKE] starting 6-step sequence", file=sys.stderr)
    step_summaries = []
    final_status = "ok"
    for i, args_list in enumerate(steps, 1):
        cmd = [python_exe, str(script), *args_list]
        print(f"\n[SMOKE STEP {i}/{len(steps)}] cmd: {' '.join(args_list)}", file=sys.stderr)
        # Inherit env so DEEPSEEK_API_KEY is available.
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        print(f"[SMOKE STEP {i}/{len(steps)}] exit_code={result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"[SMOKE STEP {i}/{len(steps)}] stderr:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
        if result.stdout:
            print(f"[SMOKE STEP {i}/{len(steps)}] stdout:", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
        try:
            envelope = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            envelope = {"status": "error", "summary": "stdout not parseable as JSON",
                        "result": None, "meta": None, "error": "non-JSON stdout"}
        step_summaries.append({
            "step": i,
            "args": args_list,
            "exit_code": result.returncode,
            "status": envelope.get("status"),
            "summary": envelope.get("summary"),
            "warnings": (envelope.get("result") or {}).get("warnings", []),
        })
        if result.returncode != 0:
            final_status = "error"
            print(f"[SMOKE] step {i} failed, continuing to capture full picture", file=sys.stderr)
        elif envelope.get("status") == "warning" and final_status == "ok":
            final_status = "warning"

    summary_envelope = {
        "status": final_status,
        "summary": f"smoke test 6 steps: final_status={final_status}",
        "result": {
            "task_id": task_id,
            "hypotheses_file": str(hyp_file),
            "steps": step_summaries,
        },
        "meta": {
            "model": None,
            "model_requested": None,
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "cost_usd": 0.0,
            "duration_ms": 0,
            "audit_file": None,
            "note": "Smoke driver doesn't aggregate per-step tokens. Check sub-invocations stderr for individual costs.",
        },
        "error": None if final_status != "error" else "one or more steps failed",
    }
    print(json.dumps(summary_envelope, ensure_ascii=True, indent=2), flush=True)
    sys.exit(0 if final_status != "error" else 1)


# ---------- CLI plumbing ----------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="deepseek_hypothesis_tracker",
        description="Manage hypotheses.md during debugging (init/add/update/falsify/list).",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke-test", action="store_true",
                      help="run canonical 6-step sequence")
    mode.add_argument("--task-id", help="AR_<id>")
    p.add_argument("--action", choices=ACTIONS)
    p.add_argument("--hypothesis-id", help="H<N> format")
    p.add_argument("--hypothesis-text", help="hypothesis content (for add/update)")
    p.add_argument("--evidence", help="evidence text (for update/falsify)")
    p.add_argument("--status", choices=tuple(STATUS_TO_SECTION.keys()))
    p.add_argument("--hypotheses-file", help="override default path")
    p.add_argument("--force", action="store_true",
                   help="for init: overwrite existing hypotheses.md")
    p.add_argument("--from-hyp", help="for class-jump: source hypothesis H<N> being class-jumped")
    p.add_argument("--rationale", help=f"for class-jump: explanation (≥{MIN_CLASS_JUMP_RATIONALE_CHARS} chars) of abstraction layer change")
    p.add_argument("--premise-rechecked", action="store_true",
                   help="override anti-FP-cascade block (add). Requires Lexosi explicit authorization.")
    args = p.parse_args()
    if not args.smoke_test:
        if not args.action:
            p.error("--action required in normal mode")
    return args


def main() -> None:
    args = _parse_args()
    if args.smoke_test:
        _smoke_test()  # Exits internally.
        return

    wrapper = DeepSeekHypothesisTracker()
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
