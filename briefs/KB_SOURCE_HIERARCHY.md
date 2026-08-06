# KB_SOURCE_HIERARCHY — Jerarquía de fuentes para resolver dudas técnicas de dominio

**Tipo**: doc canon de gobernanza (cross-dominio: verse-uefn, unreal, blender, y cualquier dominio futuro).
**Aplica a**: todo agente que resuelva una duda técnica de dominio (root, specialists, implementer, planner, curator, auditores).
**Cross-ref**: `briefs/ANTI_SYCOPHANCY_ADDENDUM.md`, `briefs/ANTI_MEMORY_VERIFICATION.md`, tags de confianza A3 (Fase 1).

---

## Para qué sirve

Define el **orden canónico** al resolver CUALQUIER duda técnica de dominio (¿renderiza?, ¿qué API?, ¿qué nombre/tipo de widget?, ¿este claim del KB sigue siendo cierto?). El sistema arrastraba dos fallos: (a) canonizar claims sin verificar, (b) tratar el KB / un senior / Epic como autoridad absoluta cuando el comportamiento in-game decía otra cosa. Esta jerarquía fija quién gana en conflicto.

---

## Los 5 niveles (de mayor a menor autoridad)

| Nivel | Fuente | Qué es | Autoridad |
|---|---|---|---|
| **N0** | **Empírico in-game** | Lo que de verdad renderiza / funciona / cruza en el proyecto real. Oráculo <user> observando el editor/partida. | **GANA SIEMPRE.** Ground-truth. |
| **N1** | **Precedente que YA funciona** | Hermano/análogo del propio proyecto que funciona (Pagination, sibling-que-renderiza) + indicación de dev senior. | Fuerte, pero subordinado a N0. |
| **N2** | **Doc oficial Epic** | `dev.epicgames.com` / `create.fortnite.com` (y equivalentes oficiales del dominio). | Hint autorizado, no gospel. |
| **N3** | **Internet fiable** | Foros reputados, repos, blogs técnicos verificables. | Hint débil. |
| **N4** | **Técnicas propias descubiertas** | Lo que canoniza A5: paste-hierarchy `.txt`, leer widgets via T3D/MCP, y futuros descubrimientos del sistema. | Útil, pero la MÁS susceptible de sobre-generalizar. |

> Orden de autoridad: **N0 > N1 > N2 > N3 > N4.**

---

## Reglas duras

1. **En conflicto entre niveles, gana el nivel MÁS BAJO en número (el más empírico).** N0 vence a todo; N1 vence a N2..N4; etc. Senior / Epic / KB propio = **hints, no gospel**. Esto es el principio Anthropic del memory-tool aplicado al KB: *"memory is a hint surface, not an authority surface — verify by reading current state"*. El KB (incluido N4) es superficie de pistas; el estado real (N0) se verifica leyéndolo.

2. **Nada se marca `CONFIRMED-in-game` sin oráculo empírico de <user>.** Tags de confianza obligatorios (A3 Fase 1) en toda entrada de KB:
   - `CONFIRMED-in-game` — validado por <user> observando el proyecto (N0). Único tag que puede contradecir niveles superiores.
   - `CONFIRMED-oficial` — respaldado por doc oficial Epic (N2), sin oráculo in-game aún.
   - `inferido` — deducido de N1..N4 sin verificación directa.
   - `UNKNOWN-needs-probe` — sin fuente fiable; requiere probe antes de usar.

3. **Aplica cross-dominio.** No solo UEFN: vale igual para Unreal (UE Editor Python), Blender (bpy), y cualquier dominio que se añada. La jerarquía es de gobernanza, no de un dominio concreto.

---

## Caso de prueba aplicado — bug material cross-WBP (Fase 1, A2)

| Paso | Qué pasó |
|---|---|
| **Claim N4 (KB)** | El KB tenía una técnica propia sobre-generalizada: *"2 saltos no propagan cross-WBP"* — tratado como verdad absoluta. |
| **N1 + N0 lo falsifican** | Dev senior + test in-game de <user>: el **TEXTO sí cruza** cross-WBP; solo el **MATERIAL/recurso** no propaga. El claim N4 era falso por sobre-generalización. |
| **Resolución por jerarquía** | N0 empírico (in-game) y N1 (senior + sibling) vencen a N4 (KB). El claim se corrige, no se mantiene "porque está en el KB". |
| **Lección** | Si esta jerarquía hubiera estado vigente, el claim N4 falso **nunca se habría canonizado como autoridad** — se habría marcado `inferido` y verificado contra N0 antes de tratarlo como hecho. |

---

## Resumen operativo (1 línea por agente)

- **Duda técnica** → recorre N0→N4 y usa la fuente más baja disponible; si dos chocan, gana la de número menor.
- **¿Marcar CONFIRMED-in-game?** → solo con oráculo <user> (N0). Si no, `inferido` / `UNKNOWN-needs-probe`.
- **KB dice X pero in-game dice Y** → gana in-game (N0). Corrige el KB, no la realidad.
