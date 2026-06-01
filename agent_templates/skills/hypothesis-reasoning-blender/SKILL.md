---
name: hypothesis-reasoning-blender
description: Skill para hypothesis-reasoning cuando AR target es bug pipeline Blender Python (bpy, bmesh, depsgraph, Cycles bake, atlas, glTF export, action.slots, --background --python, .blend, .glb). Bug class taxonomy + probe patterns Blender 5.1.2.
---

# hypothesis-reasoning-blender

## Cuándo cargar

Auto-match cuando bug-fix AR menciona pipeline Blender (`bpy`, `bmesh`, `process_blend`, `--background --python`, atlas, bake, glTF export, action filter, .blend, .glb). Skill complementa hypothesis-reasoning base con bug class taxonomy Blender 5.1.2.

## Bug class taxonomy

### Class A: Context override missing

- **Síntoma**: `bpy.ops.*` invocado background mode lanza `RuntimeError: Operator bpy.ops.X.poll() failed, context is incorrect`.
- **Hipótesis**: script asume context default (GUI mode) que no existe headless.
- **Probe**: dump `bpy.context.area`, `bpy.context.window`, `bpy.context.region` pre-op call.
- **Fix**: wrap con `bpy.context.temp_override(window=..., area=..., region=...)` matching op signature.

### Class B: GUI-only op headless crash

- **Síntoma**: Blender process crash sin stacktrace clean en `--background --python`.
- **Hipótesis**: script invoca op GUI-only (`bpy.ops.wm.window_close`, `bpy.ops.render.opengl`, `bpy.ops.screen.*`).
- **Probe**: grep ops invocadas vs whitelist headless-safe.
- **Fix**: replace con `bpy.data.*` equivalent O remove call (op no aplicable headless).

### Class C: Depsgraph stale state

- **Síntoma**: análisis/export refleja state pre-mutation; vertex count incorrecto; modifier output ignorado.
- **Hipótesis**: code muta data y re-queries evaluated sin `depsgraph.update()` intermedio.
- **Probe**: inspect `bpy.context.evaluated_depsgraph_get().updates` post-mutation → empty si update faltante.
- **Fix**: inject `bpy.context.evaluated_depsgraph_get().update()` antes de re-query.

### Class D: Normals/orientation flipped

- **Síntoma**: mesh exported renderea inside-out, lighting incorrecto.
- **Hipótesis**:
  - Y-axis convention mismatch (paste vs UV remap) → magenta atlas.
  - Mesh imported sin `export_yup=True` apply.
  - bmesh edits sin `bmesh.ops.recalc_face_normals()` post-mutation.
- **Probe**: dump `face.normal` sample; export con/sin `export_yup`; render preview comparison.

### Class E: glTF export material loss / patchwork

- **Síntoma**: GLB renderea con textures missing, magenta, o patchwork visual multi-slot.
- **Hipótesis**:
  - Broken Image Texture nodes (`image.has_data=False`) crash Cycles bake compile global.
  - Cycles bake solo ACTIVE slot per mesh → multi-slot bake incompleto.
  - Atlas paint pure-math no finalized antes de export (UV remap missing).
- **Probe**: iterate scene materials, dump `node.image.has_data` per TEX_IMAGE. Count `slots_baked` post-bake.
- **Fix**: `neutralize_broken_image_nodes()` pre-bake O class-jump a atlas paint pure-math (entry AR_2026-05-26 multitex-atlas).

### Class F: Action API DEPRECATED [Blender 5.1.2]

- **Síntoma**: `AttributeError: 'Action' object has no attribute 'fcurves'` runtime.
- **Hipótesis**: code accede `action.fcurves` directo — DEPRECATED [Blender 5.1.2].
- **Probe**: `inspect_*.py` script standalone — dump `dir(action)`, iterate `action.slots → layers → strips → channelbag(slot).fcurves`.
- **Fix**: refactor a NEW API path. Pattern confirmed AR_2026-05-26_blender-mesh-bound-structural-actions.

### Class G: MESH-bound action structural duplicates

- **Síntoma**: glTF export tiene vertex offset duplicates, animation playback shows phantom geometry.
- **Hipótesis**: MESH-bound actions con keyframes (single O multi) generan structural offset duplicates en export [Blender 5.1.2].
- **Probe**: `inspect_mesh_bound_actions.py` standalone CSV — dump action_name + slot.target_id_type + keyframe count per mesh.
- **Fix**: drop **ALL** MESH-bound actions pre-export (`filter_animations_v4` pattern). NO solo single-keyframe.

### Class H: Single offset constant insuficiente batch heterogéneo

- **Síntoma**: subset modelos OK con constant, otros below ground / floating / clipping.
- **Hipótesis**: batch tiene geometry heterogénea (bbox Z varying) → constant única no converge.
- **Probe**: dump `obj.dimensions.z` + bbox per modelo CSV; compare delta needed per modelo.
- **Fix**: override CSV/dict per-name. Pattern AR_2026-05-26 fly exampleassets (defer manual confirmed <user>).

### Class I: Auto-detection heurística falsable batch pequeño

- **Síntoma**: heurística marca false-positive/negative en subset enumerable.
- **Hipótesis**: discriminación binaria de subset `<10` modelos verbatim <user> disponible — heurística overhead innecesario.
- **Fix**: replace con `frozenset({...})` manual list ground truth verbatim. Speedup ~12-15× (AR_2026-05-26).

## Probe patterns

### Standalone inspect script

```python
# inspect_X.py — run via blender --background <file>.blend --python inspect_X.py
import bpy, csv

rows = []
for obj in bpy.data.objects:
    rows.append({
        "name": obj.name,
        "type": obj.type,
        "modifiers_count": len(obj.modifiers),
        "bbox_z_min": min(v[2] for v in obj.bound_box),
        "bbox_z_max": max(v[2] for v in obj.bound_box),
    })

with open("/path/inspect_output.csv", "w", newline='') as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
```

CSV output evidencia estática — analizable post-run sin re-invoke Blender.

### Pre/post-fix diff probe

- Pre-fix: run pipeline, dump CSV state (`vertex_count`, `material_slots`, `actions_count`).
- Apply fix.
- Post-fix: run pipeline same input, dump same CSV.
- Diff → evidence fix applied + side-effects.

## Anti-loop (brief §2.3)

- **Max 3 attempts por hipótesis**. 4º → class-jump obligatorio.
- **Probe antes de fix**. Hipótesis sin probe confirmatorio = RECHAZADA.
- **Class-jump válido pattern Cycles bake**: 2 attempts FAIL multi-slot → swap a paint pure-math (AR_2026-05-26 multitex-atlas precedent).
- **Observación <user> > hipótesis agente**. Si <user> reporta visual fail con probe empírico → falsifica hipótesis agente, re-plan.

## Source-of-truth checks pre-hipótesis

1. **`obj.data` vs evaluated mesh** — análisis usando wrong source?
2. **Cycles bake slots_baked count** — 0 = compile fail global, NO error message claro.
3. **Image data `has_data`** — broken refs scene-wide?
4. **Action API path** [Blender 5.1.2] — `fcurves` vs `slots+layers+strips+channelbag`?
5. **Depsgraph updates queue post-mutation** — empty if `update()` missing?

## Evidencia mínima hipótesis CONFIRMED

- CSV probe output con expected vs observed.
- Pre/post-fix diff measurable.
- TEST-GATE <user> visual PASS (GLB viewer O in-engine preview).
