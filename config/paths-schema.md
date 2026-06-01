# paths-schema — esquema de `config/paths.json`

## Propósito

Centralizar **todas las rutas absolutas** del sistema multi-agente en un único archivo JSON. Permite **portabilidad** entre usuarios e instalaciones: los system prompts contienen placeholders `{{paths.X.Y}}`, y un hook de session-start los sustituye por los valores reales en cada máquina. Cambiar de equipo (o de letra de unidad) requiere editar solo `paths.json`, no decenas de prompts.

## Tabla de claves

| Clave (dot-notation)             | Tipo   | Valor esperado                                                | Ejemplo                                              |
| -------------------------------- | ------ | ------------------------------------------------------------- | ---------------------------------------------------- |
| `knowledge_base`                 | string | Ruta absoluta a la raíz del knowledge base                    | `<knowledge_root>`                                       |
| `multiagent_root`                | string | Ruta absoluta a la raíz del repo multi-agente                 | `<repo_root>`                               |
| `uefn_projects_root`             | string | Ruta absoluta al directorio padre de proyectos UEFN           | `<uefn_root>`                                           |
| `uefn_output_log`                | string | Ruta a logs de Fortnite/UEFN (env vars literales permitidas)  | `%LOCALAPPDATA%\FortniteGame\Saved\Logs`             |
| `domains.verse-uefn`             | string | Carpeta de dominio Verse/UEFN dentro del knowledge base       | `<knowledge_root>\verse-uefn`                            |
| `domains.python`                 | string | Carpeta de dominio Python                                     | `<knowledge_root>\python`                                |
| `domains.rust`                   | string | Carpeta de dominio Rust                                       | `<knowledge_root>\rust`                                  |
| `domains.java`                   | string | Carpeta de dominio Java                                       | `<knowledge_root>\java`                                  |
| `domains.typescript-bun`         | string | Carpeta de dominio TypeScript/Bun                             | `<knowledge_root>\typescript-bun`                        |
| `domains.cross-language`         | string | Carpeta de dominio cross-language                             | `<knowledge_root>\cross-language`                        |

## Convención de uso en system prompts

- Sintaxis: `{{paths.<key>}}` o `{{paths.<group>.<key>}}` con **dot-notation** para anidados.
- El hook recorre el JSON recursivamente y construye placeholders planos para cada hoja string.

Ejemplos válidos:

- `{{paths.knowledge_base}}`
- `{{paths.multiagent_root}}`
- `{{paths.domains.verse-uefn}}`
- `{{paths.uefn_output_log}}`

## Cómo usar en system prompts

Antes (placeholder en el `.md` original):

```
Lee la documentación canónica desde {{paths.domains.verse-uefn}}\index.md
y escribe los logs detectados en {{paths.uefn_output_log}}.
```

Después (resultado tras la sustitución por el hook):

```
Lee la documentación canónica desde <knowledge_root>\verse-uefn\index.md
y escribe los logs detectados en %LOCALAPPDATA%\FortniteGame\Saved\Logs.
```

## Override por env var

- `$env:MULTIAGENT_PATHS_CONFIG` puede apuntar a un archivo JSON alternativo.
- Útil para CI, testing, o un override per-user sin tocar el `paths.json` versionado.
- Si la variable está vacía o no existe, se usa `<repo_root>\config\paths.json` por defecto.

PowerShell:

```powershell
$env:MULTIAGENT_PATHS_CONFIG = "C:\Users\otro\paths.local.json"
```

## Variables del sistema dentro de paths

- Variables tipo `%LOCALAPPDATA%`, `%APPDATA%`, `%USERPROFILE%`, etc. **se preservan literales** en el output del hook.
- El hook **NO** las expande. La expansión es responsabilidad del consumidor final (la herramienta o agente que usa la ruta en runtime).
- Razón: mantener la portabilidad entre usuarios cuando la ruta resuelta cambia por sesión.

## Validación

Claves **requeridas** en v1 (todas las del `paths.json` actual):

- `knowledge_base`
- `multiagent_root`
- `uefn_projects_root`
- `uefn_output_log`
- `domains.verse-uefn`
- `domains.python`
- `domains.rust`
- `domains.java`
- `domains.typescript-bun`
- `domains.cross-language`

Claves **opcionales**: ninguna en v1. Cualquier clave futura debe documentarse aquí antes de añadirse al JSON.
