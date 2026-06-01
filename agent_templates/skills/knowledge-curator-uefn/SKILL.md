---
name: knowledge-curator-uefn
description: Skill para knowledge-curator post-AR Verse/UEFN cerrado. Documenta patterns ≥2 instancias O criticidad declarada en MEMORY.md AUTO-CURATED markers. Auto-match keywords AR closed Verse, final_report verdict OK, knowledge curation UEFN, MEMORY.md verse-uefn, pattern documentation, gotcha capture.
---

# knowledge-curator-uefn

## Cuándo cargar

Auto-match si AR Verse/UEFN cerrado (final_report.md verdict OK + TEST-GATE PASS) Y `.curator_pending` registra entry. Override root explícito para curation manual post-overhaul.

## Criterios documentación pattern

**Solo documentar si**:

- **≥2 instancias** cross-AR del mismo pattern (recurrencia confirmada), O
- **Criticidad declarada en postmortem** (HIGH / CRITICAL en final_report).

**NO documentar single instance sin criticidad** (regla anti-bloat). Candidatos single-instance útiles → archivar en `Recent learnings` chronológico, NO en `Patterns` o `Gotchas` AUTO-CURATED.

## Phrasing literal (NO paraphrase)

- Lección body MUST citar literal de final_report.md "Lecciones para knowledge base" L<N> (entre comillas).
- "Cómo aplicar" MUST ser literal de final_report "Cambios aplicados" o equivalente.
- "Evidencia" MUST referenciar file:line + AR ID + TEST-GATE PASS date.
- "Criticidad" MUST declarar level (HIGH / CRITICAL / MEDIUM) con razón verbatim postmortem.

**Anti-pattern**: paraphrase para "claridad". Si phrasing original ambiguo → escalar Lexosi, NO reescribir.

## Markers AUTO-CURATED (solo edit zone permitida)

- Edita **solo entre** `<!-- AUTO-CURATED:START -->` y `<!-- AUTO-CURATED:END -->` markers en:
  - `{{paths.knowledge_base}}/verse-uefn/MEMORY.md`.
  - `<project>/CLAUDE.md` (si proyecto target tiene AUTO-CURATED markers).
- **NO crear CLAUDE.md** (lo hace `/init`). Solo añadir entries entre markers si existen.
- Si markers NO existen → append al final del archivo con disclaimer.

## Criticidad levels

- **HIGH**: bug universal (todos los animales / items / cells), silent failure (no HUD diagnostic), regresión potencial recurrente, anti-loop hit 3rd attempt.
- **MEDIUM**: specific case repetible (clase de bug latente para items futuros, recurrible al añadir entity nuevo), patrón clase tech debt.
- **LOW**: single instance no critical, useful pero NO documentar como pattern (archivar Recent learnings).
- **CRITICAL**: data loss silent, AR completo de ruido por root cause obscured, build staleness con fix previo deployed-failed sin verify.

## Entry structure MEMORY.md

```markdown
### <Title gotcha/pattern verbatim from final_report>
- **AR**: AR_<id>
- **Lenguaje/dominio**: verse-uefn (this-codebase <project> si project-specific)
- **Lección** (phrasing literal final_report "Lecciones para knowledge base" L<N>): "<verbatim quote>"
- **Mecanismo** (literal): <verbatim>
- **Cómo aplicar** (literal): <verbatim trigger + steps + verify>
- **Evidencia**: file:line post-fix + AR + TEST-GATE PASS date
- **Criticidad**: declarada <LEVEL> — <razón verbatim>
- **Patrón análogo** (si aplica): cross-ref AR previo con meta-pattern compartido
- **Fecha**: YYYY-MM-DD
```

## Archive policy

- Entries `Patterns` + `Gotchas` >30 días → mover a `MEMORY_archive_YYYY-MM.md`.
- Entries `Recent learnings` >30 días → archive equivalente.
- Última archivada documented en sección `## Archive` del MEMORY.md activo.

## Paths canónicos

- Target curation: `{{paths.knowledge_base}}/verse-uefn/MEMORY.md`.
- Archive: `{{paths.knowledge_base}}/verse-uefn/MEMORY_archive_YYYY-MM.md`.
- Project CLAUDE.md (si aplica): `<project>/CLAUDE.md` (solo AUTO-CURATED markers).
- AR source: `{{paths.docs.agent_runs}}/AR_<id>/final_report.md`.
- Pending registry: `{{paths.state_files.curator_pending}}`.

## Checklists

### Pre-curation

- [ ] `final_report.md` verdict OK verificado.
- [ ] TEST-GATE Lexosi PASS verificado.
- [ ] Read final_report "Lecciones para knowledge base" sección entera.
- [ ] Cross-AR grep para confirmar ≥2 instancias O criticidad declarada.

### Curation emitida

- [ ] Phrasing literal preservado (NO paraphrase).
- [ ] Edit dentro AUTO-CURATED markers exclusivamente.
- [ ] Criticidad level declarado con razón verbatim.
- [ ] File:line + AR ID + date evidencia citados.
- [ ] Patrón análogo cross-ref si aplica.
- [ ] Archive sweep si entries >30 días detectadas.

## Anti-patterns curator (Capa 4)

- Documentar single instance sin criticidad declarada.
- Paraphrase phrasing original para "claridad".
- Editar fuera de AUTO-CURATED markers (CLAUDE.md fuera de markers → REJECT permanente).
- Crear CLAUDE.md (solo `/init` lo hace).
- Inventar criticidad level no presente en postmortem.
- Saltar archive sweep periódico (bloat MEMORY.md).
- Curate sin TEST-GATE PASS verificado (AR no realmente cerrado).
