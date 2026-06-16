# Architecture Decision Records (ADRs)

Decisiones de arquitectura del sistema multiagente, documentadas y curadas.

## Convención

- Numeración **secuencial por repositorio**: `ADR-001`, `ADR-002`, … Es el orden de las decisiones documentadas *en este repo*, no un conteo global del proyecto.
- Cada ADR es inmutable una vez aceptado. Una decisión que reemplaza a otra se documenta como un ADR nuevo que marca el anterior como *Reemplazado*, en lugar de editarlo.
- Formato: contexto → decisión → límites conocidos → consecuencias.

## Procedencia

Esta serie pública es un **subconjunto curado**. El sistema acumula 123 ARs productivos (Agent Runs) con audit trail completo y una serie de ADRs internos que vive en otros repositorios del proyecto. Aquí se publican solo las decisiones que **no contienen información de proyectos propios** — son decisiones de arquitectura del orquestador, no datos de clientes ni de builds. Por eso `ADR-001` aquí no implica "primera decisión del sistema", sino "primera decisión documentada en este repositorio público".

## Índice

| ADR | Título | Estado |
|---|---|---|
| [ADR-001](ADR-001-auditoria-independiente.md) | Auditoría independiente del cierre de AR (outcome / process) y protección de escritura por `agent_type` | Aceptada |
