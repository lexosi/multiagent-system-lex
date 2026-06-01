---
name: reviewer-blender
description: Skill para reviewer cuando AR target es código Blender Python (bpy, bmesh, glTF export, atlas bake, --background --python, Cycles, action.slots, process_blend, .blend, .glb). Checklist Blender 5.1.2 headless safety + API correctness.
---

# reviewer-blender

## Cuándo cargar

Auto-match diff/PR review tocando `.py` con imports `bpy`, `bmesh`, scripts `process_blend.py`, `inspect_*.py`, atlas/bake/paint utils. Skill complementa reviewer base con domain Blender 5.1.2.

## Checklist review

### Versionado obligatorio

- [ ] Tag `[Blender x.y.z]` o `[Blender x.y+]` en cada comment KB-bound o docstring que cite API/comportamiento version-specific. Ausencia → flag MEDIUM.
- [ ] MEMORY.md / docs commits llevan tag explícito; NO mezclar major versions sin justificar.

### Headless safety

- [ ] **NO** `bpy.ops.wm.window_close` — crash background.
- [ ] **NO** `bpy.ops.render.opengl` — GUI-only.
- [ ] **NO** otros GUI ops (`bpy.ops.screen.*`, `bpy.ops.view3d.*` sin context override válido).
- [ ] Si `bpy.ops.*` invocado en script `--background --python` → verify `with bpy.context.temp_override(window=..., area=..., region=...)` matching op signature.
- [ ] `area.type` / `region.type` coherente con op (VIEW_3D+WINDOW para object/mesh ops; IMAGE_EDITOR+WINDOW para image ops).

### API preference

- [ ] `bpy.data.*` preferred sobre `bpy.ops.*` cuando equivalente disponible. Si `bpy.ops.*` usado, justification comment requerida.
- [ ] `bpy.context.view_layer.objects.active` (NUEVA) NO `bpy.context.scene.objects.active` (DEPRECATED).
- [ ] Action iter: `action.slots → layers → strips → channelbag(slot).fcurves` [Blender 5.1.2]. **Flag CRITICAL** si código accede `action.fcurves` directo → AttributeError runtime.

### Depsgraph / mesh state

- [ ] Tras data mutation, `depsgraph.update()` invoked antes de export/bake si modifiers presentes.
- [ ] `obj.evaluated_get(depsgraph).data` para final geometry post-modifiers; NO `obj.data` raw si modifiers en stack.

### Texture format

- [ ] BaseColor textures → `bpy.data.images.new(float_buffer=False)` uint8 RGBA OK (~7% size reduction GLB).
- [ ] **Flag HIGH** si `float_buffer=False` aplicado a normal/roughness/metallic → precisión perdida visible.

### Y-axis convention atlas

- [ ] Si script genera atlas multi-cell:
  - Pixel paste: TOP-DOWN `(rows-1-row)*cell_h` O bottom-up `row*cell_h` (uniforme con UV remap).
  - UV remap: BOTTOM-UP `(row+v)/grid_size` (Blender bottom-left origin).
  - **Mismatch paste/UV = magenta visual fail** (confirmado AR_2026-05-26).
- [ ] `_paste_image_into_atlas_cell` + `_fill_atlas_cell_solid` deben usar misma convention.

### Cycles bake multi-slot

- [ ] **Flag HIGH** si `bpy.ops.object.bake(type='DIFFUSE')` invocado en mesh multi-slot sin `neutralize_broken_image_nodes()` pre-bake → scene-wide crash si broken Image Texture refs.
- [ ] Multi-slot baking workflow complejo. Class-jump válido tras 2 attempts Cycles FAIL → atlas paint pure-math (Python pixel paste + UV remap deterministic).

### MESH-bound actions

- [ ] Pre-glTF export: filter actions, dropear ALL MESH-bound (no solo single-keyframe). Pattern `filter_animations_v4` [Blender 5.1.2].
- [ ] Multi-keyframe MESH-bound también estructural → drop incluida (H2 CONFIRMED AR_2026-05-26).

### Batch heterogéneo

- [ ] **Flag MEDIUM** si constante única (`OFFSET_Z`, `ELEVATION`) aplicada a batch heterogéneo geometry (bbox varying). Permitir override per-modelo (CSV/dict por name).
- [ ] Manual list hardcoded `frozenset({...})` preferred sobre auto-detection heurística para `<10` modelos verbatim <user> disponible.

### glTF export coherence

- [ ] `export_yup=True` (glTF convention).
- [ ] `export_animations=True` si scene tiene actions relevantes.
- [ ] Verify selected objects pre-export si `use_selection=True`.

## Severity levels Blender-specific

| Issue | Severity |
|---|---|
| `action.fcurves` directo [Blender 5.1.2] | CRITICAL — runtime AttributeError |
| `bpy.ops.wm.window_close` background | CRITICAL — crash |
| Cycles bake sin neutralize broken refs | HIGH — crash o patchwork |
| `float_buffer=False` aplicado normal/roughness | HIGH — precisión perdida |
| `bpy.ops.*` sin temp_override background | HIGH — crash |
| Y-axis paste/UV mismatch atlas | HIGH — magenta visual fail |
| Missing `depsgraph.update()` post-mutation | HIGH — stale eval mesh |
| Tag `[Blender x.y.z]` ausente comment KB-bound | MEDIUM |
| Constant única batch heterogéneo | MEDIUM |
| `bpy.ops.*` cuando `bpy.data` equivalente disponible | LOW — refactor |
| `bpy.context.scene.objects.active` (DEPRECATED) | LOW — refactor |

## Anti-patterns flag automatic

- `action.fcurves` regex match → CRITICAL.
- `bpy.ops.wm.window_close` regex → CRITICAL.
- `bpy.data.images.new(...float_buffer=False...)` con name matching `*normal*|*roughness*|*metallic*` → HIGH.
- Cycles `bake(...type=['DIFFUSE'|'COMBINED'])` precedido sin `neutralize_broken_image_nodes()` call en mismo file → HIGH.

## Aprobación criteria

- **Approve**: zero CRITICAL/HIGH, MEDIUM/LOW opcional.
- **Warning**: solo HIGH presentes — <user> decide merge.
- **Block**: CRITICAL presente — fix mandatory antes merge.
