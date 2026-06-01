---
name: knowledge-curator-unreal
description: Curation knowledge UE 5.4 Editor Python — append entries [UE x.y] tagged a <knowledge_root>/unreal-python-editor/MEMORY.md AUTO-CURATED markers. Auto-match keywords curate UE Editor, MEMORY.md unreal-python-editor, [UE 5.4] tag, pending migration verse-uefn, AUTO-CURATED markers UE Editor. NO UEFN runtime curation.
---

# knowledge-curator-unreal

## Scope

Append entries learnings UE 5.4 Editor Python a `<knowledge_root>\unreal-python-editor\MEMORY.md` entre markers `<!-- AUTO-CURATED:START -->` / `<!-- AUTO-CURATED:END -->`.

Solo `knowledge-curator` edita MEMORY.md. Solo entre markers. NUNCA mezclar con UEFN runtime entries (esos van a `verse-uefn/MEMORY.md`).

## Criticidad threshold

Append SOLO si:

- **≥2 instancias** cross-AR del pattern, **O**
- **Criticidad declarada** explícita en `final_report.md` postmortem ("CRITICIDAD: ALTA/MEDIA" sección "Lecciones para knowledge base")

Pattern menor 1 instancia + sin criticidad declarada → NO curate. Re-evaluar próxima ocurrencia.

### Meta-pattern confirmado (3 instancias, ALTA)

"AssetRegistry/Asset state inconsistencies" cross-AR:
- 1ª AR_2026-05-25 root rescan
- 2ª AR_2026-05-26 `EAL.delete_asset` stale path post-rename
- 3ª AR_2026-05-26 Texture2D collision ruta SK canónica

Nuevas instancias C6 sub-classes → append como sub-entry referenciando meta-pattern.

## Versionado tag obligatorio

Cada entry empieza con tag UE version. **NUNCA mezclar versions** en mismo entry — duplicar si API diverge.

| Tag | Uso |
|---|---|
| `[UE 5.4]` | Validado solo 5.4 |
| `[UE 5.4-5.6]` | Validado rango |
| `[UE ≥5.7]` | Disponible 5.7+ |
| `[UE all]` | Estable cross-version (rare, justificar) |
| `[UE ?]` | No verificado (flag future) |

## Entry format

```markdown
### [UE x.y] <Título descriptivo conciso>

- **AR**: AR_YYYY-MM-DD_<slug> (Hn attempt M CONFIRMED)
- **Lección (verbatim final_report)**: "<copy-paste literal del final_report.md, NO paraphrase>"
- **Pattern defensive obligatorio**: <síntesis del pattern fix>
- **Evidencia**: <probes ejecutados + resultados>
- **Criticidad**: ALTA/MEDIA/BAJA declarada (<razón breve, e.g., "Nª instancia meta-pattern X").
- **Fix aplicado**: `<absolute_path>` L<start>-L<end> <descripción mínima>
- **Fecha**: YYYY-MM-DD
```

## Phrasing literal

Reglas brief addendum Capa 3:

- **Verbatim del final_report**: NO paraphrase "Lección" field. Copy-paste exacto.
- **NO relax wording**: si final_report dice "obligatorio", curator NO suaviza a "recomendado"
- **NO ampliar scope**: si final_report scope = "post-glTF", curator NO generaliza a "post-import"

Violación phrasing → entry RECHAZADA por self-review pre-append.

## Markers AUTO-CURATED

```markdown
<!-- AUTO-CURATED:START -->

<!-- Entries nuevas append AQUÍ, al TOP (recent first) -->

### [UE 5.4] <Latest entry>
...

### [UE 5.4] <Previous entry>
...

<!-- AUTO-CURATED:END -->
```

Si markers ausentes → CREATE markers al final del file. NEVER edit fuera markers.

## Pending migration desde verse-uefn

TODO list al final `unreal-python-editor/MEMORY.md` sección "Pending migration":

Entries `verse-uefn/MEMORY.md` que son UE Editor (NO UEFN-specific) candidate migration:
- `[2026-05-25] UEFN Python 3.11 pipeline` — partes UE Editor: `MaterialEditingLibrary`, `AssetToolsHelpers`, `EditorAssetSubsystem`, `AssetRegistryHelpers`
- `[2026-05-26] AR_unreal-02-multimesh-and-spaces-fix` — `EAL.rename_asset` propagation + AssetRegistry stale post-rename

Mantener en `verse-uefn/` solo entries UEFN-specific:
- VFS mount per-project UEFN
- UEFN allow-list validation
- `M_BoneAnimation` / `M_ExampleAnimation` parents (UEFN materials específicos)

Migration workflow:
1. Identify entry candidate en `verse-uefn/MEMORY.md`
2. Verify UE Editor API only (no `fortnite_ue.*` ni Verse refs)
3. Copy a `unreal-python-editor/MEMORY.md` con tag `[UE 5.4]` (o version verified)
4. Mark original entry `verse-uefn/MEMORY.md` como `[MIGRATED → unreal-python-editor 2026-MM-DD]` o eliminar si pure UE Editor

## Workflow curation post-AR

1. AR closed-ok (final_report.md verdict OK)
2. Read `final_report.md` sección "Lecciones para knowledge base"
3. Identify learnings UE Editor-specific (vs UEFN runtime → otro curator)
4. Verificar threshold: ≥2 instancias O criticidad declarada
5. Verificar tag UE version present + validated
6. Append entry top sección AUTO-CURATED (recent first order)
7. Producir `curator_report.md` con: entries appended + path + line range + razón threshold cumplido
8. Si pattern declined → documentar razón en `curator_report.md` ("Pattern X: 1 instancia, sin criticidad declarada — defer hasta 2ª")

## Anti-patterns curation

- Append entry con 1 instancia + sin criticidad declarada (regla threshold)
- Paraphrase "Lección" field del final_report (regla phrasing literal)
- Append entry sin tag `[UE x.y]`
- Mezclar UE Editor entries con UEFN runtime entries en mismo MEMORY.md
- Editar MEMORY.md fuera markers AUTO-CURATED
- Editar `verse-uefn/MEMORY.md` desde este curator (separate domain)

## Cross-references

- `<knowledge_root>\unreal-python-editor\MEMORY.md` target file
- `<knowledge_root>\verse-uefn\MEMORY.md` domain separado (pending migration entries)
- `agent_templates/knowledge-curator.md` base agent (este skill extiende)
- Brief §3.4 addendum Capa 3 anti-sycophancy reglas curator
