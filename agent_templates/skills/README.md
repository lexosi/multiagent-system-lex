# Skills source-of-truth (P5 Hybrid)

Templates versionables. Hook SessionStart (`hooks/session-start-substitute-paths.ps1`, Fase 4 pending extensión) regenerará `.claude/skills/<name>/SKILL.md` con placeholders `{{paths.X.Y}}` sustituidos desde `config/paths.json`.

## Naming convention

`<role>-<program>` — ej. `planner-uefn`, `implementer-blender`, `reviewer-unreal`.

- **Roles cubiertos (6)**: `planner`, `implementer`, `reviewer`, `coherence-auditor`, `hypothesis-reasoning`, `knowledge-curator`.
- **Programas (3 Fase 1)**: `uefn` (verse-uefn), `unreal` (UE 5.4 Editor Python), `blender` (Blender 5.1.2 + bpy).
- **Total Fase 1**: 6 × 3 = 18 skills.

## Estructura SKILL.md

YAML frontmatter (`name`, `description`) + secciones markdown:

1. **Cuándo cargar** — trigger keywords distintivos auto-match (Q1 híbrido: auto-match por description + override explícito root).
2. **Conocimiento dominio para rol** — diferenciado por foco del rol.
3. **Paths canónicos** — placeholders `{{paths.X.Y}}` (pending Fase 4 hook extension).
4. **Gotchas top-N** — extraídos de KB MEMORY autoritativo (≥2 instancias O criticidad declarada).
5. **Checklists** — pre/post acción del rol.
6. **Anti-patterns** — qué NO hacer en este dominio.

Target ≤3K tokens body (R1 token tax mitigation per skill). Multi-skill cross-domain simultáneo soportado (Q2).

## Auto-match keywords (Q1)

Description field DEBE contener keywords distintivos del dominio para auto-trigger. Ejemplos UEFN: `.verse files, UEFN editor, Verse Persistence, weak_map, failable, ExampleUEFNProject, ExampleUEFNProject2`. Override explícito root vía Task prompt si auto-match falla.

## Refs

- Master plan: `docs/agent_runs/AR_2026-05-28_p5-hybrid-master/plan.md`
- Sub-plan Fase 1: `docs/agent_runs/AR_2026-05-28_p5-hybrid-fase1-skills/plan.md`
- Research base: `docs/agent_runs/AR_2026-05-27_root-overreach-diagnosis/research_agent_architecture.md`
- KB autoritativo UEFN: `<knowledge_root>\verse-uefn\MEMORY.md` + `<knowledge_root>\verse-uefn\docs\VERSE_SYNTAX_GUIDE.md`
