---
name: hypothesis-reasoning-unreal
description: Razonamiento hipótesis bugs UE 5.4 Editor Python — bug class taxonomy GC collect, async load race, transient package leak, redirector loop, plugin reload state, AssetRegistry stale. Auto-match keywords hypothesis UE Editor, bug class UE, probe asset state, anti-loop UE 5.4, class-jump UE Editor. NO UEFN runtime.
---

# hypothesis-reasoning-unreal

## Scope

Generar/validar hipótesis bugs UE 5.4 Editor Python. Enforce anti-loop brief §2.3 (3 attempts max → class-jump obligatorio).

## Bug class taxonomy [UE 5.4]

Cuando hipótesis bug-fix se formula, classify primero. Si 3 attempts mismo class fallan → class-jump obligatorio.

### Class C1: GC collect mid-script

**Symptom típico**: asset reload silent mid-script, referencia Python pierde objeto, próximo `set_*` falla con None type error.

**Cause**: garbage collector Python libera referencia local cuando Editor Python ejecuta async tasks intermedias (`MaterialEditingLibrary.recompile_material()` etc.). Asset disk OK pero Python wrapper invalidado.

**Probe**:
```python
import gc
asset = EAL.load_asset(path)
gc.collect()  # force GC
reloaded = EAL.load_asset(path)
# Si asset is reloaded → False, GC liberó wrapper
```

**Fix pattern**: store `unreal.Object` references en list/dict module-level durante batch operations.

### Class C2: Async load race

**Symptom**: `MEL.set_material_instance_texture_parameter_value(mi, "Diffuse", tex)` aplicado pero MI no muestra textura. Save silent-drop.

**Cause**: Texture2D recién imported aún no terminó async load cuando set_param se llamó. Reference None internamente.

**Probe**:
```python
import unreal
tex = EAL.load_asset(tex_path)
# Force sync load
unreal.AssetRegistryHelpers.get_asset_registry().wait_for_completion()
# O delay manual
# TODO [UE 5.4] verify: delay() en Editor Python context (no gameplay tick) — alternativa: time.sleep() O AssetRegistry.wait_for_completion()
unreal.SystemLibrary.delay(1.0)
```

**Fix pattern**: `wait_for_completion()` + sanity check `tex is not None` antes de set_param.

### Class C3: Transient package leak

**Symptom**: assets aparecen en `/Engine/Transient/` post-import. `AR.get_assets_by_path("/Engine/Transient")` muestra acumulación cross-runs.

**Cause**: import factory crea staging assets en Transient package. Si script aborta mid-import, no cleanup.

**Probe**:
```python
transient_assets = AR.get_assets_by_path("/Engine/Transient", recursive=True)
count_before_run = len(transient_assets)
# Run script
transient_after = AR.get_assets_by_path("/Engine/Transient", recursive=True)
leaked = len(transient_after) - count_before_run
```

**Fix pattern**: try/finally con cleanup explicit transient assets. Restart Editor si leak persiste.

### Class C4: Redirector loop

**Symptom**: post-rename A → B → A genera circular redirector. Subsequent `EAL.load_asset(A)` cuelga o devuelve None.

**Cause**: rename consecutivo same script run sin `fixup_referencers` intermedio.

**Probe**:
```python
# Detectar redirector circular
AR_helpers = unreal.AssetRegistryHelpers
# unreal.EditorAssetLibrary.fixup_referencers([path]) limpia
```

**Fix pattern**: NEVER rename A → B → A mismo script. Si needed, `EAL.fixup_referencers([A, B])` entre rename ops.

### Class C5: Plugin reload state

**Symptom**: módulos Python `import my_plugin` mantienen globals cross-script execution. Variable stale rompe lógica nueva run.

**Cause**: Editor Python interpreter NO reinicia entre script runs. `globals()` persiste.

**Probe**:
```python
import sys
if "my_plugin" in sys.modules:
    # Module cached — reload
    import importlib
    importlib.reload(sys.modules["my_plugin"])
```

**Fix pattern**: explicit `importlib.reload()` al inicio script batch. O Editor restart entre dev iterations.

### Class C6: AssetRegistry stale (meta-pattern confirmado, 3 instancias)

**Symptom**: ver `coherence-auditor-unreal` D1-D5 patterns.

**Sub-classes**:
- C6a: Ghost entry post external filesystem op
- C6b: Per-folder rescan needed (root insufficient)
- C6c: Texture2D collision masquerading
- C6d: Cleanup loop iterating pre-rename list
- C6e: In-memory edit not committed

**Anti-loop NOTE**: C6 ya tiene 3 instancias cross-AR documentadas. Bug nuevo sospecha clase C6 → consultar `coherence-auditor-unreal` ANTES de probe propio.

## Anti-loop enforcement

### 3 attempts max

Cada attempt requiere:
- Hipótesis formulada explícita
- Probe confirmatorio diseñado
- Resultado probe documentado (CONFIRMED / REFUTED / INCONCLUSIVE)
- Si REFUTED → siguiente attempt mismo class OK
- Si 3 attempts REFUTED → **class-jump obligatorio** (cambiar a otra class C1-C6)

### Probe antes de fix

Hipótesis sin probe confirmatorio = **RECHAZADA**. NUNCA fix sin CONFIRMED en `hypotheses.md`.

### Source-of-truth divergence check

Antes de declarar "bug lógica", verificar las 4 capas estado (disk / AR / in-memory / redirector chain) consistentes via `coherence-auditor-unreal` patterns D1-D5.

### <user> observation precedence

Observación <user> > hipótesis agente. Pero distinguir modo:
- **Evidencia**: probe empírico <user> contradice → falsify hipótesis + replan
- **Intuición**: opinión sin probe → discutir + pedir test
- **Ambiguo**: PEDIR clarification verbatim ANTES de actuar

## Workflow

1. Symptom reportado → classify C1-C6
2. Formular hipótesis específica con class tag
3. Diseñar probe confirmatorio
4. Run probe → resultado CONFIRMED / REFUTED / INCONCLUSIVE
5. Si CONFIRMED → escalar a `implementer-unreal` con fix pattern del class
6. Si REFUTED → attempt 2 mismo class OK (max 3)
7. Si 3 REFUTED → class-jump documentar razón

## Tag versionado obligatorio

Cada bug class entry/probe `[UE 5.4]` o `[UE x.y]`. NO mezclar versions sin probe explícito.

## Cross-references

- `coherence-auditor-unreal/SKILL.md` D1-D5 source-of-truth divergence (subset C6)
- `implementer-unreal/SKILL.md` G1-G4 fix patterns concretos
- `<knowledge_root>\unreal-python-editor\MEMORY.md` entries [UE 5.4] AUTO-CURATED
