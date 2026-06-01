---
name: coherence-auditor-blender
description: Skill para coherence-auditor cuando AR target es pipeline Blender Python (bpy, depsgraph, evaluated mesh, glTF export, atlas, Cycles bake, action.slots, process_blend, .blend, .glb). Detect source-of-truth divergence Blender 5.1.2.
---

# coherence-auditor-blender

## Cuándo cargar

Auto-match cuando audit toca código Blender (`bpy`, `bmesh`, `process_blend.py`, atlas/bake/paint utils). Skill complementa coherence-auditor base con source-of-truth divergences específicas Blender 5.1.2.

## Source-of-truth divergences típicas Blender

### 1. `obj.data` raw vs evaluated mesh

| Source | Contenido | Cuándo usar |
|---|---|---|
| `obj.data` | Mesh raw pre-modifiers | Edit operations (bmesh) |
| `obj.evaluated_get(depsgraph).data` | Final geometry post-modifiers | Export, bake, analysis |

**Divergence flag**: análisis estructural usando `obj.data` cuando modifiers presentes → resultados estadísticos incorrectos. Verify `obj.modifiers` empty O usar evaluated.

### 2. Depsgraph state vs viewport

- `bpy.context.evaluated_depsgraph_get()` snapshot — invalidated tras mutation.
- Tras `bpy.data.*` mutation → `depsgraph.update()` ANTES de re-query.
- **Flag**: code que muta data y re-queries evaluated sin `update()` intermedio → stale snapshot.

### 3. Modifier stack vs final geometry

- `obj.modifiers[*]` list ordenada.
- Final geometry = aplicar stack en order sobre `obj.data`.
- **Divergence**: skinning, displacement, subdivision modifiers cambian vertex count/positions. Análisis vertex count en raw mesh ≠ exported mesh.

### 4. Viewport preview vs Cycles render/bake

- Viewport material preview (EEVEE) ≠ Cycles render result.
- **Bake output**: solo refleja ACTIVE material slot per mesh per call [Blender 5.1.2].
- **Flag**: dev valida visualmente viewport → asume bake/export coherent → multi-slot mesh bake = patchwork.

### 5. Image data presence

| Estado | Indicador | Implicación |
|---|---|---|
| Loaded | `image.has_data == True` | `pixels[:]` populated |
| Reference broken | `image.has_data == False`, `filepath` set | File no encontrado o no loaded |
| Generated | `image.has_data == True`, `filepath == ''` | In-memory only |

**Divergence**: Cycles bake init compila TODO material set scene-wide. Broken Image Texture nodes (`image.has_data=False`) → compile fail global ALL slots. `neutralize_broken_image_nodes()` pre-bake mandatory.

### 6. Action API divergence [Blender 5.1.2]

- `action.fcurves` **DEPRECATED** [Blender 5.1.2] — AttributeError runtime.
- `action.slots → layers → strips → channelbag(slot).fcurves` **NEW canonical**.
- **Divergence flag**: docs/scripts pre-5.1 usando `action.fcurves`. Re-validar code base post-upgrade Blender 5.1.x.

### 7. Y-axis convention paste vs UV remap

- Paste TOP-DOWN: `(rows-1-row) * cell_h`.
- UV BOTTOM-UP: `(row+v) / grid_size` (Blender bottom-left origin).
- **Divergence**: mismatch entre paste y UV = magenta visual fail (`lostralaleritos_v5d` AR_2026-05-26 confirmed).

### 8. MESH-bound vs OBJECT-bound actions

- MESH-bound actions con keyframes (incluso single frame 0) = **structural offset duplicates** en glTF export [Blender 5.1.2].
- OBJECT-bound = transform animation legitimate.
- **Divergence**: pipeline filter solo single-keyframe MESH-bound → multi-keyframe estructural se cuela. Drop ALL MESH-bound pre-export.

## Métricas esperadas verificación

Per-file orchestrator log:

- **fly exampleasset detected** (si applicable) — name match `FLY_EXAMPLEASSETS` frozenset.
- **delta_z applied** — offset value logged.
- **MESH-bound actions dropped** count.
- **slots_baked** count post-bake (0 = compile fail → broken refs).
- **atlas paint completed** time (2-13s típico).

GLB output:

- Size correlation texture format: uint8 BaseColor → ~7% reduction vs float32.
- Embedded textures count == material slots count expected.
- glTF validation pass (`gltf-validator` standalone tool si disponible).

## Coherence checks per-file

1. **`obj.modifiers` vs export**: si modifiers presentes → export usa evaluated; sin `depsgraph.update()` post-mutation = stale.
2. **`bpy.data.actions[name].slots` API path**: code usando `action.fcurves` → flag DEPRECATED [Blender 5.1.2].
3. **Image data presence pre-bake**: iterate scene materials, check `node.image.has_data` per TEX_IMAGE node. Broken → neutralize required.
4. **Atlas Y-coord coherence**: paste fn + UV remap fn deben usar mismo Y origin (bottom-up OR top-down consistente).
5. **glTF export filter coherence**: scene actions vs exported animations count match expected.

## Anti-patterns coherence

- Análisis estadístico vertex count usando `obj.data` con modifiers presentes → flag SEVERITY HIGH.
- Cycles bake metric `slots_baked > 0` reportado sin verify visual (patchwork posible aún post-bake).
- Filter MESH-bound actions solo single-keyframe → multi-kf estructural se cuela.
- Manual list `FLY_EXAMPLEASSETS = frozenset({...})` desactualizada vs scene actual content → false negatives/positives. Verify list vs <user> ground truth periódicamente.

## Divergence severity

| Type | Severity | Action |
|---|---|---|
| `action.fcurves` API DEPRECATED | CRITICAL | refactor mandatory |
| Stale evaluated mesh post-mutation | HIGH | inject `depsgraph.update()` |
| `obj.data` raw análisis con modifiers | HIGH | switch a evaluated |
| Y-axis paste/UV mismatch | HIGH | fix convention coherent |
| Broken Image Texture nodes pre-bake | HIGH | neutralize call mandatory |
| Filter solo single-kf MESH-bound | HIGH | drop ALL MESH-bound |
| Manual list desactualizada | MEDIUM | re-validate vs scene |
| EEVEE preview ≠ Cycles bake assumption | MEDIUM | flag verify pipeline |
