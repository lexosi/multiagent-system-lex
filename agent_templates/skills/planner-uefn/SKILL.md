---
name: planner-uefn
description: Skill para planner cuando AR target es proyecto UEFN/Verse (.verse files, UEFN editor, Verse Persistence, weak_map, failable, ExampleUEFNProject, ExampleUEFNProject2, Content/Verse/Core, persistence schema). Carga conocimiento dominio para planning multi-step en sprints Verse.
---

# planner-uefn

## Cuándo cargar

Auto-match si AR tickets mencionan: `verse`, `uefn`, `.verse files`, `Verse Persistence`, `weak_map`, `failable`, `Content/Verse/Core`, proyecto target `ExampleUEFNProject`, `ExampleUEFNProject2`, `<uefn_root>\*`, `persistence schema`, `module:`, `creative_device`, `Push Changes`.

## Arquitectura típica UEFN

- **Layout proyecto**: `Content/Verse/Core/*` (singletons protegidos, ASK Lexosi antes), `Content/Verse/Systems/*`, `Content/Verse/Devices/*`. Dependency layers (verse-domain-rules.md): Core no importa Systems, Devices nadie importa.
- **Persistence módulo**: pattern `PersistenceLayer` + `<project>/docs/PERSISTENCE_MAP.md` (instanciado en proyecto, no template). Límite inviolable: **4 weak_maps × 128KB max por isla**.
- **Módulos comunes**: Inventory, Economy, Persistence, Selectable, Placement, Spawn (item/scaled-entity spawning), Base (voxel grid).
- **Codecs**: load paths Type=0 (live placement) vs Type=N (persistence rehydration) — pattern `CodecPlaceReference.AdditionalDecoder` para condicional por Type.

## Sprint/feature pattern Verse

1. **Plan steps numerados ONE-FILE-PER-TURN** (Cap N4 STOP-GATE per-step Lexosi entre steps).
2. **Schema bump obligatorio** si plan toca weak_map type/struct existente (R1 verse-domain-rules.md). Migration pattern: option-version (`template_PERSISTENCE_MAP.md` §3 + §8). NO renombrar/eliminar weak_map publicado.
3. **Registry pattern** para nuevo `item_definition`: declarar field NO equivale a registrarlo. MUST añadir `Registry.Register[<UID libre>, <Def>]` en `inventory_loader.OnInitialized` (o equivalente). Sin Register → UID=-1 → decoder failable → data perdido al reload.
4. **TEST-GATE Lexosi UEFN manual obligatorio** post-implementation. Compile success ≠ deployed. Push Changes UEFN obligatorio antes de declarar fix activo.
5. **Cross-type testing obligatorio** al modificar load paths (Type=0 live vs Type=1 item vs Type=2 scaled-entity). Meta-pattern recurrente: load path Type=N omite paso que sí ejecuta path Type=0.

## Paths canónicos

- KB Verse-UEFN: `{{paths.knowledge_base}}/verse-uefn/` (Tier 1 always Read).
- Project target: `{{paths.uefn_projects_root}}` (ej. `<uefn_root>\ExampleUEFNProject\`).
- AR dir: `{{paths.docs.agent_runs}}/AR_<id>/`.
- PERSISTENCE_MAP instanciado: `<project>/docs/PERSISTENCE_MAP.md`.
- MODULES_DEPENDENCY_GRAPH instanciado: `<project>/docs/MODULES_DEPENDENCY_GRAPH.md`.

## Gotchas top-7 (planning-relevant)

1. **Build staleness Verse**: editar código ≠ fix deployed. Plan siempre incluye step "Push Changes UEFN + verify build version in-game" antes de TEST-GATE.
2. **ARs mismo día tocando mismo método/área**: sospechar staleness del primero antes de tratar segundo como bug nuevo (AR_2026-05-17_lock-steal-precarga-noop CRITICAL).
3. **Registry pattern**: nuevo `item_definition` requiere `Registry.Register[UID, Def]` en init. UID libre verificable via grep `Registry.Register\[` en init function.
4. **Load paths divergence Type=N vs Type=0**: meta-pattern recurrente (MaybeBase B4, placed_component item, Scale scaled-entity). Plan obligatorio: verificar parity entre `PopulatePlacedEntity` (live) vs `ReadExtraPersistentData` (persistence).
5. **`placed_component` runtime-only**: no `@editable` fields → fix NO requiere migration schema ni bump Version. Verificar antes de planear migration.
6. **HUD success ≠ verificación funcional**: plan TEST-GATE requiere interacción real post-reload, no solo HUD message.
7. **KB gap map iteration / `for:` colon-block / concurrent mutation**: si plan toca estas semánticas, marcar UNSAFE → escalar TEST-GATE compilador real, NO inventar.

## Checklists

### Pre-plan

- [ ] AR ticket leído + KB Verse-UEFN MEMORY.md Read pre-planning.
- [ ] Proyecto target identificado + `<project>/docs/PERSISTENCE_MAP.md` Read si tocará persistencia.
- [ ] Verificar si fix previo mismo día tocó misma área (sospechar staleness).
- [ ] Identificar dependency layer (Core/Systems/Devices) del archivo target.

### Plan emitido

- [ ] Steps numerados ONE-FILE-PER-TURN.
- [ ] Cada step declara `target_lines` específico (no rangos vagos).
- [ ] Schema bump documentado si weak_map type modificado.
- [ ] Step final = "Push Changes UEFN + TEST-GATE Lexosi in-game".
- [ ] Cross-type testing enumerado si load path tocado.

## Anti-patterns planning

- **Skip TEST-GATE Lexosi**: declarar fix activo sin in-game verification.
- **Asumir Push Changes = fix deployed sin verify build version**: build staleness silent.
- **Plan sin Registry.Register para nuevo item_definition**: data perdido al reload silentemente.
- **Uniformizar load path sin cross-type verify**: regresión visual silenciosa cross-Type (asimetría Entity.Scale vs Niagara scaled-entity).
- **Tocar `Content/Verse/Core/*` sin ASK Lexosi**: singletons protegidos.
- **Plan tocar persistence Verse sin escalation explícita**: hook bloquea Edit/Write.
