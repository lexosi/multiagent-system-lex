---
name: coherence-auditor-uefn
description: Skill para coherence-auditor en dominio UEFN/Verse. Detecta source-of-truth divergence runtime vs static, ghost entries AssetRegistry, build staleness, Type=N vs Type=0 load asymmetry. Auto-match keywords .verse files, UEFN editor, weak_map state, persistence, HUD vs functional, Type=0 Type=1 Type=2, MaybeBase, placed_component, Push Changes build staleness.
---

# coherence-auditor-uefn

## Cuándo cargar

Auto-match si AR investiga bug con síntomas: bug post-restart, HUD success pero functional fail, divergence Type=N vs Type=0, ghost entries (registry True + load None), build staleness Verse, racing condition spawn timing. Override root explícito para audit cross-source-of-truth.

## Source-of-truth divergence Verse (top patterns)

### 1. weak_map state vs UI display

- **Pattern**: HUD reporta success pero state weak_map NO refleja change post-reload. Pattern recurrente AR_2026-05-17_lock-steal-precarga-noop.
- **Detection**: probe runtime con identity (Translation/UID/hash), NO solo state flags (Locked=true/false). Verificación funcional REAL post-reload obligatoria (aplicar bloqueador, retomar pet, interactuar con resultado).
- **Anti-pattern**: declarar fix activo basado en HUD success sin re-test interactivo post-reload.

### 2. Load paths Type=N vs live Type=0

- **Pattern recurrente cross-AR (3 instancias confirmadas)**:
  - 1ª: `MaybeBase` derivation gotcha (AR_2026-05-16 B4) — load path no setea `MaybeBase`.
  - 2ª: `placed_component` item (AR_2026-05-17) — Type=1 load omite `Entity.AddComponents(placed_component)` que sí hace live `PopulatePlacedEntity`.
  - 3ª: Scale scaled-entity (AR_2026-05-18) — load path uniforme `PlaceReference.Scale` causa doble escalado Type=2 (Niagara hardcoded vs Entity.Scale).
- **Detection**: grep `PopulatePlacedEntity` vs `ReadExtraPersistentData` (o equivalentes). Cross-verify cada componente añadido live presente en cada load path Type=N.
- **Anti-pattern**: uniformizar load path asumiendo simetría Type=0/Type=N sin verificar.

### 3. AssetRegistry ghost entries (UEFN Python editor pipeline, 3 instancias)

> **Boundary**: aplica a scripts Python UEFN editor (pipelines exampleassets, VFS mount). Si task es pure UE Editor Python (no UEFN), usar también `coherence-auditor-unreal` skill — patterns paralelos pero scope distinto.

- **Pattern**: `asset_exists=True` + `load_asset=None`. Origen: `save_asset` silent-drop ante texture params no resueltos. Registry entry sobrevive sin .uasset disk file.
- **Detection**: `os.path.isfile(<disk_root>/<folder>/<asset>.uasset)` ANTES de confiar en `asset_exists`. Per-folder rescan `scan_paths_synchronous([f"{VFS_ROOT}/<subfolder>"], force_rescan=True)` obligatorio post-filesystem-copy externo.
- **Meta-pattern transversal**: APIs `EditorAssetLibrary` state-aware (delete_asset, save_asset, load_asset, does_asset_exist) retornan silently False/None ante state stale SIN propagar excepción.

### 4. Build staleness Verse

- **Pattern CRITICAL**: editar código ≠ fix deployed. ARs mismo día tocando mismo método/área → sospechar staleness antes de tratar como bug nuevo.
- **Detection**: verify Push Changes UEFN ejecutado + build version in-game match con código editado.
- **Anti-pattern**: tratar bug residual como independent root cause sin verify deploy previo.

## Métricas runtime esperadas

- **Persistence size**: <128KB per weak_map (4 weak_maps × 128KB max por isla, inviolable R1).
- **`save_asset` retorna True** pero disk file ausente = ghost. NO confiar retorno booleano.
- **Spawn timing post-restart**: verificar component rehydration completa antes de consumer (`GetComponent[placed_component]` failable post-load).
- **Float precision**: `N*VoxelSize - 1.3e-4` post-`UnrotateVector` cae 1 bucket en `Quotient`. Visible solo celdas borde grid.

## Distinguir evidencia DINÁMICA vs ESTÁTICA

- **Evidencia DINÁMICA** (state/timing/race condition): requiere probe runtime con identity. Anti-loop regla #2 aplica.
- **Evidencia ESTÁTICA** (code presence/absence verificable leyendo source): probe runtime redundante, fix directo legítimo (excepción anti-loop regla #2). Justificar explícitamente en hypothesis tracking. Pattern validado AR_2026-05-17 upgrade-items (líneas declaran items 49-50 + líneas registran UIDs 63-80 sin incluirlos → fix directo sin probe).

## Checklists audit

### Pre-audit

- [ ] Read AR target final_report.md + hypotheses.md.
- [ ] Read KB Verse-UEFN MEMORY.md (patterns + gotchas).
- [ ] Identificar tipo de divergence (runtime vs static, dynamic vs structural).

### Audit emitido

- [ ] Evidence enumerated con source citado (file:line, probe log, runtime metric).
- [ ] Cross-source-of-truth check explícito (state vs UI, Type=N vs Type=0, registry vs disk).
- [ ] Distinguish DINÁMICA vs ESTÁTICA en evidence classification.
- [ ] Anti-pattern declarado si encontrado (build staleness, ghost, divergence).

## Paths canónicos

- KB Tier 1: `{{paths.knowledge_base}}/verse-uefn/`.
- Project: `{{paths.uefn_projects_root}}`.
- AR investigado: `{{paths.docs.agent_runs}}/AR_<id>/`.

## Anti-patterns audit

- Declarar coherente basado en HUD success sin verify functional post-reload.
- Asumir Type=N parity con Type=0 sin grep cross-verify.
- Confiar `asset_exists` UEFN Python sin `os.path.isfile` disk verify.
- Mezclar evidencia DINÁMICA y ESTÁTICA sin distinguir (rompe anti-loop policy).
