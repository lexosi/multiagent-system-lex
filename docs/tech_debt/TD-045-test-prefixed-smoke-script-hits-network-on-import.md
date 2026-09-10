# TD-045 — Un `test_*` que no es un test hace una llamada de red en el import

**Clase**: hazard de collection de pytest / naming engañoso
**Estado**: OPEN — anotado, no diagnosticado (sin PASO 0)
**Abierto**: 2026-09-10
**Relación**: destapado al correr `pytest` desde la raíz tras añadir la suite
de coherencia de config (H-1) y el guard de dependencias (H-3).

## El fallo de clase

`config/test_deepseek_connection.py` se llama `test_*` pero **no es un test**:
es un smoke script de conexión. Y ejecuta una **llamada de red a nivel de
módulo** — no está bajo `if __name__ == "__main__"`. Al **importarlo** sale a
`https://api.deepseek.com`.

`pytest` desde la raíz — lo primero que prueba quien clona — **colecciona** ese
fichero por el prefijo `test_`, lo importa, y con ello **intenta salir a
internet**. La única razón por la que no explota siempre es que el flujo real
invoca `pytest tests/`, no `pytest` a secas.

## Concretamente

- `config/test_deepseek_connection.py:3` — `from openai import OpenAI`
- `config/test_deepseek_connection.py:10` — `client = OpenAI(..., base_url="https://api.deepseek.com")`, a nivel de módulo
- `config/test_deepseek_connection.py:17` — `resp = client.chat.completions.create(...)` — **la llamada de red, en el import, sin guard `__main__`**

(Con el stub de OpenAI del `conftest`, la collection revienta con
`AttributeError: '_StubOpenAI' object has no attribute 'chat'` — misma causa:
código de red ejecutándose al importar.)

## ¿Se repite el patrón?

Ficheros `test_*` fuera de `tests/`:

- **este snapshot público**: 1 — `config/test_deepseek_connection.py` (el hazard).
- **repo fuente privado**: 2 — `config/test_deepseek_connection.py` (el hazard) + `eval/test_run_eval.py`.

`eval/test_run_eval.py` (fuente privada, ausente de este snapshot) **sí es un
test real** (`unittest`, fixtures sintéticas, guardado por
`if __name__ == "__main__"`, sin red). Comparte nombre y ubicación fuera de
`tests/` pero **no** el hazard; se lista para cerrar el barrido.

## Consecuencia

`git clone` + `pytest` = intento de red no anunciado en el primer comando que
cualquiera prueba. Sin `DEEPSEEK_API_KEY` o sin el stub del conftest, el fallo
cambia de forma, pero el intento de salida a internet sigue estando en el import.

## Fuera de scope hoy

Solo anotación. **No se propone solución**: renombrar (quitar el prefijo
`test_`), moverlo fuera del path de collection, o mover la llamada bajo
`if __name__ == "__main__"` son opciones distintas y es **decisión**.
