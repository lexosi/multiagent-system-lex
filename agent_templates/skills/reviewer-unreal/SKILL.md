---
name: reviewer-unreal
description: Review diffs UE 5.4 Editor Python (unreal.EditorAssetLibrary, unreal.AssetTools, MaterialEditingLibrary). Auto-match keywords reviewer UE Editor, EAL diff, AssetRegistry validation, rename_asset review, redirector propagation review, Texture2D collision check, Material compile cosmetic, grep REAL vs COSMETIC. NO UEFN runtime review.
---

# reviewer-unreal

## Scope

Validar diffs UE 5.4 Editor Python producidos por `implementer-unreal`. Enforcement reglas anti-sycophancy + KB versionado tags.

## Checklist obligatorio

### Versionado tags

- [ ] Cada gotcha/entry KB-bound en diff lleva tag `[UE x.y]` o `[UE x.y-z]` o `[UE ≥x.y]`
- [ ] NO mezclar APIs UE 5.4 con UE ≥5.7 sin probe explícito documentado
- [ ] Constraint Lexosi current = UE 5.4 (no aceptar `[UE ≥5.7]`-only sin justificación)
- [ ] Comments código referenciando APIs version-specific incluyen tag inline

### Asset paths

- [ ] Formato canónico `/Game/<subfolder>/AssetName` (sin extensión `.uasset`)
- [ ] NO mezclar disk path NTFS (`C:\Users\...\Content\X\Y.uasset`) con VFS path (`/Game/X/Y`) sin conversion explícita
- [ ] Conversion `SystemLibrary.conv_package_to_object_path()` o equivalente cuando se cruza VFS↔disk

### EAL.rename_asset defensive pattern

- [ ] Branch `does_asset_exist(canonical_sk_pkg)=True` incluye `isinstance(existing, unreal.Texture2D)` check **antes** de rename/purge `[UE 5.4]`
- [ ] Si Texture2D collision → rename `{name}` → `{name}_texture` + actualizar lista index
- [ ] Si SkeletalMesh → purge seguro o skip
- [ ] Sin isinstance check → RECHAZAR diff (CRITICAL gotcha 3ª instancia AssetRegistry inconsistencies)

### Cleanup loop post-rename

- [ ] `old_path` excluido de `to_cleanup` list tras `EAL.rename_asset(old, new)` (+3 LOC defensive trackear)
- [ ] NO llamar `EAL.delete_asset(old_path)` mismo loop que renombró (silent False return `[UE 5.4]`)

### Save + verify

- [ ] `EAL.save_asset(path)` seguido por verify `os.path.isfile(disk_path)` cuando MaterialInstance/critical asset
- [ ] NO trust `save_asset()` return True solo (silent-drop MaterialInstance None texture refs `[UE 5.4]`)

### AssetRegistry rescan

- [ ] `scan_paths_synchronous` per-folder específico, NO root path `/Game/` si target = subfolder
- [ ] `force_rescan=True` cuando assets externally-copied via filesystem
- [ ] Rescan ANTES de `load_asset` sobre assets recién copiados

### Threshold multi-tex

- [ ] Si código heurística "multi-texture SKIP", threshold ≥ 4 (no `>1` frágil `[UE 5.4]`)
- [ ] Comment inline justificando threshold elegido (Blender V5 atlas Viewer Node + `.001/.002` artifacts)
- [ ] Alternativa preferida: helper `_count_unique_diffuse_textures(materials)`

### Investigación grep REAL vs COSMETIC

- [ ] Whitelist baseline documentada (Material compile transient warnings, `Cube_*_root` delete false)
- [ ] Grep FAIL separated log file
- [ ] Reporte tabular Lexosi (tipo / count / sample line / decisión)
- [ ] NO gastar ciclos investigando cosmetics whitelist confirmados

## Severity levels

| Level | Trigger | Action |
|---|---|---|
| CRITICAL | EAL.rename_asset sin isinstance Texture2D check | BLOCK merge |
| CRITICAL | Cleanup `EAL.delete_asset(old_path)` post-rename mismo loop | BLOCK |
| CRITICAL | Tag UE version ausente en KB-bound entry/comment | BLOCK |
| HIGH | save_asset sin verify disk file presence (MI critical) | WARN |
| HIGH | Root path scan_paths_synchronous cuando subfolder target | WARN |
| HIGH | Threshold multi-tex `>1` sin justificación | WARN |
| MEDIUM | Falta whitelist cosmetics en grep investigation | INFO |
| LOW | Asset path sin formato canónico estricto | NOTE |

## Anti-patterns review

- Asumir `EAL.rename_asset` falla solo por ausencia source asset (puede ser Texture2D collision destino `[UE 5.4]`)
- Approve diff que confía `EAL.does_asset_exist(path) == True` como prueba disk file presence (ghost entries posibles)
- Approve cleanup loop usando lista pre-rename sin trackear path mutations
- Approve script con APIs `unreal.*` mezclados con `fortnite_ue.*` (UEFN runtime — dominio separado)

## Cross-references

- `implementer-unreal/SKILL.md` G1-G4 gotchas concretos con código
- `coherence-auditor-unreal/SKILL.md` source-of-truth divergence patterns
- `F:\knowledge\unreal-python-editor\MEMORY.md` entries [UE 5.4] AUTO-CURATED
