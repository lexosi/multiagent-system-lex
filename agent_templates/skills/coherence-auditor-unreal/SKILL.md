---
name: coherence-auditor-unreal
description: Auditoría coherencia source-of-truth UE 5.4 Editor Python — divergence patterns AssetRegistry vs disk, in-memory vs saved, redirector chains. Auto-match keywords AssetRegistry stale, ghost entries, in-memory edits, save_asset commit, redirector chain, source-of-truth divergence UE Editor, EAL.does_asset_exist vs disk. NO UEFN runtime.
---

# coherence-auditor-unreal

## Scope

Detectar divergence source-of-truth entre las 4 capas estado UE 5.4 Editor Python:

1. **Disk filesystem** (`*.uasset` en NTFS)
2. **AssetRegistry in-memory** (índice rápido)
3. **In-memory edited assets** (post `load_asset` sin `save_asset`)
4. **Redirector chain** (post `rename_asset` auto refs)

Anti-loop brief §2.3 regla 4: divergence check ANTES de declarar bug de lógica.

## Divergence patterns documented [UE 5.4]

### D1: Ghost AssetRegistry entry

`EAL.does_asset_exist(path) == True` pero `os.path.isfile(disk_path) == False`.

**Trigger típicos**:
- Asset deleted externally vía filesystem sin AssetRegistry rescan
- Plugin reload mid-session
- Cleanup loop parcial post-rename

**Probe**:
```python
# [UE 5.4] TODO verify empirical (smoke: 3-line Editor Python script)
# Package path /Game/X/Foo → Object path /Game/X/Foo.Foo
def _package_to_object_path(pkg: str) -> str:
    return f"{pkg}.{pkg.rsplit('/', 1)[-1]}"

exists_registry = EAL.does_asset_exist(path)
disk = _package_to_object_path(path)
exists_disk = os.path.isfile(disk)
if exists_registry != exists_disk:
    # DIVERGENCE confirmed
    AR.scan_paths_synchronous([parent], force_rescan=True)
```

### D2: In-memory edit perdido

`EAL.load_asset(path) → set_*` cambios visibles en mismo script run, pero `EAL.save_asset(path)` retorna True silent sin commit a disk.

**Trigger típicos**:
- MaterialInstance texture parameter set a None ref [UE 5.4] silent-drop
- Asset reload mid-script (GC collect) pierde referencia Python
- Plugin reload entre set y save

**Probe**:
```python
EAL.save_asset(path)
# TODO [UE 5.4] verify: delay() en Editor Python context (no gameplay tick) — alternativa: time.sleep() O AssetRegistry.wait_for_completion()
unreal.SystemLibrary.delay(0.5)  # async commit window
disk = _package_to_object_path(path)  # helper definido D1
mtime_after = os.path.getmtime(disk)
if mtime_after <= mtime_before:
    # Save silent-dropped
```

### D3: Redirector chain stale references

`EAL.rename_asset(A, B)` crea redirector A → B. Refs en otros assets propagan auto. PERO scripts iterando lista paths pre-rename ven A obsoleto.

**Trigger típicos**:
- Cleanup loop usando lista snapshot pre-rename
- AssetRegistry cache stale post-rename (per-folder rescan needed)
- Cross-references desde Blueprint no rescan auto

**Probe**:
```python
# Pre-rename snapshot
paths_before = AR.get_assets_by_path("/Game/X", recursive=True)
EAL.rename_asset(old, new)
# CRITICAL: refresh snapshot
AR.scan_paths_synchronous(["/Game/X"], force_rescan=True)
paths_after = AR.get_assets_by_path("/Game/X", recursive=True)
# Comparar set diff
```

### D4: Per-folder rescan needed (root path insufficient)

`AR.scan_paths_synchronous(["/Game"], force_rescan=True)` NO descubre subfolders externally-copied `[UE 5.4]` (2ª instancia meta-pattern).

**Probe**:
```python
# Externally copied uassets en /Game/ExampleAssets/NewBatch/
AR.scan_paths_synchronous(["/Game"], force_rescan=True)
exists_root_scan = EAL.does_asset_exist("/Game/ExampleAssets/NewBatch/Asset1")
# Likely False

AR.scan_paths_synchronous(["/Game/ExampleAssets/NewBatch"], force_rescan=True)
exists_per_folder = EAL.does_asset_exist("/Game/ExampleAssets/NewBatch/Asset1")
# True
```

### D5: Texture2D collision masquerading as missing SK

`EAL.rename_asset(sk_temp_path, canonical_sk_pkg)` falla. Surface error: "rename failed". Root cause: `canonical_sk_pkg` ocupado por Texture2D del mismo glTF import `[UE 5.4]` (3ª instancia).

**Probe**:
```python
if EAL.does_asset_exist(canonical_sk_pkg):
    existing = EAL.load_asset(canonical_sk_pkg)
    type_name = type(existing).__name__
    # SkeletalMesh → real collision con SK previo
    # Texture2D → defensive rename pattern needed (gotcha G1 implementer)
    # Otro → investigar
```

## Métricas coherencia esperadas

| Métrica | Validación |
|---|---|
| Asset persistido real | `EAL.does_asset_exist(path) == True` **AND** `os.path.isfile(disk_path) == True` |
| Save committed | `mtime` post-save > `mtime` pre-save |
| Rename propagated | Snapshot AR post-rescan refleja new_path, old_path solo como redirector |
| Externally-copied discoverable | Per-folder `scan_paths_synchronous(force_rescan=True)` previo a `load_asset` |
| Texture2D collision diagnosed | `isinstance(existing, unreal.Texture2D)` retorna True para canonical SK path ocupado |

## Workflow audit

1. Read diff implementer
2. Identify operations sobre AssetRegistry/disk/in-memory (rename, save, delete, load, scan)
3. Para cada operation, check si pattern D1-D5 aplica
4. Si match → reportar divergence risk + probe sugerido a `hypothesis-reasoning` y `reviewer`
5. Tag `[UE 5.4]` cada divergence pattern referenciado

## Anti-patterns audit

- Aceptar "asset exists" como prueba single-source-of-truth (4 capas pueden divergir)
- Probe basado solo en `EAL.does_asset_exist` (ghost entries posibles)
- Comparación snapshots paths sin rescan intermedio post-mutación
- Asumir redirectors propagan auto a TODOS los consumers (Blueprint refs pueden necesitar refresh manual)

## Cross-references

- `implementer-unreal/SKILL.md` G1-G4 gotchas con código defensive
- `hypothesis-reasoning-unreal/SKILL.md` bug class taxonomy (GC collect, async load race, redirector loop)
- `<knowledge_root>\unreal-python-editor\MEMORY.md` entries [UE 5.4]
