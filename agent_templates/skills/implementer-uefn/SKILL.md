---
name: implementer-uefn
description: Skill para implementer cuando target file es .verse (UEFN/Verse). Carga top-11 gotchas inline + effects propagation + Authority resolution + anti-patterns críticos. Auto-match keywords .verse, UEFN editor, weak_map, failable, transacts, decides, localizes, creative_device, module:, Verse Persistence, ExampleUEFNProject, ExampleUEFNProject2.
---

# implementer-uefn

## Cuándo cargar

Auto-match si `file_path` termina en `.verse` O contiene `Content/Verse/`. Override root explícito si AR tocará Verse sin file_path obvio.

## Top-11 gotchas inline (CRITICAL — read before any edit)

| # | Gotcha | Fix idiomatic |
|---|---|---|
| 1 | `event(t){}` literal top-level → err **3512**. NO `module:`, NO file scope, NO `class<concrete>:` sin parent. | Encapsular en `class<concrete>(creative_device)` |
| 2 | `if (not X[])` rollback `<transacts>` si X failable → silent revert writes. Blocker absoluto. | `if (X[]) {} else: <error>` |
| 3 | `return`/`fail` keywords NO existen en `<decides>` functions → err **3535/3506**. | `var Found:logic = false; for (...) { set Found = true }; Found?` |
| 4 | `Print()` tiene `no_rollback` effect → err **3512** en failure context. | Usar `log_channel` + `log` instance + `log.Print()` |
| 5 | `var` top-level **SOLO `weak_map`** (err **3502/3593**). | State no-weak_map → device instance con `@editable` (patrón Core+Device §2.4-bis) |
| 6 | Failable calls (`<decides>`) con `[]` no `()`. | `Floor[x]`, `Mod[x,y]`, `GetUTCNow[]` |
| 7 | `set weak_map[K] = V` propaga `<decides>` al caller. | Envolver `if (set Map[K] = V) {}` (bloque `{}` vacío consume decides) |
| 8 | Archivos sin `module:` wrapper → símbolos en scope **CARPETA padre**, no archivo. | Import path a CARPETA: `using { Verse.Core }` no `using { Verse.Core.PersistenceLayer }` (err **3506/3587**) |
| 9 | **4 weak_maps × 128KB max por isla.** NUNCA renombrar/eliminar/cambiar type publicado. | Backwards compat enforzado por Epic al publicar |
| 10 | `logic` value NO tiene `ToString` overload → interpolación `"{logic_val}"` falla err **3509**. | Convertir explícito: `if (val?) {"true"} else {"false"}` (NO `var`+`set`, lección 20) |
| 11 | Path imports `using { /<account>@fortnite.com/<ProjectName>/Verse/Core/<Module> }`. Placeholder `<ProjectName>` LITERAL → err `vErr:S26`. Path canónico INCLUYE `Verse/`. | Versión dotted relative: `using { Verse.Core.<Module> }` también válida |

## Effects propagation patterns validados (§7 SPR-008)

- `Logger.LogX` compatible `<computes>` default. **INCOMPATIBLE `<transacts>`** (err 3512 'no_rollback effect not allowed').
- `set weak_map[K] = V` propaga `<decides>` al caller (lección 15).
- Archetype constructor `T{...}` OK como retorno en `<computes>` y `<transacts>`.
- **Helper `:void` non-declared NO encapsula `<localizes>` effects al callsite** (AR_2026-05-22 verificado 3 attempts). Solución: remove `<transacts>` cascade upward donde no requiere rollback (pattern `SetCount` L543 `inventory_manager.verse`).

**Patrones NO validados (zona TBD §7)**: `<varies>` + `<transacts>`, effect inheritance en class methods con `<override>`, function pointers passing through effect contexts. Si tocas → flag UNSAFE, escalar specialist-verse.

## Authority resolution

- **KB local primary**: `{{paths.knowledge_base}}/verse-uefn/` (Tier 1 always Read PRE-edit).
- **WebFetch Epic docs BROKEN runtime** (SPA JS-rendered, devuelve shell HTML sin contenido). Authority CASO 3 NO ejecutable hasta Epic fix SPA.
- **Si KB local + specialist-verse devuelven UNKNOWN** → respuesta `UNKNOWN_NEEDS_PROBE` + escalar Lexosi TEST-GATE compilador real. NO inventar.

## Verse-specific anti-patterns críticos

- **Invent signature without source**: NUNCA inventar firma `creative_device` API ni Verse builtins. Check `<project>/docs/API_REFERENCE_GENERATED.md` → `VERSE_SYNTAX_GUIDE.md` Lección 17 → Epic docs (BROKEN runtime) → `unknown, probe required`.
- **`vector3` ambiguity**: anotación explícita `:vector3` falla err **3588** (Verse.org/SpatialMath vs UnrealEngine.com/Temporary/SpatialMath coexisten). Soluciones: chained inline access `GetLocalTransform().Translation.Forward`, namespace qualification full path, inferencia `:=`.
- **`Quotient[float, float]` post-rotation**: pierde precisión silently → truncate `N-1`. Fix: epsilon `+ 1.0` pre-Quotient si `1.0 << K`. Pattern `base_placeable_spot.verse:359,360,426,427`.
- **Skip `Registry.Register[UID, NewItemDefinition]`** al añadir nuevo item: UID=-1 → decoder fail → data perdido reload silent.
- **Apply uniform load path Type=N**: meta-pattern divergence (MaybeBase B4, placed_component item, Scale scaled-entity). Cross-type verify obligatorio.
- **Map iteration / `for:` colon-block / concurrent mutation**: KB gap (TD-020/021). Si tocas, flag UNSAFE → TEST-GATE compilador real.

## Pre-edit checklist (KB Read auto)

- [ ] Read `{{paths.knowledge_base}}/verse-uefn/docs/VERSE_SYNTAX_GUIDE.md`.
- [ ] Read `{{paths.knowledge_base}}/verse-uefn/docs/verse-domain-rules.md`.
- [ ] Read `{{paths.knowledge_base}}/verse-uefn/docs/KB_GAPS.md`.
- [ ] Read `<file_path>` ENTERO antes de Edit.
- [ ] Si tocas weak_map type → schema bump declarado en plan_step.
- [ ] Side-effect scan post-edit: grep refs símbolo modificado.

## Paths canónicos

- KB Tier 1: `{{paths.knowledge_base}}/verse-uefn/docs/`.
- Project: `{{paths.uefn_projects_root}}/Content/Verse/`.
- API ref instanciado: `<project>/docs/API_REFERENCE_GENERATED.md`.
- PERSISTENCE_MAP instanciado: `<project>/docs/PERSISTENCE_MAP.md`.

## Stop conditions Verse-specific

- File path bajo `Content/Verse/Core/*Persistence*.verse` → REJECT, ASK Lexosi (hook bloquea).
- Schema bump weak_map no declarado en plan_step → REJECT, pide planner reformular.
- `WebFetch dev.epicgames.com` falla runtime → NO autoritativo, escalar TEST-GATE.
- Effects question zona TBD §7 → escalar specialist-verse, NO inventar.
