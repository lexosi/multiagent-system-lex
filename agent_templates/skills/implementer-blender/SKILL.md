---
name: implementer-blender
description: Skill para implementer cuando AR target es código Blender Python (bpy.data, bpy.ops, bpy.context.temp_override, bmesh, --background --python, glTF export, atlas paint, Cycles bake, action.slots channelbag, process_blend, .blend, .glb). Density-max APIs concretas Blender 5.1.2.
---

# implementer-blender

## Cuándo cargar

Auto-match Edit/Write touching `.py` con imports `bpy`, `bmesh`, `mathutils`; scripts orchestrator `process_blend.py`; scripts standalone `inspect_*.py`, `paint_*.py`, `bake_*.py`; pipeline `<projects_root>\ExampleBlenderProject\ExampleAssetSet\`.

## APIs concretas [Blender 5.1.2]

### Context override background mode

`bpy.ops.*` necesita context válido. Background mode no tiene window default:

```python
# Pattern correcto
window = bpy.context.window_manager.windows[0]  # background mode: synth window OK
with bpy.context.temp_override(window=window, area=area, region=region):
    bpy.ops.object.bake(type='DIFFUSE')
```

Match `area.type` / `region.type` al op signature (VIEW_3D + WINDOW para mesh/object ops; IMAGE_EDITOR + WINDOW para image ops).

### bpy.data preferred (deterministic)

```python
# Mesh creation
mesh = bpy.data.meshes.new(name="atlas_mesh")
obj = bpy.data.objects.new(name, mesh)
bpy.context.collection.objects.link(obj)

# Image creation — uint8 RGBA reduce GLB ~7% para BaseColor
img = bpy.data.images.new(
    name="atlas",
    width=2048, height=2048,
    float_buffer=False,   # uint8 (4 B/px) — BaseColor OK
    alpha=True
)
# NO aplicar float_buffer=False a normal/roughness/metallic — mantener float32
```

### Action API [Blender 5.1.2] — NEW

**`action.fcurves` DEPRECATED** [Blender 5.1.2]. Usar:

```python
for slot in action.slots:
    for layer in slot.layers if hasattr(slot, 'layers') else action.layers:
        for strip in layer.strips:
            cbag = strip.channelbag(slot)
            if cbag is None:
                continue
            for fc in cbag.fcurves:
                # fc.data_path, fc.array_index, fc.keyframe_points
                ...
```

`action.slots → layers → strips → channelbag(slot).fcurves`. CRÍTICO en introspections / filter_animations.

### bmesh edit mode

```python
import bmesh
bm = bmesh.from_edit_mesh(obj.data)
# bm.verts, bm.edges, bm.faces — mutate
bmesh.update_edit_mesh(obj.data)
```

Más rápido + safer que `bpy.ops.mesh.*` para batch geometry edits.

### glTF export

```python
bpy.ops.export_scene.gltf(
    filepath="output.glb",
    export_format='GLB',
    use_selection=True,           # export selected only
    export_animations=True,
    export_yup=True,              # glTF convention
)
```

### Cycles bake (multi-pass workaround)

```python
# Pre-bake: neutralize broken Image Texture nodes scene-wide
def neutralize_broken_image_nodes():
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image is not None:
                if not node.image.has_data:
                    node.image = None  # detach → evita compile fail scene-wide
```

Cycles `bpy.ops.object.bake(type='DIFFUSE')` bakea **solo ACTIVE material slot per mesh**. Multi-slot requiere iterate set active + bake N times (frágil, broken refs crash).

### Atlas paint pure-math (preferido multi-slot)

```python
# Y-axis convention CRÍTICA [Blender 5.1.2] — post-fix AR_2026-05-26 atlas-bake
# Paste bottom-up: row * cell_h (matches Blender UV bottom-left origin)
# UV remap bottom-up: (row+v) / grid_size
# Mismatch paste/UV → magenta visual fail (NO usar paste TOP-DOWN sin invert UV también)
def paste_image_into_atlas_cell(atlas_pixels, src_pixels, row, col, cell_w, cell_h, grid_size):
    cell_y0 = row * cell_h  # bottom-up coherente con UV Blender bottom-left origin
    cell_x0 = col * cell_w
    # ... blit src_pixels into atlas_pixels[cell_y0:cell_y0+cell_h, cell_x0:cell_x0+cell_w]
```

Mismatch Y paste vs UV = magenta visual fail (confirmado AR_2026-05-26_blender-pipeline-multitex-atlas-bake).

### Depsgraph evaluated mesh

```python
depsgraph = bpy.context.evaluated_depsgraph_get()
eval_obj = obj.evaluated_get(depsgraph)
eval_mesh = eval_obj.data  # post-modifiers final geometry
# obj.data raw ≠ eval_mesh si modifiers presentes
```

## Gotchas implementación [Blender 5.1.2]

1. **Y-axis paste vs UV mismatch** = magenta. Remover Y invert en paste, mantener UV bottom-up.
2. **MESH-bound actions** con keyframes → drop ALL pre-export (`filter_animations_v4` pattern). Helper `_is_structural_single_kf` preservar dead-code para reference.
3. **`bpy.ops.wm.window_close`** background → crash. Banned headless.
4. **Cycles bake init** compila TODO material set scene-wide → broken Image Texture nodes crash global. `neutralize_broken_image_nodes()` pre-bake mandatory.
5. **Single offset constant insuficiente** voladores heterogéneos (bbox Z varying). Override CSV/dict per-name (`FLY_EXAMPLEASSETS_OVERRIDE = {"name": delta_z, ...}`).
6. **`action.fcurves` AttributeError** [Blender 5.1.2] → usar slots+layers+strips+channelbag.
7. **uint8 RGBA aplicado a normal/roughness/metallic** → precisión perdida visible. Solo BaseColor.

## Anti-patterns

- `bpy.ops.wm.window_close` headless → crash.
- Auto-detect heurística complex para batch `<10` modelos verbatim Lexosi disponible → manual `frozenset({...})` supera.
- `action.fcurves` directo → AttributeError [Blender 5.1.2].
- Cycles bake multi-slot sin neutralize → crash global o patchwork visual.
- Modificar `obj.data.vertices` sin `depsgraph.update()` antes de export → stale evaluated mesh.
- `bpy.context.scene.objects.active = obj` (DEPRECATED). Usar `bpy.context.view_layer.objects.active = obj`.
- Subprocess Python externo importando `bpy` → ImportError. `bpy` solo dentro runtime Blender (`--python script.py`).

## Side-effect scan checklist

Tras Edit/Write `process_blend.py` u otro script:

- `grep` refs a símbolo modificado (function name) — verificar callers.
- Si tocaste `filter_animations_*` → verify callers en pipeline pre-export.
- Si tocaste atlas paint/bake → verify UV remap coherence (Y-axis convention).
- Si bumpeaste constant (FLY_ELEVATION_Z, ATLAS_GRID_SIZE) → verify downstream usages.
