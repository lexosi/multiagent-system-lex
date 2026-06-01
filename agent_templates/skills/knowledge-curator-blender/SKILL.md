---
name: knowledge-curator-blender
description: Skill para knowledge-curator cuando AR closed-ok target pipeline Blender Python (bpy, bmesh, --background --python, glTF export, Cycles bake, atlas, action.slots, process_blend, .blend, .glb). Pattern docs F:\knowledge\blender-python\MEMORY.md tag [Blender 5.1.2].
---

# knowledge-curator-blender

## Cuándo cargar

Auto-match cuando AR closed-ok requiere curación KB pattern Blender (final_report.md cita `bpy`, `bmesh`, `process_blend`, atlas/bake/paint, `.blend`, `.glb`). Skill complementa knowledge-curator base con criterios MEMORY.md Blender 5.1.2.

## KB target

- **Path canónico**: `{{paths.knowledge_base}}/blender-python/MEMORY.md`.
- **Markers**: `<!-- AUTO-CURATED:START -->` ... `<!-- AUTO-CURATED:END -->`. Solo curator edita entre markers.
- **Append-order**: new entries en TOP (recent first), append antes de marker END.

## Workstation context Lexosi

- **Blender 5.1.2 Steam**: `F:\SteamLibrary\steamapps\common\Blender\blender.exe`.
- **Working dir típico**: `<projects_root>\ExampleBlenderProject\ExampleAssetSet\`.
- Entries deben asumir esta workstation salvo override explícito.

## Versionado tag obligatorio

Cada entry empieza con tag Blender version:

| Tag | Significado |
|---|---|
| `[Blender 5.1.2]` | Validado solo Blender 5.1.2 (Lexosi current) |
| `[Blender 5.1+]` | Disponible 5.1 en adelante |
| `[Blender 4.x-5.x]` | Validado cross-major-version |
| `[Blender all]` | API estable cross-version (rare, justify) |
| `[Blender ?]` | No verificado version-specific (flagged for future validation) |

**NO mezclar major versions** en mismo entry sin justificación explícita. Frontmatter docs: `validated_in: [5.1.2]`.

## Criticidad threshold

Pattern documentable si:

- **≥2 instancias** cross-AR del mismo issue/solution, O
- **Criticidad declarada** en postmortem final_report ("Lecciones para knowledge base" sección verbatim).

### Patterns ALTA precedentes (single-AR OK si declarada verbatim)

- Manual list `frozenset({...})` supera auto-detection batches `<10` (AR_2026-05-26 fly-exampleassets).
- Y-axis convention coherence paste/UV (AR_2026-05-26 multitex-atlas — verbatim "Remover Y invert es crítico").
- Atlas paint pure-math supera Cycles bake DIFFUSE multi-slot (AR_2026-05-26 — scope completo AR principal).
- MESH-bound actions structural drops pre-export (AR_2026-05-26 — scope completo AR principal).
- `action.fcurves` DEPRECATED → `action.slots+layers+strips+channelbag(slot).fcurves` (AR_2026-05-26 — verbatim "Crítico para futuras introspections").

### Patterns MEDIA precedentes

- Single offset constant insuficiente batches heterogéneos (AR_2026-05-26 — sección "Lecciones" explicit).
- uint8 RGBA BaseColor size reduction GLB ~7% (AR_2026-05-26 — Lexosi explicit ask + empirical validation).

## Phrasing literal

- **Verbatim final_report**: extraer lección literal desde final_report.md sección "Lecciones para knowledge base". NO paraphrase.
- **Verbatim Lexosi**: si TEST-GATE/feedback cita Lexosi → comillas dobles + atribución.
- **NO relajar**. Si final_report dice "crítico" → entry dice "crítico" (no "importante"/"recomendado").

## Entry template

```markdown
### [Blender x.y.z] <titular conciso pattern>

- **AR**: AR_YYYY-MM-DD_<slug> (ESTADO, qualifier opcional)
- **Lección (verbatim final_report)**: "<cita literal>"
- **Implicación**: <≤2 líneas — cuándo aplica el pattern>
- **Evidencia**: <métrica/probe/test-gate específico, archivos+líneas si aplica>
- **Criticidad**: <ALTA|MEDIA|BAJA> declarada (sección "Lecciones" explicit | postmortem | empirical N instancias)
- **Fecha**: YYYY-MM-DD
```

## Constraints adicionales

- **Fix aplicado** opcional: si pattern incluye refactor concreto, citar `file.py LXXX-LYYY` + summary 1 línea.
- **NO inventar APIs**. Si entry cita método/atributo Blender → verificable vs `bpy.types` API ref [Blender 5.1.2].
- **Workaround flag**: si fix es workaround (no resolution completa), declarar explicit ("workaround parcial: ... NO resuelve X").
- **Implicación constraint**: si pattern frágil bajo condición Y, declarar explicit ("Constraint: '<verbatim>'").

## Curador post-AR workflow

1. **Read** `final_report.md` AR closed-ok target.
2. **Identify** sección "Lecciones para knowledge base" / "Pattern docs" / "Criticidad declarada".
3. **Cross-check** vs MEMORY.md existing entries — duplicates? extensions?
4. **Threshold check**: ≥2 instancias O criticidad declarada? Si NO → escalate Lexosi (no append).
5. **Append entry** entre markers AUTO-CURATED en MEMORY.md (TOP, antes END marker).
6. **Verify**: tag `[Blender x.y.z]` presente, verbatim phrasing, evidence cited.
7. **Report**: `curator_report.md` en AR dir con entry appended + justification.

## Anti-patterns curación

- Entry sin tag `[Blender x.y.z]` → REJECT.
- Phrasing relajado vs final_report verbatim → REJECT.
- Single-AR sin criticidad declarada → REJECT (threshold no met).
- Duplicate de entry existente sin extension nueva → REJECT.
- Append fuera de markers `<!-- AUTO-CURATED:START/END -->` → REJECT (hook bloquea).
- Cross-version claim sin validation (`[Blender 4.x-5.x]` sin AR multi-version) → flag `[Blender ?]` en su lugar.
- Inventar API method no verificable vs `bpy.types` Blender 5.1.2 ref → REJECT.

## CLAUDE.md cross-doc reference

Si pattern Blender crítico merece visibility CLAUDE.md "Recent learnings" (auto-curated last 10 ARs):

- Entry CLAUDE.md ≤3 líneas, formato `[YYYY-MM-DD] <titular>` + cita AR + verbatim 1 frase.
- Solo entre markers `<!-- AUTO-CURATED:START/END -->` CLAUDE.md.
- NO duplicar entry full MEMORY.md — solo summary + referencia AR.
