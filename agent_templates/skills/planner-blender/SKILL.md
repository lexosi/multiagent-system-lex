---
name: planner-blender
description: Skill para planner cuando AR target es pipeline Blender Python (bpy, --background --python, bmesh, glTF export, atlas bake, process_blend orchestrator, .blend files, <projects_root>\ExampleBlenderProject). Carga conocimiento dominio para planning multi-step batch headless Blender 5.1.2.
---

# planner-blender

## Cuándo cargar

Auto-match si AR mencionan: `blender`, `bpy`, `bmesh`, `.blend`, `glTF`, `glb`, `atlas`, `bake`, `Cycles`, `process_blend`, `--background --python`, `<projects_root>\ExampleBlenderProject`, `ExampleAssetSet`, `armature`, `fcurves`, `material slot`, `UV remap`, `temp_override`.

## Arquitectura típica pipeline Blender

- **Workstation Lexosi**: Blender 5.1.2 Steam, path `F:\SteamLibrary\steamapps\common\Blender\blender.exe`. Working dir `<projects_root>\ExampleBlenderProject\ExampleAssetSet\`.
- **Orchestrator**: `process_blend.py` itera `.blend` files batch → invoca Blender headless per-file via subprocess → output `.glb` glTF embedded.
- **Invocation pattern** `[Blender 5.1.2]`:
  ```
  blender --background <input.blend> --python <script.py> -- <args>
  ```
  Subprocess from orchestrator Python. NO ejecutar `bpy` desde Python externo (debe ser dentro del runtime Blender).
- **Pipeline típico por file**: load .blend → mesh/UV/material operations → filter animations → atlas paint/bake (opcional) → glTF export → `.glb` output.

## Module decisión tree

| Caso | API preferida | Razón |
|---|---|---|
| Crear/modificar data (mesh, image, material) | `bpy.data.*` | Deterministic, no context dependency, safer headless |
| Operator sin equivalent data (bake, UV ops) | `bpy.ops.*` con `bpy.context.temp_override(...)` | `bpy.ops` requiere context válido; background mode no tiene window default |
| Edit mode geometry | `bmesh.from_edit_mesh()` + `bmesh.update_edit_mesh()` | Faster + safer que `bpy.ops.mesh.*` |

**Regla**: si `bpy.data` cubre el caso → usar `bpy.data`. Justificar en plan_step cuando `bpy.ops` necesario.

## Sprint/feature pattern Blender

1. **Plan steps numerados ONE-FILE-PER-TURN** (Cap N4 STOP-GATE per-step Lexosi entre steps).
2. **Probe-first para discovery** API change/divergence: script `inspect_*.py` standalone read-only que dumpea CSV evidencia estática (ej. `inspect_mesh_bound_actions.py` discovery `action.fcurves` deprecated [Blender 5.1.2]).
3. **Batch size matters**:
   - `<10` modelos enumerable → **manual list hardcoded** `FROZEN_SET = frozenset({"name1", ...})` con verbatim ground truth Lexosi. Speedup ~12-15× vs auto-detection heurística.
   - `≥10` con feature común → auto-detection heurística OK.
4. **Tag versionado `[Blender 5.1.2]` obligatorio** en cada plan_step que cite API/comportamiento version-specific.
5. **TEST-GATE Lexosi visual obligatorio** post-implementation (GLB viewer, in-engine UEFN/Unreal preview, o blender re-load). Compile success ≠ visual correct.

## Paths canónicos

- KB Blender-python: `{{paths.knowledge_base}}/blender-python/` (Tier 1 Read).
- MEMORY.md patterns: `{{paths.knowledge_base}}/blender-python/MEMORY.md`.
- Project target típico: `<projects_root>\ExampleBlenderProject\ExampleAssetSet\`.
- AR dir: `{{paths.docs.agent_runs}}/AR_<id>/`.
- `process_blend.py` orchestrator: ubicado en working dir Lexosi (NO en multiagent-system repo).

## Gotchas top-8 (planning-relevant)

1. **Headless safety**: NO planear `bpy.ops.wm.window_close`, `bpy.ops.render.opengl`, GUI-only ops → crash background mode.
2. **Context override mandatory** background: `bpy.ops.*` requiere `with bpy.context.temp_override(window=..., area=..., region=...)` matching op signature.
3. **Depsgraph update**: tras data mutation, `depsgraph.update()` o `obj.evaluated_get(depsgraph).data` para final geometry post-modifiers.
4. **Single offset constant insuficiente para batches heterogéneos** [Blender 5.1.2] (voladores bbox Z varying). Plan debe permitir override per-modelo (CSV/dict por name) si batch heterogéneo.
5. **MESH-bound actions** [Blender 5.1.2] = structural offset duplicates en glTF export. Plan obligatorio: drop ALL MESH-bound pre-export (`filter_animations_v4` pattern), NO solo single-keyframe.
6. **Cycles bake** [Blender 5.1.2] solo bakea ACTIVE material slot per mesh + compila scene-wide al init (broken Image Texture refs crash global). Plan multi-slot atlas → swap a **paint pure-math** (Python pixel paste + UV remap deterministic) tras 2 attempts Cycles FAIL = class-jump válido.
7. **Y-axis convention coherence** [Blender 5.1.2]: paste TOP `(rows-1-row)*cell_h`, UV BOTTOM `(row+v)/grid_size`. Mismatch = magenta visual fail.
8. **Texture format**: BaseColor → uint8 RGBA OK (~7% size reduction GLB embedded). Normal/roughness/metallic → float32 mandatory.

## Anti-patterns plan

- Plan que itera mesh edit con `bpy.ops.mesh.*` sin `temp_override` → background crash.
- Auto-detection heurística complex para batch `<10` que Lexosi puede aportar verbatim ground truth → manual list supera.
- Plan que asume `action.fcurves` API → DEPRECATED [Blender 5.1.2]. Usar `action.slots → layers → strips → channelbag(slot).fcurves`.
- Plan Cycles bake DIFFUSE multi-slot sin preneutralize broken Image Texture nodes → crash o patchwork.
- Aplicar uint8 RGBA a normal/roughness/metallic maps → pérdida precisión visible.
