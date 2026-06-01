---
name: reviewer-uefn
description: Skill para reviewer cuando diff implementer toca .verse files. Carga checklist Verse review + effect specifier compatibility + Authority resolution. Auto-match keywords .verse files, UEFN, weak_map, failable, transacts, decides, localizes, schema bump, Push Changes, Verse Persistence, ExampleUEFNProject, ExampleUEFNProject2.
---

# reviewer-uefn

## Cuándo cargar

Auto-match si diff implementer modifica `*.verse` O paths bajo `Content/Verse/`. Override root explícito para review post-mortem Verse-flavored.

## Checklist Verse review

### Pre-review (KB Read auto)

- [ ] Read tier_1_always KB Verse-UEFN: `VERSE_SYNTAX_GUIDE.md`, `verse-domain-rules.md`, `KB_GAPS.md`.
- [ ] Read `<file_path>` modificado ENTERO + 2 archivos vecinos importantes (call-sites).
- [ ] Identificar dependency layer (Core/Systems/Devices) del archivo.

### Diff review

- [ ] **Schema bump** declarado si diff toca weak_map type/struct existente (R1 verse-domain-rules.md). Sin bump → CRITICAL BLOCK.
- [ ] **Effect specifier compatibility**:
  - `Logger.LogX` NO en `<transacts>` (err 3512 silent).
  - `<localizes>` constructor NO en `<transacts>` body NI helper `:void` invocado desde `<transacts>` (AR_2026-05-22 — helper NO encapsula, effects propagan).
  - `set weak_map[K] = V` propaga `<decides>` → envuelto `if (set Map[K] = V) {}`.
- [ ] **`Content/Verse/Core/*` modificado** → ASK Lexosi (singletons protected). Si diff incluye sin pre-aprobación → BLOCK.
- [ ] **Registry pattern**: nuevo `item_definition` declarado MUST tener `Registry.Register[UID, Def]` en `inventory_loader.OnInitialized` (o equivalente init). Grep verificación obligatoria.
- [ ] **Load path Type=N** (`ReadExtraPersistentData` o equivalente decoder) → cross-verify parity con live placement path (`PopulatePlacedEntity` o equivalente). Meta-pattern divergence recurrente.
- [ ] **Loader fail path defensive**: decoder fail debe avanzar stream `DecodedData(0)+1` ints, NO fijo `+= 1` (coincidencia accidental con `additional=0` no es defensa robusta).
- [ ] **Build staleness check**: diff con cambios pequeños sobre área tocada por AR cerrado mismo día → flag "verify Push Changes UEFN ejecutado + build version in-game".

### Anti-patterns to flag

- `if (not X[])` con X failable → ROLLBACK silent transacts (Gotcha #2).
- `return`/`fail` en `<decides>` → err 3535/3506 (Gotcha #3).
- `Print()` en failure context → err 3512 (Gotcha #4). Sustituir por `log_channel.Print`.
- Interpolación `"{logic_val}"` → err 3509 (Gotcha #10). Convertir `if (val?) {"true"} else {"false"}`.
- `vector3` annotation explícita → err 3588 (ambigüedad namespace). Inline chained o `:=`.
- `Quotient[float, float]` post-rotation sin epsilon → truncate `N-1` silent.
- Map iteration / `for:` colon-block / concurrent mutation **UNSAFE pending KB gap** (TD-020/021). Flag UNSAFE, escalar TEST-GATE.
- Helper `:void` envuelve `<localizes>` para "encapsular" → NO funciona. Effects propagan al callsite. Remove `<transacts>` cascade upward.

## Authority resolution policy (review)

Si diff implementer cita pattern Verse:

- **CASO 1**: KB local cita postmortem/test empírico/SPR → gana KB. Confirmar source citado.
- **CASO 2**: KB local afirma sin probe → Epic gana (BROKEN runtime → escalar).
- **CASO 3**: Epic posterior a verificación nuestra → probe empírico TEST-GATE Lexosi.

**NUNCA decides solo qué caso aplica.** Ambiguo → escalar Lexosi.

## Verdict levels

- **APPROVED**: diff matches documented Verse pattern, source citado, tests TEST-GATE plan presente.
- **APPROVED-WITH-CAVEATS**: pattern OK pero cross-type testing pending O effects TBD §7 → caveats explicitos.
- **CHANGES-REQUESTED**: anti-pattern detectado, schema bump missing, Registry.Register missing, etc.
- **BLOCK-CRITICAL**: `Content/Verse/Core/*` sin ASK, weak_map type modificado sin migration, persistence corrupta risk.

## Paths canónicos

- KB Tier 1: `{{paths.knowledge_base}}/verse-uefn/docs/`.
- Project: `{{paths.uefn_projects_root}}/Content/Verse/`.
- PERSISTENCE_MAP: `<project>/docs/PERSISTENCE_MAP.md`.
- TD docs: `{{paths.docs.tech_debt}}/`.

## Anti-sycophancy (Capa 1 reviewer)

- "Sin cambios necesarios" / "Sin blockers" son verdicts VÁLIDOS. NO inventar trabajo.
- NO sugerir refactor cosmético no relacionado con diff.
- Si encuentras bug colateral mientras revisas → flag TD ticket separado, NO bloquear diff actual por ello.
