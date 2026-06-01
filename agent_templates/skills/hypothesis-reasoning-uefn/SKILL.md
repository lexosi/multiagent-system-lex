---
name: hypothesis-reasoning-uefn
description: Skill para hypothesis-reasoning en bug-fix UEFN/Verse. Carga bug class taxonomy + anti-loop integration + probe pattern Verse-specific (identity, DIANA discriminators). Auto-match keywords .verse bug, UEFN crash, weak_map iteration, failable propagation, spawn timing race, persistence loss post-restart, effect specifier mismatch, Quotient float precision.
---

# hypothesis-reasoning-uefn

## Cuándo cargar

Auto-match si AR es bug-fix Verse con keywords: crash post-restart, weak_map iteration, failable silent, spawn timing race, persistence loss, effect mismatch, float truncate, build staleness. Override root explícito al inicializar hypotheses.md AR Verse bug-fix.

## Bug class taxonomy UEFN

### 1. weak_map iteration crash (concurrent mutation)

- **Síntoma**: crash o silent fail durante iteración `for (K:M, V:=M[K])` con mutation concurrente.
- **KB gap actual**: TD-021 NO cubierto. Hipótesis Verse-specific UNSAFE hasta KB autoritativa. Escalar TEST-GATE compilador real.

### 2. Failable propagation silent

- **Síntoma**: decoder fail path silent, data perdido al reload. Ejemplo: `inventory_loader.verse:257` `ReaderIndex += 1` fijo vs happy path `DecodedData(0)+1` ints.
- **Pattern**: skip size en fail path debe matchear happy path size sea cual sea `additional` count. Coincidencia accidental con `additional=0` no es defensa robusta.
- **Probe**: log decoder fail branch con stream position + decoded UID + expected vs actual skip.

### 3. Spawn timing race (post-restart, post Push Changes)

- **Síntoma**: component rehydration incomplete antes de consumer. Ejemplo: `spawn_controller.verse:108 GetComponent[placed_component]` fail silent post-restart porque `placeable_component.ReadExtraPersistentData` no ejecutó `Entity.AddComponents(placed_component)` que sí hace live `PopulatePlacedEntity`.
- **Probe**: DIANA 5-step discriminators replicando `if:` cascade original con `Print` en cada step (success path + fail path), vars `_Probe` suffix para no shadow originales. 1 ciclo <user> resuelve sub-condición.

### 4. Persistence post-restart loss

- **Pattern recurrente**: Type=N load path omits component live (Type=0) añade. `MaybeBase` / `placed_component` pattern.
- **Detection**: grep `PopulatePlacedEntity` vs `ReadExtraPersistentData`. Verify parity components AddedComponents.
- **NO requiere migration schema** si componente es runtime-only (no `@editable` fields). Fix +N líneas parity load path.

### 5. Effect specifier mismatch (3512 helper `:void` NO encapsula `<localizes>`)

- **Síntoma**: err 3512 'no_rollback effect not allowed' al invocar `<localizes>` constructor desde `<transacts>` body directamente O via helper `:void`.
- **Verificado empírico AR_2026-05-22** 3 attempts: attempt 1 (directo) FAIL, attempt 2 (helper `:void` separado) FAIL, attempt 3 (remove `<transacts>` cascade upward 5 firmas + inline RewardLabel) PASS.
- **Hipótesis**: helper `:void` NO encapsula effects implícitos del body. Effects propagan a firma efectiva del callsite.

### 6. Float precision Quotient/Mod truncate N-1 post-rotation

- **Pattern**: `Quotient[float, float]` sobre valores post-`Rotation.UnrotateVector()` trunca silently a `N-1` (drift ~1e-4 `N*VoxelSize - 0.000131`).
- **Visible solo celdas borde grid**, NO fail compile/runtime. Detection visual in-game.
- **Probe**: log `InvertedLeft`/`RelativeSecond`/`VoxelSize`/`GridSize`/`ChunkCount` pre-Quotient.
- **Fix**: epsilon `+ 1.0` pre-Quotient si `1.0 << K`.

### 7. Build staleness Verse (meta-class)

- **Síntoma CRITICAL**: bug residual de fix previo no-deployed. ARs mismo día tocando mismo método → sospechar staleness antes de hipótesis independiente.
- **Verify**: Push Changes UEFN ejecutado + build version in-game match.

## Anti-loop integration

- **3 attempts max per hipótesis**. 4º → class-jump obligatorio.
- **Probe antes de fix** (anti-loop regla #2). Excepción: evidencia ESTÁTICA verificable leyendo source code (presencia/ausencia líneas) → probe runtime redundante. Justificar explícito en hypothesis tracking.
- **Probes con identity** (Translation/UID/hash) obligatorios si hipótesis involucra divergencia de instancia. State flags solos (Locked=true/false) producen interpretaciones erróneas. Validado AR_2026-05-17 lock-steal probes A1-A5 v2.
- **Observación <user> > hipótesis del agente** (anti-loop regla #3), pero distinguir modo:
  - Evidencia → falsificar hipótesis + replanear.
  - Intuición → discutir + pedir test confirmatorio.
  - Ambiguo → pedir clarificación verbatim.
- **Source-of-truth divergence check** antes de bug de lógica (anti-loop regla #4). Type=N vs Type=0, state vs UI, registry vs disk.
- **Predicciones visuales** contrastadas con observación real (anti-loop regla #5). Validado AR_2026-05-18 placeable-spot — H_OVERFLOW falsificada por <user> "garbage es mecánica real, no fantasma".

## Probe pattern Verse-specific

```verse
# Pattern DIANA 5-step discriminator
var Step1_Probe:logic = false
if (Cond1[]):
    set Step1_Probe = true
    Log.Print("[DIANA] step1 OK")
else:
    Log.Print("[DIANA] step1 FAIL")

# Repetir N steps. Vars `_Probe` suffix evita shadow originales.
# Identity en probe: Translation, UID, hash.
```

## Checklists

### Inicializar hypotheses.md

- [ ] Bug class identificada de taxonomy arriba.
- [ ] KB gap check (TD-020/021 mapa iteration / concurrent mutation → UNSAFE flag).
- [ ] Hipótesis H1..HN enumeradas con tipo evidencia esperada (DINÁMICA / ESTÁTICA).
- [ ] Probe design para cada H con identity declarado.

### Per hypothesis check

- [ ] Attempts counter ≤3.
- [ ] Probe ejecutado (o evidencia estática justificada).
- [ ] CONFIRMED / FALSIFIED status declarado pre-fix.
- [ ] Si CONFIRMED → implementer puede proceder. Si FALSIFIED → próxima H o class-jump.

## Paths canónicos

- KB Tier 1: `{{paths.knowledge_base}}/verse-uefn/`.
- AR dir: `{{paths.docs.agent_runs}}/AR_<id>/hypotheses.md`.
- TD docs: `{{paths.docs.tech_debt}}/`.

## Anti-patterns hypothesis-reasoning

- Hipótesis Verse sin probe confirmatorio (excepto evidencia estática justificada).
- Probe sin identity en divergencia de instancia.
- Class-jump skipped post-3 attempts mismo class.
- Inventar Verse semantics (mapa iteration / concurrent mutation) sin KB authoritative.
- Ignorar observación empírica <user> por intuición agente.
