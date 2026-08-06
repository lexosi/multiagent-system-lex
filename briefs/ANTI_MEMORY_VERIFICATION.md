# ANTI_MEMORY_VERIFICATION — Verdad fresca sobre memoria/intuición (cross-agente)

**Tipo**: doc canon de gobernanza (cross-dominio: verse-uefn, unreal, blender, y cualquier dominio futuro).
**Aplica a**: **root Y TODOS los subagentes** (specialists, implementer, planner, curator, auditores). No es una regla solo-root.
**Cross-ref**: `briefs/KB_SOURCE_HIERARCHY.md` (N0 empírico gana SIEMPRE), `briefs/ANTI_SYCOPHANCY_ADDENDUM.md`, CLAUDE.md (C1/C3/B3/D2).

---

## Para qué sirve

Doc único DRY que canoniza **la regla anti-memoria** + el **routing de captura por dueño**. Nace del post-mortem **2026-07-01** (2 ARs NO cerrados). La falla NO fue falta de conocimiento. Fue: **root Y los subagentes afirmaban estado/hechos de dominio desde MEMORIA/INTUICIÓN en vez de desde una verificación FRESCA (tool response)**.

Evidencia de causa (<user> = oráculo, N0 verbatim):

1. <user> pasaba capturas y el agente a veces **ni las miraba** — respondía por intuición/recuerdo.
2. <user> decía "esto está así" y el agente iba a su **memoria del último look MCP (stale)** en vez de comprobarlo en vivo.
3. La conversación guardaba **solo PARTE** de lo que <user> explicaba (concreto y load-bearing) → se perdían instrucciones.

**Patrón único detrás de todo**: sustituir VERDAD-FRESCA por MEMORIA/INTUICIÓN.

---

## (a) Principio — la regla gobernante

> **Afirmar un estado/hecho de dominio → SIEMPRE desde una tool response FRESCA. NUNCA desde el recuerdo del último look ni de la intuición.**

Cubre: editor UEFN/UE, grafo de material, posiciones/tamaños/bindings, comportamiento runtime, estado de asset.

Fuentes válidas de VERDAD-FRESCA (las tres):

| Fuente fresca | Qué es |
|---|---|
| **Read de la captura provista** | <user> pega la ruta → `Read <captures_dir>\<archivo>.png` en ESTE turno. |
| **Introspección MCP en vivo** | Consulta MCP UEFN/UE al estado actual del asset/editor AHORA (no el recuerdo del último dump). |
| **Palabra verbatim de <user>** | Lo que <user> afirma explícitamente (N0 oráculo). |

**Prohibido**: responder desde el recuerdo de un dump MCP previo (stale), desde intuición sobre cómo "debería" estar, o desde un look de hace N turnos.

**Autoridad**: principio general de uso de memoria — **la memoria es superficie de PISTAS, no de autoridad: verifica leyendo el estado actual**. Reforzado por evidencia multi-agente 2026 (Galileo, hallucination): **toda afirmación factual debe nacer de una tool response; los agentes no generan hechos libremente.** Cross-ref anti-sycophancy rule 1.

---

## (b) Routing de captura POR DUEÑO

El routing es **por TIPO/DUEÑO del artefacto**, NO hardcoded a un único agente. Root no interpreta una captura de un dominio que no es suyo: la delega al specialist dueño.

| Tipo de captura | Agente dueño que la LEE |
|---|---|
| Código / comportamiento Verse | `specialist-verse` |
| UE 5.x Editor Python / assets UE | `specialist-unreal` |
| Blender / `.blend` / GLB | `specialist-blender` |
| Estado del código (grep/Read) | `implementer` |

**Regla de root**:

> **Root LEE la captura O la DELEGA al subagente-dueño por tipo. NUNCA la routea a un único dueño por defecto.**

**Formato de entrada (INPUT 1 <user>)**: <user> **PEGA LA RUTA** (`<captures_dir>\<archivo>.png`) como texto en el chat; NO arrastra imagen content-block. El token de path es la señal detectable.

---

## (c) Qué es enforcement-detectable y qué no

**Honestidad sobre los límites** (RFC anthropics/claude-code #45427: los hooks gatean **tool-calls, NO texto**; + probe propio M0 2026-06-27: el TEXTO de root NO es interceptable por PreToolUse).

| | Señal | Mecanismo |
|---|---|---|
| **DETECTABLE** (firma dura) | En el turno de usuario aparece un token de path de captura (`<captures_dir>\...\*.png`) **Y** el turno del asistente termina SIN un `Read` de ese path **NI** una invocación `Agent`/`Task` cuyo prompt CONTENGA ese path. = **"ni la miró ni la delegó"**. | Stop hook lee transcript `.jsonl` post-hoc, `decision:block` one-shot (dedup per-firma). |
| **NO DETECTABLE** (solo regla + spec-verbatim + auditor) | (1) Afirmar estado de asset desde memoria MCP stale — texto libre, no parseable. (2) **Owner-correctness**: ¿fue al dueño CORRECTO por tipo? — no machine-decidible barato. | Regla capa 1 (este doc + templates) + `process-auditor`. |

La firma dura exige "leída **O** delegada". Que la delegación fuese al dueño CORRECTO y que el subagente EFECTIVAMENTE leyera su captura (fuera del main-thread) quedan en regla + auditor, no en el hook.

Enforcement duro: **Stop hook exit-2 / `decision:block`** — único punto que muerde "responder de memoria", vía firma determinista de tool-call ausente.

---

## (d) Frescura + spec-verbatim + anti-runaway

| Mecanismo | Regla |
|---|---|
| **1 tarea = 1 contexto** | Agentes efímeros por tarea. **Máx 3 reinvocaciones** del mismo subagent en el mismo AR antes de exigir contexto fresco (nueva invocación limpia, NO acumular). Cross-ref B3 (context rot: −30% precisión a 100K+ tokens). |
| **Spec-verbatim-a-disco** | Al iniciar trabajo con instrucciones precisas de <user>, guardar su explicación **VERBATIM** en `<ar_dir>/USER_SPEC_VERBATIM.md`. El agente lee ESE archivo, NO su memoria. Ataca la pérdida parcial de contexto (causa 3 del post-mortem). |
| **Anti-runaway** | Subagent que se re-dispara/degrada (fabrica requisitos, re-autora sin gate) → **matar + contexto fresco; NO relayar su invento**. Cross-ref runaway 2026-07-01. |

---

## (e) Cross-refs

| Ref | Qué aporta |
|---|---|
| `briefs/KB_SOURCE_HIERARCHY.md` | **N0 empírico in-game GANA SIEMPRE.** El KB es superficie de pistas, no de autoridad; el estado real se verifica leyéndolo. |
| **C1** (CLAUDE.md) | Root sin autoridad de dominio → default = enrutar al specialist aunque "lo sepa". |
| **C3** (CLAUDE.md) | Relevo verbatim del subagente; root sintetiza poco, atribuye la fuente. |
| **B3** (CLAUDE.md) | Contexto fresco intra-AR: 1 tarea = 1 contexto, máx 3 reinvocaciones. |
| **D2** (CLAUDE.md) | Checkpoint/restart entre ARs grandes (frescura de root inter-AR). |

**Fuentes externas 2026**:

- **Galileo** — multi-agent hallucination: toda afirmación factual debe nacer de una tool response.
- **RFC anthropics/claude-code #45427** — hooks gatean tool-calls, NO texto (límite duro del enforcement).
- **Stop hook exit-2** como enforcement determinista.

---

## Resumen operativo (1 línea por agente)

- **¿Vas a afirmar estado de dominio?** → Read captura fresca / MCP en vivo / verbatim <user>. NUNCA de recuerdo.
- **<user> pegó una ruta de captura** → root LEE o DELEGA al dueño-por-tipo (Verse→specialist-verse, UE→specialist-unreal, Blender→specialist-blender). NUNCA por-defecto a un único dueño.
- **Instrucción precisa de <user>** → guárdala verbatim a `<ar_dir>/USER_SPEC_VERBATIM.md` y lee ESE archivo.
- **Subagent degradando/inventando** → matar + contexto fresco, NO relayar el invento.
- **KB dice X pero in-game dice Y** → gana in-game (N0). Corrige el KB, no la realidad.
