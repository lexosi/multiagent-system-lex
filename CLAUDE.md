# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es este repo

Sistema multi-agente para <user> (Windows 11 + PowerShell admin). Coordina debugging/feature work en proyectos Verse/UEFN, Python, Rust, Java, TS+Bun. Diseño cerrado en `briefs/AGENT_SYSTEM_BRIEF.md` (v2) + `briefs/ANTI_SYCOPHANCY_ADDENDUM.md`. **Lee ambos antes de tocar arquitectura.**

Stack: Claude Code subagents nativos (no Agent Teams) + 4 grunt-work Python wrappers que llaman DeepSeek API directa vía OpenAI SDK con `base_url=https://api.deepseek.com`. Híbrido necesario porque Claude Code 2.1.x no soporta routing per-agent a providers distintos.

## Comandos comunes

Activación venv **prohibida**. Siempre path absoluto al python del `.venv`:

```powershell
<repo_root>\.venv\Scripts\python.exe <repo_root>\scripts\agents\<wrapper>.py <args>
```

| Acción | Comando |
|---|---|
| Smoke test conexión DeepSeek | `<repo_root>\.venv\Scripts\python.exe <repo_root>\config\test_deepseek_connection.py` |
| Smoke test wrapper | `<python> scripts\agents\<wrapper>.py --smoke-test` |
| Install dep | `<repo_root>\.venv\Scripts\python.exe -m pip install <pkg>` (actualizar `.venv-info.md`) |
| Cargar `DEEPSEEK_API_KEY` per session | `$env:DEEPSEEK_API_KEY = [System.Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')` |
| Verificar encoding agents | `Get-ChildItem ".claude\agents\*.md" \| ForEach-Object { $b = [System.IO.File]::ReadAllBytes($_.FullName)[0..3]; "$($_.Name): $($b -join ' ')" }` (debe empezar `45 45 45 ...`, NUNCA `239 187 191`) |
| Fix encoding BOM | Script `hooks/fix-bom-agents.ps1` (TODO crear) |

No hay `pytest` / build system. Validación = smoke tests de cada wrapper + ejecutar un AR end-to-end. La key vive en `.env` (gitignored) y en env var de Windows User.

## Arquitectura (lo que requiere leer varios archivos)

### Roster — 14 agentes registrados (source-of-truth: `config/agents.json`)

| Tipo | Agentes | Modelo runtime | Source-of-truth |
|---|---|---|---|
| Planning / review / specialist / audit | `planner`, `reviewer`, `tester`, `knowledge-curator`, `implementer`, `specialist-verse`, `coherence-auditor`, `hypothesis-reasoning`, `root-discipline-auditor` | Opus (tier resuelto `config/agents.json`) | `agent_templates/*.md` |
| Thin-wrappers (bridge Task→Bash→Python) | `researcher`, `hypothesis-tracker`, `doc-writer`, `tech-debt-scanner` | Sonnet (delegan a DeepSeek) | `agent_templates/*.md` |
| Python wrappers DeepSeek | `deepseek_researcher.py`, `deepseek_hypothesis_tracker.py`, `deepseek_doc_writer.py`, `deepseek_tech_debt_scanner.py` | `deepseek-v4-flash` (curator: `deepseek-v4-pro`) | `scripts/agents/` + `_deepseek_wrapper_base.py` |

`agent_templates/` es source-of-truth versionable. SessionStart hook (`hooks/session-start-substitute-paths.ps1`) regenera `<repo_root>\.claude\agents\*.md` (project-level, **UTF-8 sin BOM**) sustituyendo placeholders `{{paths.X.Y}}` con valores de `config/paths.json`. **No edites `~/.claude/agents/*.md` (CC los ignora en Windows) ni `.claude/agents/*.md` directamente** — el hook los sobrescribe. Edita en `agent_templates/`.

### Flujo §2.2 (brief)

```
<user> ticket → root produce plan.md → researcher → hypothesis-tracker (init)
  → planner refina plan.md → [implementer + specialist-<lang>] → reviewer → tester
  → TEST-GATE humano (UEFN manual) → doc-writer → tech-debt-scanner → knowledge-curator
```

Root es el ÚNICO que invoca otros agentes (CC v2.1.146 limit: subagents NO tienen Task tool). Root planea + invoca + coordina inline. Subagents (incluido implementer) reportan a root y NO orquestan entre sí (TD-030 RESOLVED B4 — `Task` removido frontmatter implementer).

### Paths centralizados

`config/paths.json` = única source of truth de rutas absolutas. Schema documentado en `config/paths-schema.md`. Override per-machine vía `$env:MULTIAGENT_PATHS_CONFIG`. **Mapeo lenguaje→dominio obligatorio**: nunca concatenar `<knowledge_root>\<language>\…` literal; siempre `paths.language_to_domain[language] → paths.domains[domain]`. `verse` ≠ `verse-uefn`.

### AR lifecycle (estados inferidos por archivos)

Cada ticket → `docs/agent_runs/AR_<YYYY-MM-DD>_<slug>/`. Colisión → sufijo `-2`, `-3`. Estados:

| Estado | Marcadores |
|---|---|
| `open` | `plan.md` solo |
| `in-progress` | `plan.md` + algún output intermedio, sin `final_report.md` |
| `closed-ok` | `final_report.md` verdict OK (+ opcional `curator_report.md`) |
| `closed-failed` | `final_report.md` verdict FAILED |
| `aborted` | `_ABORTED.md` marker |

### Hooks (3)

| Hook | Trigger | Función |
|---|---|---|
| `session-start-substitute-paths.ps1` | SessionStart (startup/resume/clear/compact) | Regenera agents desde templates con paths sustituidos. Target: **`<repo_root>\.claude\agents\`** (project-level). Encoding: **UTF-8 sin BOM**. Idempotente vía `.placeholders_state.json` (SHA256). |
| `stop-knowledge-curator.ps1` | Stop (cada turn) | Detecta ARs cerrados (final_report.md reciente sin curator_report.md), registra en `.curator_pending`. Next session lo consume. Exit 0 SIEMPRE. |
| `pretooluse-guard-protected-files.ps1` | PreToolUse `Edit\|Write` | Bloquea writes a `.git/`, persistence Verse (`Content\Verse\Core\*Persistence*.verse`), `CLAUDE.md` fuera de markers `<!-- AUTO-CURATED:START/END -->`. |

Debug hooks: `$env:MULTIAGENT_HOOKS_DEBUG = "1"` → log a `hooks\.debug.log`.

## Invariantes (INQUEBRANTABLES)

### Encoding & paths (descubierto Fase 5)

- Agents .md DEBEN ser **UTF-8 sin BOM**. CC v2.1.142 Windows falla silencioso con BOM (primeros 4 bytes `EF BB BF 2D` rompen YAML frontmatter parser).
- CC v2.1.142 Windows **NO carga `~/.claude/agents/`** (user-level). Solo project-level `<repo>/.claude/agents/` y plugin agents. Bug confirmado issue #31392.
- Hook SessionStart DEBE regenerar a `<project>\.claude\agents\` usando `[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))` — NUNCA `Set-Content` ni `Out-File` (añaden BOM por default en Windows).

### Anti-loop (brief §2.3)

1. Max **3 intentos por hipótesis**. 4º → class-jump obligatorio.
2. **Probe antes de fix.** Hipótesis sin probe confirmatorio = RECHAZADA.
3. **Observación <user> > hipótesis del agente** — pero distinguir modo (evidencia / intuición / ambiguo). Si ambiguo, PEDIR clarificación. Root enforce regla "modo contradicción <user>" inline (evidencia → falsificar hipótesis + replanear; intuición → discutir + pedir test; ambiguo → pedir clarificación verbatim).
4. Source-of-truth divergence check antes de bug de lógica.
5. Predicciones visuales contrastadas con observación real.

### Anti-sycophancy (addendum, 4 capas)

- **root/reviewer**: "sin cambios necesarios" / "sin blockers" son outputs válidos. NO inventar trabajo.
- **implementer**: ONE file per turn. Cambio de 1 línea = 1 línea (no reformat vecinas). Bug colateral → TD ticket, NO arreglar en mismo commit.
- **researcher (triaje)**: scrubs aprobados = scope. No sobre-corregir.
- **knowledge-curator**: pattern requiere ≥2 instancias O criticidad declarada en postmortem. Phrasing literal (no relax). Solo entre markers AUTO-CURATED.

### Archivos protegidos

- `CLAUDE.md` (cualquier proyecto): **solo `knowledge-curator`** edita, y **solo** entre `<!-- AUTO-CURATED:START -->` / `<!-- AUTO-CURATED:END -->`. Si markers no existen → append al final. Nunca crear CLAUDE.md (lo hace `/init`).
- `Content/Verse/Core/*` (singletons proyecto UEFN): ASK <user> antes.
- Persistence Verse: ASK antes.
- `.git/`: bloqueado por hook.

### Budget

Si Task a agente Anthropic estima >50k tokens (`chars/4`) → ESCALAR a <user> antes de invocar. Wrappers DeepSeek negligibles (<$0.01 típico): invocar sin escalar.

## Convenciones código

- **Python wrappers**: heredan de `WrapperBase` (`scripts/agents/_deepseek_wrapper_base.py`). Output JSON envelope a stdout (`ensure_ascii=True`), audit `.md` por invocación en `docs/agent_runs/AR_<id>/`. UTF-8 forzado en stdout. Modelos canónicos: `deepseek-v4-flash`, `deepseek-v4-pro`. Aliases `deepseek-chat`/`deepseek-reasoner` deprecated.
- **Pricing**: re-verificar tras 2026-05-31 (promoción 75% v4-pro expira).
- **Verse**: el `specialist-verse` es el ÚNICO con `WebFetch`. Whitelist estricta: `dev.epicgames.com/documentation/*`, `create.fortnite.com/*`. PROHIBIDO `forums.unrealengine.com`. Top-11 gotchas inline en `agent_templates/specialist-verse.md` — leer antes de tocar Verse.

## Idioma

Español por defecto en docs, system prompts, reportes a <user>. Comentarios de código y nombres en inglés OK.

<!-- AUTO-CURATED:START -->
## Recent learnings (auto-curated by knowledge-curator, last 10 ARs)

- [2026-05-19] Cap N4 — STOP-GATE <user> per-step en ARs feature multi-step. Verbatim <user>: "Cada step espera OK explícito mío antes de pasar al siguiente." Planner produce `plan.md` con steps numerados ONE-FILE-PER-TURN; root presenta cada step output a <user> verbatim y espera `OK` antes de invocar el siguiente subagent. NO encadenar steps sin gate humano. Anti-loop no aplica (no bug-fix) pero gate humano per-step suple supervisión. 8 gates en 1 AR ejecutados sin fricción confirma viabilidad. (AR_2026-05-19_audit-batch1-silent-base-defaults)
- [2026-05-19] Silent-failure → loud-failure pattern wrappers DeepSeek + hooks PowerShell — Mecanismos divergentes por contexto: Python wrappers `raise ValueError`/`_emit_result(exit_code=1)` (single-shot, abort+envelope error); PowerShell hooks `[Console]::Error.WriteLine` + `$contextLines += warning` (fire-and-forget, NO `sys.exit` — rompe CC session, contract hook exit 0 obligatorio). Defensa-en-profundidad: lower-layer raise (`_call_deepseek` content vacío) + upper-layer guards en callers como red de seguridad ante subclase futura que atrape excepción. Pattern recurrente cross-AR (AR_2026-05-18_fix-wrapper-max-tokens silent truncation + AR_2026-05-19 batch 9 SF en 6 files). No reintroducir `except Exception: pass` ni swallow silently en wrappers/hooks. (AR_2026-05-19_audit-batch1-silent-base-defaults, AR_2026-05-18_fix-wrapper-max-tokens)
- [2026-05-21] orchestrator subagent eliminado B4 (Opción A) — Root absorbe planning + invocador físico único (CC v2.1.146 subagents NO tienen Task). TD-030 RESOLVED (Task removido implementer.md frontmatter). B2-obs-2 cleared. 16 ops disco: DELETE orchestrator.md + agents.json entry + 6 templates body + 4 scripts/hooks + CLAUDE.md secciones operacionales. Razón: 5+ ARs nunca usaron orchestrator funcionalmente. Entries históricas §"Disciplina de sesión" L137-154 PRESERVADAS verbatim (β audit trail). (AR_2026-05-21_B4-orchestrator-eliminacion)
- [2026-05-28] P5 Hybrid Fase 2 — `skills:` frontmatter wildcard NO documentado docs Anthropic oficiales → lista explícita 3 entries default safe. Investigation Step 1 verbatim docs `code.claude.com/docs/en/sub-agents#preload-skills-into-subagents` + `code.claude.com/docs/en/skills`: syntax oficial muestra YAML list explícita exact names, ZERO menciones de `*`/`glob`/`wildcard`/`pattern`. Graceful fallback documentado: "If a listed skill is missing or disabled, Claude Code skips it and logs a warning to the debug log". Riesgo silent fail si parser interpreta `planner-*` como literal string. Pattern aplicado: 6 base templates (planner, implementer, reviewer, coherence-auditor, hypothesis-reasoning, knowledge-curator) × 3 entries (`<role>-uefn/unreal/blender`) = 18 entries total. Excluidos: `root-discipline-auditor.md` (process audit cross-domain) + `specialist-verse.md` (specialist profundo Capa 3). Templates nuevos base agents que precarguen skills domain deben replicar pattern lista explícita exact names. (AR_2026-05-28_p5-hybrid-fase2-frontmatter)
- [2026-05-28] CC v2.1.146 caveat: edits frontmatter `skills:` mid-session NO refrescan awareness skill content — Step 10 smoke-test verificó parser LOADED-OK pero awareness NOT-AWARE (cache pre-edit). Causa probable: CC v2.1.146 carga subagents at session startup; ediciones post-startup no refrescan mid-session. Verificación awareness skill content inyectado context requiere restart sesión Claude. Nota técnica runtime, no regla — implica post-edit `skills:` frontmatter, smoke-test awareness debe deferirse a sesión nueva. (AR_2026-05-28_p5-hybrid-fase2-frontmatter)
- [2026-05-28] P5 Hybrid Fase 4 — Hook `session-start-substitute-paths.ps1` extendido para procesar `agent_templates/skills/**/SKILL.md` → regen `.claude/skills/<name>/SKILL.md` runtime CC v2.1.146, idempotente SHA256, mismo pattern `.claude/agents/`. Extension +127/-3 líneas, state file `.placeholders_state.json` aditivo (`skills_hash`+`skills_generated`), backward-compat first-run automático sin migración manual. Smoke-test: exit 0 + 18 skills regen + encoding no BOM + idempotencia 3rd invocation `skipRegen` sin output. Pattern backward-compat aditivo state files JSON reutilizable futuras extensions hook (state antiguo sin field nuevo → `$null` mismatch → regen first-run automático). Cierra gap fundacional Fase 2 manual copy drift risk. TD-minor detectado (no blocking): mensaje regen agents ahora ambiguo (puede triggerse por mismatch `skills_hash`), optional añadir `or skills` al string. (AR_2026-05-28_p5-hybrid-fase4-hook-skills)
- [2026-05-28] P5 Hybrid Capa 3 CLOSED (3/3 specialists profundos: verse + unreal + blender) — `AR_2026-05-28_p5-hybrid-fase3-specialists`. Templates NEW `agent_templates/specialist-unreal.md` (205 LOC, 7 gotchas inline `[UE 5.4]` verbatim KB MEMORY.md) + `agent_templates/specialist-blender.md` (197 LOC, 7 gotchas inline `[Blender 5.1.2]` verbatim KB MEMORY.md). Roster 14→16 (`config/agents.json` +12 lines, schema EXACT clone specialist-verse: `type=claude_md`, `tier=high`, `enabled=true`, `params={}`). Pattern Fase 3 confirmed: claude_md + tier=high opus + WebFetch nativo whitelist específico per dominio + skills explicit list 6 entries `<role>-<domain>` + top gotchas inline verbatim KB. WebFetch whitelist divergence: Unreal `docs.unrealengine.com/*` + `dev.epicgames.com/documentation/unreal-engine/*` con SPA broken disclaimer (replicado specialist-verse); Blender `docs.blender.org/*` + `developer.blender.org/*` sin SPA disclaimer (Blender docs HTML OK). Smoke regen G2 PASS: hook exit 0 + 10 agents regen + skills passthrough 18 files preservados + encoding UTF-8 sin BOM (`2d 2d 2d 0a`) + skills frontmatter byte-for-byte. Awareness smoke-test Step 5 DEFERRED next session (caveat CC v2.1.146 mid-session post-edit frontmatter). TD detectados: paths.json domains map omite `blender-python` y `unreal-python-editor` (specialist templates resuelven via literal append `{{paths.knowledge_base}}/<domain>/` — funcional pero source-of-truth gap, TD-paths-domains-missing); hook regen FULL triggera regen 18 skills inalterados cada agents.json edit (TD-minor low-priority); kb_tiers.json solo `verse-uefn` (specialists unreal/blender Read MEMORY.md authority primaria, tier_1_always entries pending future AR). (AR_2026-05-28_p5-hybrid-fase3-specialists)
- [2026-05-28] Wrappers Python (researcher/tester/doc-writer/tech-debt-scanner/hypothesis-tracker) NO requieren `.md` template en `agent_templates/`. Contract canónico vive en `scripts/agents/_deepseek_wrapper_base.py`. Analysis simetría rol-discipline NO aplica (wrappers son thin-bridge Task→Bash→Python, no subagents claude_md con system prompt independiente). RC8 (crear 5 templates `.md`) explícitamente skip político — decisión <user> 2026-05-27 B5. AR_2026-05-27_stage1-hardening-anti-overreach.
- [2026-05-28] P5 Hybrid Fase 5 MVP token tax CLOSED (5/5 capas arquitectónicas + Fase 5.1 deferred) — `AR_2026-05-28_p5-hybrid-fase5-mvp-token-tax`. Stop hook 3º deployed `hooks/stop-capture-skills-token-tax.ps1` 146 LOC PS5.1 regex YAML frontmatter multi-line + fail-open trap + UTF-8 sin BOM `AppendAllText`. Agregador `scripts/metrics/aggregate_token_tax.py` 119 LOC stdlib + resolver paths.json+fallback. `config/paths.json` +1 entry `state_files.metrics_dir`. `.gitignore` +3 líneas `.metrics/` (`!!` flag confirmed). `.claude/settings.json` +1 Stop entry (3º array). Baseline cuantitativo real upper-bound `chars/4` single-turn full-load: TOTAL 41021 approx_tokens; breakdown: specialist-blender 8680 (6 skills) + specialist-unreal 7855 (6) + hypothesis-reasoning 4773 (3) + implementer 4390 (3) + coherence-auditor 4194 (3) + knowledge-curator 3924 (3) + planner 3727 (3) + reviewer 3478 (3) + specialist-verse 0 + root-discipline-auditor 0 (NO frontmatter `skills:` list, ver Fase 2 entry — specialist-verse predates P5 Hybrid + root-discipline-auditor by design cross-domain process audit). Lecciones literal final_report L62-65: (a) "PS5.1 requiere parse multi-línea con `[regex]::Matches` + `Select-String` fallback"; (b) "chars/4 es cota superior; para per-invocación real se necesita tokenizador CC (post-restart)"; (c) "specialist-verse y root-discipline-auditor no cuentan skills — no afecta el MVP, pero debe ser manejado en Fase 5.1 (contar 0)"; (d) "Fail-open trap: hook no debe bloquear turno si falla el parse o escritura — implementado con `try/catch` y log a stderr". Stop hook pattern reactivo confirmed stable (3rd Stop hook deployed: stop-knowledge-curator + stop-no-auditor + stop-capture-skills-token-tax — array crece per enforcement/instrumentation need). TD-paths-domains-missing 3ª instancia surfaced (Fase 3 + Fase 4 + Fase 5 paths fix `state_files.metrics_dir` resuelto via paths.json edit) → meta-pattern paths.json mantenimiento AR confirmed. TD post-Fase 5: stop-knowledge-curator BOM risk PS5.1 cosmético, hook full agents.json regen, static upper-bound vs real (Fase 5.1 dinámico), false-positive skill match (Fase 5.1 NLP-lite). 5 capas P5 Hybrid CLOSED: (1) Base agents, (2) Skills 18, (2.5) Frontmatter precarga, (2.6) Runtime location, (3) Specialists profundos, (4) Hook extension, (5) Outcome measurement MVP token tax. (AR_2026-05-28_p5-hybrid-fase5-mvp-token-tax)
- [2026-05-29] CC v2.1.146 tool_name rename Task→Agent — subagent invocation runtime envía `tool_name="Agent"`, NO `"Task"`. Hook PreToolUse capture filter `if ($payload.tool_name -ne "Task") { exit 0 }` + `.claude/settings.json` matcher entry `"matcher": "Task"` → dead-code desde deploy Fase 5.1 (hook NUNCA registered + NUNCA fires post-rename → `_pending_turn_tasks.jsonl` NUNCA escrito → campos dynamic Fase 5.1/5.1b SIEMPRE vacíos). Fix atómico 3 single-line edits: hook L71 filter `-ne "Agent" -and -ne "Task"` (De Morgan: passa solo si tool_name ∈ {Agent, Task}) + settings.json L184 matcher `"Agent|Task"` (regex pipe validado precedente `Edit|Write` 3× same file L151/L162/L173) + hook header doc L3/L13 sync. Defensive backward-compat: aceptar ambos `"Agent"|"Task"` cubre futura release CC que pudiera re-renombrar (cobertura mínima sin coste). Pattern reuse: cualquier hook actual o futuro que filtre `tool_name` para subagent invocation DEBE aceptar ambos `Agent` y `Task` (matcher regex pipe + hook condition AND con `-ne` doble). Criticality declarada postmortem: dead-code silent post-rename CC version bump — pattern recurrente potencial cada CC upgrade que renombra tool internal names. Reviewer G1 APROBADO + smoke-test G1 step 4 PASS empíricamente (`_pending_turn_tasks.jsonl` entry `subagent_type:"Explore"` populated post-fix). Side-findings deferred AR hijos: H3 Stop multi-fire ghost records (`AR_2026-05-29_fase5-1d-stop-multi-fire-ghost`) + agentId camelCase mismatch hook L91-92 (`AR_2026-05-29_fase5-1e-agentId-camelcase-mismatch`). (AR_2026-05-29_fase5-1-tool-name-mismatch)
- [2026-05-29] CC v2.1.146 PreToolUse payload schema — agentId NO emitted, tool_use_id correlation key — H1 (snake↔camel rename `agent_id`→`agentId` L91-92) FALSIFIED empírico via probe Step 1 attempt 2: payload dump runtime captured 2026-05-29 11:14:39 confirma `session_id`+`tool_use_id`+`tool_input.subagent_type`+`tool_input.description` populated ✓ pero `agentId`/`agent_id`/`subagentId`/`taskId` NO present en NINGÚN nivel (top + nested). Causa arquitectural: subagent agentId se genera AT spawn time (post-PreToolUse phase) — PreToolUse fires BEFORE Agent tool spawns el child → agentId NO existe runtime aún. Payload structure verbatim top-level: `session_id` + `transcript_path` + `cwd` + `permission_mode` + `effort.level` + `hook_event_name` + `tool_name` + `tool_input{description,prompt,subagent_type}` + `tool_use_id` (formato `toolu_<base62>`). Mapping producer→consumer correcto: PreToolUse `tool_use_id` → scan `~/.claude/projects/<repo>/<session_id>/subagents/agent-<HEX17>.meta.json` matching field `toolUseId` → extract `<HEX17>` from filename → real agentId = `<HEX17>` (e.g., `a2515a61e12e94c9b`). Defensive L92 fix attempt 1 (`if ($payload.agentId) {...} elseif ($payload.agent_id) {...}`) PRESERVADO zero-cost backward-compat — futura CC release pudiera añadir field; revert añade churn sin beneficio. Variant F2c (PostToolUse hook complementario emit agentId post-spawn) DESCARTADO plan attempt 2 por race conditions cross-fire pairing pending↔post brittle. Pattern reuse: cualquier hook PreToolUse que requiera subagent identifier DEBE usar `tool_use_id` + meta.json filesystem scan pattern, NO asumir agentId disponible at PreToolUse phase. AR cierra verdict OK-with-finding (NO FAILED): H1 falsified scientifically tested via probe-first + payload dump + revert; H2 CONFIRMED architectural reality identificada; producer+consumer F2c-pivot fix deferred AR hijo `AR_2026-05-29_fase5-1f-tool-use-id-correlation`. (AR_2026-05-29_fase5-1e-agentId-camelcase-mismatch)
- [2026-05-29] CC v2.1.146 PreToolUse correlation pipeline tool_use_id → meta.json filesystem scan → HEX17 agentId resolution → subagent JSONL response extraction — architectural pivot deploy AR hijo 1f (cierre funcional sprint Fase 5.1 + 5.1b). Cross-file producer/consumer coherence: producer (`pretooluse-capture-task-invocation.ps1` L94-L95 + L130) captura `$payload.tool_use_id` top-level + emite field `tool_use_id` snake_case JSONL entry `_pending_turn_tasks.jsonl` (ephemeral); consumer (`stop-capture-skills-token-tax.ps1` L172-L179 cache + L240-L321 refactor scan) lee field + escanea `~/.claude/projects/<repo>/<session_id>/subagents/*.meta.json` matching `toolUseId == pe.tool_use_id` → extract HEX17 vía regex `^agent-([a-f0-9]{17})\.meta$` → build path `agent-<HEX17>.jsonl` para response text extraction phrase-match per_skill_usage. Schema migration aditiva: `agentId` field empty default RETAINED zero-cost backward-compat (futura CC release pudiera emit agentId-on-PreToolUse → fallback path legacy preservado L298-L300). Fase 5.1b/c distinction: 5.1b=deploy correlation infra (este AR 1f); 5.1c=enrichment per_skill_usage phrase taxonomy + per_agent_actually_loaded registry resolution (subagents built-in Explore/Glob/Grep NO en agents.json → per_agent_actually_loaded=[] documented case). G2 smoke evidence verbatim 2026-05-29 12:23-12:24: producer entry `tool_use_id="toolu_01VnqMy3SUTBajDtq4QcLpTL"` non-empty + `agentId=""` empty (arch reality) ✓; consumer debug log `[stop-capture-skills-token-tax.ps1] resolved agentId=a4a2fa8bd6c3cea5b for tool_use_id=toolu_01VnqMy3SUTBajDtq4QcLpTL` ✓ meta.json scan + HEX17 extraction working; turn_id=f8ec8862 `subagents_invoked_this_turn:["Explore"]` populated; `_pending_turn_tasks.jsonl` removed post-consume ✓. Reviewer Step 2 + Step 3 APROBADO. Criticality declarada postmortem: architectural pipeline fundacional Fase 5.1 + cross-ref AR 1e + base future Fase 5.1c. Pattern reuse: cualquier consumer hook que necesite real agentId desde context PreToolUse DEBE adoptar tool_use_id → meta.json filesystem scan pattern (NO asumir agentId disponible at PreToolUse phase, NO usar PostToolUse complementario por race conditions cross-fire pairing brittle). Side-finding observado durante G2 smoke: ghost record `b45dcc8f` 12:24:55 AFTER consumer cleared pending → pending AR hijo 1d (`AR_2026-05-29_fase5-1d-stop-multi-fire-ghost`). 3 nits non-blocker deferred Fase 5.1c: per_agent_actually_loaded=0 (built-in subagents fuera registry), per_skill_usage=0 (taxonomy phrase pendiente), multi-fire ghost (AR hijo 1d). (AR_2026-05-29_fase5-1f-tool-use-id-correlation)
- [2026-06-01] Hard-block enforcement scope-territory vía sentinel one-shot agent_type-aware — hook PreToolUse `pretooluse-block-scope-territory.ps1` reemplaza advisory exit-0 (0% enforcement) por `permissionDecision=deny`. Discrimina caller por `agent_type` payload (string exacto subagent; `<unknown>` root). Subagents legítimos pasan por role-map (planner→plan.md, implementer→agent_templates, knowledge-curator→curator_report); root requiere sentinel-file `.scope_override` one-shot TTL 1h (NO env-var session-level). Absorbe+retira RC1 (`MULTIAGENT_PLAN_MD_OVERRIDE` env-var muere). ≥2 instancias macro-pattern hard-block enforcement (RC1 AR_2026-05-27 + este P3); cross-ref `feedback_root_overreach_persistente` (4ª instancia "regla blanda → regresión"). PROBE Step 1 refutó invariante load-bearing "subagent writes invisibles al hook" ANTES de construir → salvó orquestación. (AR_2026-06-01_p3-hard-block-scope-territory)

### Disciplina de sesión (curated 2026-05-18, AR_2026-05-18_session-discipline-fixes; actualizado 2026-05-18 AR_2026-05-18_system-overhaul-9-acciones; sweep 2026-05-28 AR_2026-05-27_stage1-hardening-anti-overreach post-B4)

- **Arquitectura root-driven (curated 2026-05-18 cap 9, refactored 2026-05-21 AR_B4 post-orchestrator eliminación; sweep 2026-05-28).** CC v2.1.146 Windows: subagents NO tienen Task tool. Solo root (main thread) tiene Task/Agent tool. Por tanto:
  - **Root** = invocador físico único + planner-coordinador lógico + portavoz a <user>. Absorbe rol planning (producía orchestrator pre-B4): produce `plan.md` con secuencia de invocaciones explícitas (qué agente, qué context, qué output esperado, qué gate). Mantiene `hypotheses.md`, anti-loop counter, verdict.
  - **Subagents** (`planner`/`researcher`/`implementer`/`reviewer`/`tester`/`specialist-verse`/etc.) = especialistas. Reportan a root. NO orquestan entre sí (TD-030 RESOLVED B4 — `Task` removido frontmatter implementer + roster).
  - Flow post-B4: <user>→root→`plan.md`→root invoca step N→Task(subagent_N)→reporta a root→root decide step N+1.
  - Cross-ref histórico: orchestrator eliminado documentado verbatim Recent learning [2026-05-21] L134 (β audit trail preservada).
- **Visibility bloque obligatorio cada turn root→<user>.** Formato (curated 2026-05-21, AR_2026-05-21_visibility-banner-per-agent):
  ```
  ═══════════════════════════════════════════════
  [AGENTE-ACTIVO]: <agent-name>
  [MODELO]: <model-id>
  [TAREA]: <descripción 1 línea>
  [HIPOTESIS]: <id si bug-fix activo, "N/A" otherwise>
  ═══════════════════════════════════════════════
  ```
  `<agent-name>` = subagent que root está invocando este turn, O `root direct` si acción directa autorizada (raro, justificar). `<model-id>` resuelto via `config/agents.json` tier → `config/models.json` (e.g., opus/sonnet/haiku para claude_md, deepseek-v4-pro/deepseek-v4-flash para wrappers Python). Permite a <user> interrumpir mid-flow sin esperar output + transparency cost + workflow debugging. Subagents claude_md emiten banner INICIO + línea CIERRE `← {subagent} done, return to root.` per Task invocation. Wrappers Python: root parsea `meta.agent`+`meta.model` del envelope post-PowerShell y emite banner pre/post invocación. Omisión 2+ turns consecutivos mismo AR → `root-discipline-auditor` lo flag como violación.
- **"Subagent bloqueado" requiere error técnico verbatim citado** (curated 2026-05-18, generalized 2026-05-28 post-B4). Root NO puede declarar subagent (planner/researcher/implementer/reviewer/tester/specialist-verse/etc.) bloqueado sin: (a) intento de invocación documentado via Task tool, (b) error verbatim del runtime CC capturado. Asumir bloqueo sin probar = violación. Si bloqueado de verdad → root propone reroute a subagent alternativo Y espera OK <user> antes de ejecutar (NO usurpa rol del subagent bloqueado haciendo el trabajo directo — la invocación al alternativo es root-physical legítima, pero el trabajo lo hace el subagent alternativo).
- **Proyectos UEFN en `<uefn_root>\*`: NO usar git** (curated 2026-05-18 AR_overhaul-9). Save = Push Changes (UEFN editor interno) + manual <user>. Cero `git add/commit/push/reset/checkout`. Si root/agente sugiere git para `<uefn_root>\*` → violación. Hook `pretooluse-guard-protected-files.ps1` bloquea Bash/PowerShell `git *` con CWD o path bajo `<uefn_root>\*`.
- **AR closed-ok sobre proyecto target → append a `<Project>_bugs_fixes_summary.md`** (curated 2026-05-18). Tras TEST-GATE PASS + final_report.md OK + curator pass, root invoca `doc-writer` con `--doc-type=bugs-summary-append` (TODO doc-type a crear en `deepseek_doc_writer.py`, AR siguiente). Formato entry: bug / causa raíz / fix (≤10 líneas/entry). Path destino: `docs/agent_runs/<Project>_bugs_fixes_summary.md`.
- **Verificación de contexto target.** Al iniciar AR sobre proyecto externo (ej. `<uefn_root>\ExampleUEFNProject`), root verifica supuestos antes de planear: ¿hay git?, ¿logs están en chat o en disk?, ¿qué archivos tocó el último cambio?. No arrastrar contexto de AR previo.
- ~~**Prohibición Edit/Write proyecto target desde multiagent-system.**~~ **ANULADA por <user> 2026-05-18.** Root e implementer SÍ aplican Edit/Write directos sobre proyectos target Verse/UEFN. Excepción mantenida: `Content/Verse/Core/*Persistence*.verse` y persistencia → ASK <user> antes (cubierto por hook `pretooluse-guard-protected-files.ps1`). **Cláusula Pattern B (curated 2026-05-28 cross-ref `feedback_root_overreach_persistente`)**: scope discipline aplica — root puede recomendar Edit paths fuera scope plan aprobado pero NO decide unilateralmente. Propuesta `propongo X — ¿confirmas?` obligatoria antes de ejecutar Edit/Write sobre target fuera scope explícitamente aprobado. Root sugiere; <user> confirma dirección.
- **Regla post-FAIL: root re-plan obligatorio con gate <user>** (curated 2026-05-18 cap 9, refactored 2026-05-28 post-B4). Cuando un step termina en FAIL/contradicción (`reviewer` RECHAZADO, `deepseek_tester.py` verdict FAIL, TEST-GATE <user> reporta FAIL, `hypothesis-tracker` exit 4/5, `specialist-verse` retorna UNSAFE/UNKNOWN/INSUFFICIENT, <user> contradice con probe empírico), root **MANDATORIO** invoca `planner` subagent para re-plan antes de cualquier otro step. Planner re-planea, actualiza `plan.md`, propone próximo step a <user>. Root espera OK verbatim <user> antes de invocar siguiente subagent. **PROHIBIDO root direct post-FAIL**: scope unilateral, Bash discovery sin escalación, invocar wrappers sin que planner los haya planeado, avanzar al siguiente step del plan original (obsoleto post-FAIL), Edit/Write directos sin nuevo step planeado. Excepción única: Read read-only de artifacts del AR para preparar reporte a planner. Razón: 3+ instancias cross-AR documentadas + 1 instancia mid-AR `item-offline-spawn-discount` 2026-05-18 (root saltó re-plan post TEST-GATE FAIL → Bash ls + planeaba init hypothesis-tracker unilateral).
<!-- AUTO-CURATED:END -->