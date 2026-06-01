---
name: planner-unreal
description: Planificación implementaciones UE 5.4 Editor Python (unreal.EditorAssetLibrary, unreal.AssetTools, AssetRegistry, MaterialEditingLibrary). Auto-match keywords UE Editor Python, EAL, AssetRegistry, MaterialEditingLibrary, AssetTools, import batch GLB/GLTF, rename_asset, redirector propagation, plugins Content/Code Python. NO UEFN runtime (separate skill).
---

# planner-unreal

## Scope

Planificar features/fixes UE 5.4 Editor Python. NUNCA mezclar con UEFN runtime — son dominios separados (UEFN game-side Python tiene VFS distinto, allow-list filtering, restricciones SkeletalMesh, etc.).

## Convención versionado [OBLIGATORIA]

Cada step KB-bound o gotcha referenciada en `plan.md` lleva tag UE version:

| Tag | Uso |
|---|---|
| `[UE 5.4]` | Validado solo 5.4 (default actual Lexosi) |
| `[UE 5.4-5.6]` | Validado rango |
| `[UE ≥5.7]` | Disponible 5.7+ |
| `[UE all]` | Estable cross-version (rare, justificar) |
| `[UE ?]` | No verificado (flag future validation) |

Constraint actual: Lexosi UE 5.4. NO planear features dependientes de APIs `[UE ≥5.7]` sin probe explícito previo.

## Arquitectura Editor Python

### Layout proyectos UE Editor

```
<Project>/
├── Content/
│   ├── Code/                  ← scripts Python `*.py` (NO compilable; runtime Editor)
│   │   ├── 01_import_exampleassets.py
│   │   ├── 02_batch_exampleassets.py
│   │   └── shared/
│   ├── ExampleAssets/            ← assets imported `/Game/ExampleAssets/`
│   └── Materials/
└── <Project>.uproject
```

VFS mount: `/Game/` ↔ `<Project>/Content/`. Disk path: `<Project>/Content/<sub>/Asset.uasset`. AssetRegistry expone ambos a Python via `unreal.EditorAssetLibrary` (alias EAL).

### Capas estado (CRÍTICO planning)

1. **Disk filesystem** (`*.uasset` en NTFS)
2. **AssetRegistry in-memory** (índice rápido, puede divergir de disk)
3. **In-memory edited assets** (load_asset → set_* sin save_asset → cambios pendientes)
4. **Redirector chain** (post-rename auto refs)

Planear pasos que mantengan estas 4 capas consistentes. Divergence patterns documented en `coherence-auditor-unreal`.

## Workflow típico

### Pipeline import batch GLB/GLTF (canonical)

1. Discover GLBs source folder
2. `unreal.AssetTools.import_assets_automated(import_data)` con `unreal.GLTFImportFactory`
3. Post-import: detect Texture2D collision en ruta SK canónica `[UE 5.4]` (gotcha confirmada 3 instancias)
4. Defensive rename Texture2D `{name}` → `{name}_texture` si colisiona con SK destinada
5. `EAL.rename_asset(temp_path, canonical_pkg)` (auto-propaga redirectors)
6. MaterialInstance create + `MaterialEditingLibrary.set_material_instance_texture_parameter_value(...)`
7. `EAL.save_asset(canonical_pkg)` + verify `os.path.isfile(disk_path)` post-save
8. `AssetRegistry.scan_paths_synchronous([folder], force_rescan=True)` per-folder (no root)

### Pipeline rename + cleanup

1. Trackear `old_path` pre-rename en lista cleanup
2. `EAL.rename_asset(old, new)` (redirector creado auto)
3. **EXCLUIR `old_path` de cleanup loop** (`EAL.delete_asset(old_path)` retorna False silent post-rename)
4. Cleanup `/Game/<temp_folder>/` resto

## Constraints planning

- **STOP-GATE per-step Lexosi**: feature multi-step UE Editor batched LOW+MED, HIGH solo (Cap N4)
- **TEST-GATE manual UEFN/UE Editor**: post-implementer + pre-doc-writer. NO automatizable Editor Python (Editor abierto manual)
- **Investigación grep REAL vs COSMETIC** `[UE 5.4]`: whitelist baseline (Material compile transient, `Cube_*_root` delete false) + grep separated FAIL log → Lexosi decide scope
- **NO planear EAL.rename_asset sin defensive Texture2D collision check** `[UE 5.4]` (CRITICAL 3ª instancia meta-pattern AssetRegistry inconsistencies)

## Anti-patterns planning

- Asumir `EAL.does_asset_exist(path)` == disk file present (ghost AssetRegistry entries posibles)
- Planear root path `scan_paths_synchronous` cuando subfolders externally-copied (NO descubre, per-folder needed `[UE 5.4]`)
- Trust `save_asset()` return True sin verify disk file (silent-drop MaterialInstance None texture refs `[UE 5.4]`)
- Mezclar APIs UE Editor con UEFN runtime en mismo plan.md (split por dominio)

## Pending migration KB

Entries `verse-uefn/MEMORY.md` que son UE Editor (no UEFN-specific) pendientes migrar:
- MaterialEditingLibrary patterns
- AssetToolsHelpers
- EditorAssetSubsystem
- AssetRegistryHelpers

Mantener en `verse-uefn/` solo: VFS mount per-project UEFN, allow-list validation UEFN, M_BoneAnimation/M_BrainrotAnimation parents UEFN materials.
