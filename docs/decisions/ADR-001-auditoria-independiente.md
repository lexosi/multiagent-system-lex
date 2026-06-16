# ADR-001 · Auditoría independiente del cierre de AR (outcome / process) y protección de escritura por `agent_type`

- **Estado:** Aceptada
- **Fecha:** 2026-06-16
- **Ámbito:** Ciclo de cierre de un Agent Run (AR); rol del `root`; agentes auditores.

> **Nota de procedencia.** Este es el primer ADR de *este repositorio público*. No es la primera decisión del sistema: el sistema acumula 123 ARs productivos con audit trail completo, y la serie de ADRs internos vive en otros repos del proyecto. Este ADR se extrae y adapta para compartir en abierto **precisamente porque no contiene información de proyectos propios** — documenta una decisión de arquitectura del orquestador, no datos de ningún cliente o build. La numeración (`ADR-001`) es secuencial *por repositorio*, según la convención estándar de ADRs.

---

## Contexto

El `root` (main thread, único con `Task`/`Agent` tool) ejecuta el trabajo de un AR **y**, hasta este cambio, emitía también el *verdict* de éxito en su propio `final_report.md`. Es decir: el mismo actor producía el resultado y se ponía la nota.

Eso es **auto-evaluación sin independencia estructural** (self-grading). El problema no es que el `root` sea deshonesto; es que un evaluador que juzga su propio trabajo, leyendo su propia narrativa, **aprueba de forma estructuralmente inevitable**. No hay separación entre el ejecutor y el juez.

**Cómo se detectó:** revisión manual, no por el CI ni por ningún test. Esto es relevante por sí mismo: un test verde confirma que *lo que mides* pasa, pero no te dice si *estás midiendo lo correcto*. La ausencia de independencia del evaluador no la detecta un test de la pipeline — la detecta el criterio de quien audita el propio aparato de medición. El fallo era estructural, no funcional, y por eso era invisible para la batería automática.

Contradicción doctrinal previa, ya anotada en el sistema: el `root` "producía su propio `final_report` con verdict" mientras la dirección vigente exigía un juez independiente.

---

## Decisión

### 1. Split en dos auditores independientes

| Auditor | Pregunta que responde | Veredicto |
|---|---|---|
| `outcome-auditor` | ¿El entregable cumple la meta declarada? (RESULTADO) | `OK` / `PARTIAL` / `FAILED` |
| `process-auditor` | ¿El `root` siguió la disciplina de rol? (CÓMO) | `CLEAN` / `VIOLATIONS_N` |

El `root` deja de emitir verdict. Pasa a escribir **solo el resumen factual** (qué se hizo) en `final_report.md`. El verdict de éxito lo emite `outcome-auditor`; el de disciplina, `process-auditor`.

### 2. Independencia por fuente: evidencia cruda, no narrativa

Ambos auditores confían **solo en fuentes crudas verificables**:

- El **transcript crudo del main-thread** (`<session_id>.jsonl`): acciones reales del `root` (tool calls, edits, `tool_result`, exit codes, gates humanos).
- El **`plan.md`** del AR: objetivo y scope declarados.
- **Evidencia en disco**: los artefactos que el AR dice haber producido (verificación por `Glob`/`Read`).

El `final_report.md` del `root` se lee **únicamente para contrastar**, nunca como fuente de verdad. Una divergencia entre el transcript y el `final_report` es un hallazgo de primer orden. Regla explícita en ambos templates: *ignorar cualquier framing o narrativa del prompt de invocación del `root`*.

Esto es lo que hace la independencia **real** y no cosmética: un auditor que lee la misma evidencia cruda puede contradecir a un `root` que se esté racionalizando. Un auditor que solo leyera el auto-informe del `root` sería un sello de goma.

### 3. El verdict gobierna downstream, el del `root` no se propaga

`knowledge-curator` toma el verdict del `outcome_audit_report.md` independiente, **no** del `final_report.md` self-authored. Aunque el `root` escribiera un verdict en su resumen, no tiene consumidor: es ruido sin canal. La protección no es impedir que el `root` opine — es que su opinión no gobierne nada.

### 4. Protección de escritura por `agent_type` (enforcement a nivel hook)

Para cerrar la falsificación —que el `root` escriba él mismo el informe del auditor haciéndose pasar por él— se añade una regla de `deny` en el hook `PreToolUse`:

- `outcome_audit_report.md` → solo lo escribe el subagente cuyo `agent_type` es exactamente `outcome-auditor`.
- `process_audit_report.md` → solo `process-auditor`.
- Cualquier otro caller (incluido el `root`, que llega con `agent_type` ausente → `<unknown>`) → **`deny`**.

El campo `agent_type` del payload `PreToolUse` discrimina al caller: presente = nombre del subagente; ausente = `root`. Verificado empíricamente (los strings literales `outcome-auditor` / `process-auditor` se confirmaron leyendo el log de denegación real, no por suposición).

**Validación:** smoke test no destructivo con matriz de verdad. `root` → `DENY` en ambos reports; cada auditor → `ALLOW` sobre el suyo, con escritura confirmada en disco. El candado cierra y la llave correcta abre, sin romper al auditor legítimo.

### 5. Verificación dirigida de claims de subagente (v2-mínimo)

Las acciones del `root` quedan completas en el transcript del main-thread, pero los pasos internos de un subagente viven en su propio transcript (`<session_id>/subagents/agent-<hex>.jsonl`), fuera de ese registro. Un subagente puede, por tanto, afirmar algo en el resultado que devuelve al `root` ("fue read-only", "los tests pasaron") sin que esa afirmación quede contrastada.

Para cerrar ese hueco sin saturar al auditor, este puede abrir el transcript interno de un subagente —localizándolo por su cuenta vía `session_id` → `subagents/`, cruzando el `toolUseId` del bloque `Agent` con el `meta.json`— **solo bajo un disparador estricto de tres condiciones (AND)**:

1. El resultado del subagente afirma algo **verificable en su propia traza** (corrió tests, fue read-only, editó N archivos).
2. La afirmación es **material para el verdict**: si fuera falsa, cambiaría el resultado (`OK`↔`FAILED`/`PARTIAL`) o la disciplina (`CLEAN`↔`VIOLATIONS_N`).
3. **Nunca por rutina.** Sin un claim material que la traza interna pueda confirmar o refutar, el auditor no abre nada y se queda en el main-thread.

Una divergencia entre lo que el subagente afirma y lo que muestra su traza interna es un hallazgo de primer orden, igual que la divergencia transcript↔`final_report`.

**Validación:** smoke bidireccional sobre ARs reales. El auditor abrió el transcript interno por decisión propia cuando un claim de conducta lo exigía (confirmó "read-only" contra cero `Edit`/`Write` internos) y, en la dirección opuesta, no abrió transcripts cuando el main-thread y el disco ya bastaban. El disparador discrimina: ni laxo (no escarba por si acaso) ni inútil por estricto (se activa cuando hace falta).

---

## Límites conocidos

Documentados de forma explícita; no son descuidos, son fronteras de alcance decididas.

1. **La invocación es retrospectiva y best-effort, no un hard-gate.** Un hook no puede *invocar* un agente en Claude Code (solo el `root` tiene `Agent` tool); un hook solo puede *denegar* un tool call, no originar uno. Por tanto, la auditoría corre en la sesión siguiente al cierre, empujada por un flag persistente (`stop-no-auditor.ps1` marca → `SessionStart` recuerda) que reaparece en cada arranque hasta que ambos reports existen. No se puede forzar la invocación; se puede garantizar el recordatorio. Hacerla síncrona con `deny` en el cierre exigiría un punto de cierre interceptable, que hoy no existe (el estado de un AR se *infiere por archivos*, no por una acción explícita). Queda como endurecimiento futuro.

2. **Gap de shell.** La regla de protección es path-based, igual que el resto de reglas del hook. No intercepta una escritura por shell con redirección (`Set-Content`, `>`, etc.), porque esos tool calls no llevan `file_path`. Es una limitación consistente en todas las reglas path-based del guardia, no específica de esta. Cerrarla exigiría un parser de comandos sobre `tool_input.command`, frágil y con cobertura incompleta; se prefiere documentar el límite a desplegar un parche que aparente cerrarlo.

3. **Alcance de la auditoría de subagentes.** Los auditores leen el transcript del main-thread —que contiene las acciones del `root` de forma completa, incluida cualquier usurpación: si el `root` hace el trabajo en vez de delegarlo, aparece como edit directo y no como `Task`— y, bajo el disparador estricto de la sección 5, abren transcripts internos de subagente para verificar claims materiales. Lo que **no** se hace es una auditoría exhaustiva de todos los pasos internos de todos los subagentes (mediana ~7 por sesión, hasta 100): leerlos siempre saturaría el contexto del propio auditor sin valor proporcional. La verificación es dirigida, no total. Consecuencia residual: un subagente podría afirmar en falso algo que su claim **no expone como verificable**, en cuyo caso no dispara la apertura del transcript. La auditoría exhaustiva de internos de subagente es un objetivo distinto y mayor (v2-completo); se mantiene fuera de alcance de forma consciente.

---

## Consecuencias

**A favor:**

- El ejecutor ya no se pone la nota. La evaluación tiene independencia estructural de lectura (evidencia cruda) y de canal (el verdict del `root` no se propaga).
- El informe del auditor es inviolable por el `root` a nivel hook, verificado en disco.
- La separación outcome/process distingue "¿se logró?" de "¿se hizo bien?" — dos ejes que antes se mezclaban en un único verdict.
- La verificación dirigida (sección 5) permite contrastar claims de subagente contra su traza interna sin auditar todo siempre, cerrando el hueco de "el subagente afirma y nadie comprueba" para los claims que importan.

**En contra / coste:**

- Latencia: el verdict no es síncrono con el cierre; llega en la sesión siguiente.
- Dependencia de la cooperación del `root` para la *invocación* (no para el contenido): el sistema solo puede recordar, no obligar, dada la plataforma.
- Tres límites conocidos (arriba) que acotan la garantía. Se asumen de forma consciente frente a alternativas que aparentarían más cobertura de la real.

---

## Referencias

- Templates: `agent_templates/outcome-auditor.md`, `agent_templates/process-auditor.md`.
- Doctrina: `CLAUDE.md` — roster, ciclo de vida del AR, bloque de auditoría independiente.
- Enforcement: `hooks/pretooluse-guard-protected-files.ps1` (regla de protección por `agent_type`).
- Backstop: `hooks/stop-no-auditor.ps1`, `hooks/session-start-substitute-paths.ps1` (§7.6).
