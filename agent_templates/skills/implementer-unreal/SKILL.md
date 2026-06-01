---
name: implementer-unreal
description: Implementación UE 5.4 Editor Python — APIs unreal.EditorAssetLibrary, unreal.AssetTools, unreal.MaterialEditingLibrary, unreal.AssetRegistry, factories. Auto-match keywords EAL.rename_asset, EAL.delete_asset, save_asset, scan_paths_synchronous, create_asset, set_material_instance_texture_parameter_value, GLTFImportFactory, redirector, Texture2D collision, AssetRegistry stale. NO UEFN runtime.
---

# implementer-unreal

## Scope

Aplicar cambios concretos código Python UE 5.4 Editor (typical: `<Project>/Content/Code/*.py`). NUNCA tocar UEFN runtime side desde este skill — son APIs distintas.

## APIs concretas [UE 5.4]

### unreal.EditorAssetLibrary (alias EAL)

```python
import unreal
EAL = unreal.EditorAssetLibrary
```

| Método | Signature | Gotcha |
|---|---|---|
| `EAL.rename_asset(old_path, new_path)` | `(str, str) -> bool` | Crea redirector auto + propaga refs. Falla por **Texture2D collision en ruta destino SK canónica** (3ª instancia meta-pattern) |
| `EAL.delete_asset(path)` | `(str) -> bool` | Retorna **False silent sobre path stale post-rename** (2ª instancia AR inconsistencies). EXCLUIR `old_path` de cleanup loop post-`rename_asset` |
| `EAL.save_asset(path)` | `(str) -> bool` | **Silent-drop si MaterialInstance texture params None refs** (1ª instancia). Verify `os.path.isfile(disk_path)` post-save |
| `EAL.does_asset_exist(path)` | `(str) -> bool` | Consulta AssetRegistry in-memory — puede divergir de disk (ghost entries) |
| `EAL.load_asset(path)` | `(str) -> Object` | Mutaciones in-memory hasta `save_asset` |

### unreal.AssetRegistry

```python
AR = unreal.AssetRegistryHelpers.get_asset_registry()
AR.scan_paths_synchronous(["/Game/ExampleAssets"], force_rescan=True)
```

Gotcha [UE 5.4]: **root path rescan NO descubre subfolders externally-copied uassets** (2ª instancia). Per-folder rescan explícito antes de `load_asset` sobre assets copiados via filesystem.

### unreal.AssetTools

```python
AT = unreal.AssetToolsHelpers.get_asset_tools()
new_asset = AT.create_asset(name, package_path, asset_class, factory)
```

### unreal.MaterialEditingLibrary

```python
MEL = unreal.MaterialEditingLibrary
MEL.set_material_instance_texture_parameter_value(mi, param_name, texture)
```

Save MI post-set obligatorio o cambios no persisten.

### Factories import

- `unreal.GLTFImportFactory` — GLB/GLTF batch
- `unreal.FbxFactory` — FBX
- `unreal.TextureFactory` — texturas standalone

## Gotchas críticos [UE 5.4]

### G1: Texture2D collision post-glTF en ruta SK canónica

`GLTFImportFactory` puede crear Texture2D con nombre = `{name}` (mismo que SK destinada). Antes `EAL.rename_asset(sk_path, canonical_sk_pkg)`:

```python
if EAL.does_asset_exist(canonical_sk_pkg):
    existing = EAL.load_asset(canonical_sk_pkg)
    if isinstance(existing, unreal.Texture2D):
        # Rename Texture2D → liberar ruta para SK
        EAL.rename_asset(canonical_sk_pkg, f"{canonical_sk_pkg}_texture")
        # Actualizar lista cleanup
    elif isinstance(existing, unreal.SkeletalMesh):
        # Purge seguro o skip
        EAL.delete_asset(canonical_sk_pkg)
```

Sin `isinstance` check → rename falla colisión silent.

### G2: Threshold multi-tex SKIP tunable

V5 Blender atlas produce Viewer Node + `.001/.002` duplicate refs. `len(Texture2D) > 1` frágil → 7/9 false-positive SKIP empirical. Threshold realista `> 4` para pipeline V5. Alternativa robusta: helper `_count_unique_diffuse_textures(materials)`.

### G3: Defensive pre-check disk file presence

```python
import os

# [UE 5.4] TODO verify empirical (smoke: 3-line Editor Python script)
# Package path /Game/X/Foo → Object path /Game/X/Foo.Foo
def _package_to_object_path(pkg: str) -> str:
    return f"{pkg}.{pkg.rsplit('/', 1)[-1]}"

if EAL.does_asset_exist(asset_path):
    disk_path = _package_to_object_path(asset_path)
    # Convert /Game/X/Y → <Project>/Content/X/Y.uasset
    if not os.path.isfile(disk_path):
        # Ghost AssetRegistry entry — force rescan
        AR.scan_paths_synchronous([parent_folder], force_rescan=True)
```

### G4: Cleanup loop post-rename

```python
to_cleanup = [...]
for old_path in renamed_assets:
    new_path = rename_map[old_path]
    EAL.rename_asset(old_path, new_path)
    # CRITICAL: excluir old_path del cleanup (devuelve False silent)
    if old_path in to_cleanup:
        to_cleanup.remove(old_path)

for stale_path in to_cleanup:
    EAL.delete_asset(stale_path)
```

## Workflow ONE-FILE-PER-TURN

Brief §4.4 atomic = 1 file/step. Aplica igual UE Editor Python:

1. Read file target ENTERO antes editar
2. Edit min necesario (NO refactor vecino)
3. Side-effect scan: `grep` refs símbolo modificado en `Content/Code/*.py`
4. Bug colateral → TD ticket separado, NO mismo commit
5. Diff summary a root con tag `[UE 5.4]` en cada gotcha relevante

## Anti-patterns

- Confiar return `save_asset()` True sin verify disk file presence
- `EAL.rename_asset` sin `isinstance` Texture2D defensive
- `EAL.delete_asset(old_path)` dentro mismo loop que renombró old_path
- Root path `scan_paths_synchronous` cuando target = subfolder externally-copied
- Mezclar APIs UEFN runtime (`fortnite_ue`) con Editor Python (`unreal.*`)

## Archivos protegidos

- `<Project>/Content/Code/*.py` ASK <user> antes editar (proyectos UE 5.4 <user> en `<unreal_projects_root>\*` y `<uefn_root>\*`)
- NO usar git para `<uefn_root>\*` (save = Push Changes Editor interno UEFN); `<unreal_projects_root>` también workflow Editor-driven
