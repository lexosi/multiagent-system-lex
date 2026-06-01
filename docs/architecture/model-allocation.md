> **⚠️ DEPRECATED — config-modular B3.0 (2026-05-20)**
>
> Source-of-truth ahora: `F:\multiagent-system\config\agents.json` + `F:\multiagent-system\config\models.json`
>
> Futuro: auto-generar este doc desde JSON (defer post-B6).
>
> Contenido tabla abajo preservado por historia decisión B1.

---

# Model Allocation — DeepSeek wrappers Python

**AR origen**: `AR_2026-05-19_B1-modelos-por-tarea`
**Date**: 2026-05-19
**Parent rebuild**: B (6 ARs: B1→B6)
**Scope**: argparse `--model` default por wrapper en `F:\multiagent-system\scripts\agents\deepseek_*.py`

---

## Tabla de decisión

| wrapper | naturaleza tarea | model actual pre-B1 | model B1 | target final | razón |
|---|---|---|---|---|---|
| `deepseek_researcher.py` | extracción + juicio relevancia context | deepseek-v4-pro | deepseek-v4-pro | deepseek-v4-pro | "qué es relevante" del contexto = juicio, no extracción mecánica. Flash en research = riesgo de extracción engañosa (precedente: AR_2026-05-19_item... bug item donde extracción pobre habría disfrazado save-path bug). |
| `deepseek_doc_writer.py` | generación rutinaria | deepseek-v4-pro | deepseek-v4-flash | deepseek-v4-flash | Generación template-driven mecánica. Pro overkill — flash cubre con ahorro coste. |
| `deepseek_tech_debt_scanner.py` | scan superficial patterns | deepseek-v4-pro | deepseek-v4-flash | deepseek-v4-flash | Pattern matching superficial. Cross-data verification crítica fuera de scope (→ B2 coherence-auditor). |
| `deepseek_model_allocator.py` | decisión binaria allocation | deepseek-v4-pro | deepseek-v4-flash | deepseek-v4-flash | Decisión binaria (qué modelo asignar a qué agente). Simple lookup + reasoning ligero. |
| `deepseek_tester.py` | smoke validation mecánico | deepseek-v4-pro | deepseek-v4-flash | deepseek-v4-flash | Verifica PASS/FAIL mecánico. NO cuestiona premisas (eso B2 coherence-auditor). Flash 3x más rápido en smoke. |
| `deepseek_hypothesis_tracker.py` | storage hipótesis + anti-loop counter (reasoning migrado) | deepseek-v4-pro | deepseek-v4-pro | hybrid Opción C **IMPLEMENTED B2 (2026-05-19)** | Reasoning (duplicate_check + falsify_eval) migrado a Claude `.md` agent `hypothesis-reasoning` (AR_2026-05-19_B2 Step 5+6). Wrapper Python pure storage + anti-loop runtime — NO llama DeepSeek. `--model` flag removed. TD-026 cerrado por construcción. |
| `deepseek_root_discipline_auditor.py` | **DELETED B2 (2026-05-19, Step 9)** — FULL migration Claude `.md` agent `root-discipline-auditor` | deepseek-v4-pro | deepseek-v4-pro | **FULL migration IMPLEMENTED B2** | Storage trivial (LLM-write + Read markdown) no justifica wrapper Python. Reasoning 100% Claude alineado con razón Opción C (DeepSeek no eficiente razonamiento crítico). Template: `agent_templates/root-discipline-auditor.md` (Step 8). Wrapper file Remove-Item Step 9. |

---

## Notas explícitas

### Smoke override hardcoded `deepseek-v4-flash`

Cross-wrapper, dentro del bloque `if args.smoke_test:` cada wrapper sobrescribe `args.model = "deepseek-v4-flash"` con comment uniforme:

```python
# Smoke uses flash intentionally — validates pipeline mechanics, not output quality. Runtime defaults to pro.
```

Intent: validar pipeline mechanics (transporte, parseo, envelope), NO calidad output. **Este AR (B1) NO toca smoke override.** Smokes siguen ejecutando contra flash post-B1 sin importar argparse default runtime.

Curated AR_2026-05-19 (`feedback_silent_failure_guard_wrappers.md` + entry CLAUDE.md "Smoke override").

### Target final `hypothesis_tracker` + `root_discipline_auditor` = **IMPLEMENTED B2 (2026-05-19)**

**Resolución divergente per gap 4 Lexosi 2026-05-19**:

- **`hypothesis_tracker` = HYBRID Opción C**: wrapper Python preserva storage rico (parse/serialize hypotheses.md + anti-loop counter + class-jump). Reasoning (`duplicate_check` + `falsify_eval`) migrado a `agent_templates/hypothesis-reasoning.md` Claude Opus. Wrapper Python NO llama DeepSeek post-refactor. Step 5+6 AR_2026-05-19_B2.
- **`root_discipline_auditor` = FULL MIGRATION** (NO hybrid). Wrapper Python deleted (Step 9). Reasoning + storage = Claude `.md` agent `agent_templates/root-discipline-auditor.md` (Step 8). Razón: storage trivial no justifica wrapper Python; YAGNI shared base class confirmado.

Pattern siblings: `coherence-auditor` (Step 1-3 B2, pre-fix divergencia esperado vs observado) + `hypothesis-reasoning` (Step 5 B2) + `root-discipline-auditor` (Step 8 B2). 3 Claude reasoning agents independientes.

### Pricing DeepSeek post-2026-05-31

Promoción 75% off DeepSeek v4-pro expira 2026-05-31 (12 días desde hoy 2026-05-19).

**TD-029**: re-evaluar pricing tier post-fecha. Si pro deja de ser cost-effective → considerar bajar wrappers pro→flash residuales (`researcher`) salvo si target final Opción C ya implementado. Post-B2: `hypothesis_tracker` ya no llama DeepSeek (storage-only Python, reasoning Claude). `root_discipline_auditor` deleted (FULL migration Claude). Lista reducida a `researcher` único pro residual con DeepSeek calls activos.

**No abordar en B1**. Defer fecha real.

---

## Anti-scope de este documento

- NO documenta `max_output_tokens` defaults (cubierto curated AR_2026-05-19, separado).
- NO documenta `_deepseek_wrapper_base.py` defaults internos (`flash` base).
- NO documenta wrappers nuevos hipotéticos (coherence-auditor B2 será documentado al implementarse).
- NO incluye modelos Claude agents `.md` (frontmatter cada agent template tiene `model: opus|sonnet` específico).

---

## Cambios aplicados en B1

| Wrapper | argparse default | docstring | help= añadido |
|---|---|---|---|
| `deepseek_doc_writer.py` | pro → flash | (ya flash, match) | sí (mechanical task: doc generation) |
| `deepseek_tech_debt_scanner.py` | pro → flash | (ya flash, match) | sí (mechanical task: tech-debt scan) |
| `deepseek_model_allocator.py` | pro → flash | pro → flash | sí (mechanical task: model allocation decision) |
| `deepseek_tester.py` | pro → flash | pro → flash | sí (mechanical task: smoke validation) |
| `deepseek_researcher.py` | pro (no change) | flash → pro | sí (critical reasoning: context relevance judgment) |
| `deepseek_hypothesis_tracker.py` | pro (no change) | flash → pro | sí (critical reasoning: hypothesis formulation/refutation) |
| `deepseek_root_discipline_auditor.py` | pro (no change) | pro (no change) | sí (critical reasoning: role discipline audit) |

Pattern `help=`: `"DeepSeek model. Default <X> (<mechanical task | critical reasoning>: <subcategory>)."`. Steps 6+7 añaden sufijo `" Target final B2: hybrid Claude .md agent."`.

---

## Referencias cruzadas

- `CLAUDE.md` proyecto: convenciones código wrappers + invariantes pricing.
- `_deepseek_wrapper_base.py`: base default `flash` (L152) — no tocar este AR.
- AR previo `AR_2026-05-19_modelo-tokens-defaults-7-wrappers`: max_output_tokens uniformes 65536.
- AR origen este doc: `docs/agent_runs/AR_2026-05-19_B1-modelos-por-tarea/steps.md`.
