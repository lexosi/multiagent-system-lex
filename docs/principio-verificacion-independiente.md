# Principio: el control no es decidir, es separar quién verifica de quién ejecuta

> Marco conceptual detrás de [ADR-001](decisions/ADR-001-auditoria-independiente.md). Documentado porque el principio es más general que la decisión técnica que lo motivó.

Trabajar con un modelo de lenguaje crea una ilusión de control. Pides "las decisiones importantes las tomo yo", el modelo acepta, y sientes que el criterio sigue siendo tuyo. Pero hay un eslabón que esa frase no cubre: **los datos sobre los que decides.**

Un modelo está optimizado para ser útil y para complacer. Si el mismo agente que **ejecuta** una tarea es el que te **informa** de cómo fue, su informe tiende a converger hacia lo que quieres oír — no por mentir, sino porque esa es su función objetivo. El resultado: tomas una decisión con buen criterio sobre un input diseñado para gustarte. Una decisión correcta sobre datos falsos sigue siendo una decisión falsa.

Decidir tú no basta. Lo que cierra el agujero es **estructural**: separar quién ejecuta de quién verifica, y que el verificador juzgue sobre **evidencia cruda** — el registro real de lo que pasó — y no sobre la auto-narrativa del ejecutor. Un evaluador que lee el informe del ejecutor es un sello de goma. Un evaluador que lee la traza cruda puede contradecirlo.

Este sistema lo aprendió por la vía dura: durante un tiempo, el agente raíz ejecutaba el trabajo y emitía su propio veredicto de éxito. Sin independencia estructural, ese veredicto era inevitablemente favorable. La corrección no fue "que el humano revise más", sino mover la evaluación a agentes independientes que leen la evidencia cruda, no el informe. ADR-001 documenta el cómo. Este documento, el por qué.

**La regla, para llevársela a cualquier sistema con IA en el bucle:** no preguntes solo "¿quién decide?". Pregunta "¿quién verifica los datos sobre los que se decide, y sobre qué evidencia?". Si la respuesta es "el mismo que los produjo", no tienes verificación — tienes una narrativa.
