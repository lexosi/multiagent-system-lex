<#
.SYNOPSIS
    UserPromptSubmit hook — inyecta recordatorio de bloque [AGENTE-ACTIVO] cada turn.

.DESCRIPTION
    Cada vez que Lexosi envia prompt, este hook inyecta additionalContext
    recordando a root que la respuesta debe empezar con:
        [AGENTE-ACTIVO]: <nombre>
        [TAREA]: <una linea>
        [HIPOTESIS]: <id o N/A>

    Resuelve dolor "no veo que agente trabaja" detectado 2026-05-18.

    El hook NO bloquea ni denega — solo inyecta recordatorio.
    Si root omite el bloque, root-discipline-auditor lo flag post-AR.

.NOTES
    Trigger: UserPromptSubmit
    Output: stdout JSON con hookSpecificOutput.additionalContext
    Exit 0 siempre (never block on visibility check).

    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> log a hooks\.debug.log
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

# --- Bootstrap: derive paths from env var or PROD fallback ---
$PathsJson = if ($env:MULTIAGENT_PATHS_CONFIG -and (Test-Path -LiteralPath $env:MULTIAGENT_PATHS_CONFIG)) {
    $env:MULTIAGENT_PATHS_CONFIG
} else {
    "F:\multiagent-system\config\paths.json"
}

$RepoRoot     = Split-Path -Parent (Split-Path -Parent $PathsJson)
$DebugLogPath = Join-Path $RepoRoot "hooks\.debug.log"

$DebugMode = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"
function Write-DebugLog($msg) {
    if ($DebugMode) {
        $logPath = $DebugLogPath
        $timestamp = (Get-Date).ToString("o")
        try { Add-Content -Path $logPath -Value "[$timestamp] [userpromptsubmit-visibility-reminder.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
    }
}

# --- Consume stdin (no se usa el contenido) ---
try {
    $stdinRaw = [Console]::In.ReadToEnd()
    Write-DebugLog "stdin bytes: $($stdinRaw.Length)"
} catch {
    Write-DebugLog "stdin read failed (ok, no critical): $($_.Exception.Message)"
}

Write-DebugLog "ENTRY"

# --- Emit reminder ---
$reminderText = @"
[VISIBILITY-REMINDER] Empieza tu respuesta SIEMPRE con bloque obligatorio.

REGLA ROOT-ACTIVE BANNER (since 2026-05-18): si [AGENTE-ACTIVO] = "root direct" O "root", PREPEND banner ANTES del bloque:

============================================================
ATENCION - ROOT EJECUTANDO TAREA DIRECTA
Lexosi: revisa que no usurpe rol de subagente.
============================================================

Si [AGENTE-ACTIVO] = subagent (planner/implementer/reviewer/etc.) NO uses banner. Solo bloque normal.

BLOQUE OBLIGATORIO (siempre):

[AGENTE-ACTIVO]: <nombre>
[TAREA]: <una linea>
[HIPOTESIS]: <id si bug-fix activo, "N/A" otherwise>

<nombre> = subagent que invocas este turn O "root direct" si accion directa autorizada.
Aplica a TODOS los turns (sustantivos y conversacionales). Si conversacion informal: [AGENTE-ACTIVO]: root | [TAREA]: conversacion | [HIPOTESIS]: N/A.

CAP 4 EXTENSION (since 2026-05-18): si turn implica Edit/Write directo del root, AnAde lineas:
[SCOPE]: archivos=<lista> | lineas=<ranges si aplica>
[ANTI-SCOPE]: NO toco <archivos vecinos / lineas vecinas> porque <razon>

Si turn implica trabajo bug-fix activo (hipotesis registrada), AnAde:
[ATTEMPTS]: H<id>=N/3

CAP N2 EXTENSION (since 2026-05-18): si root usa Grep como pre-check de scope cleanup >=1 simbolo (preparando borrado / refactor cross-file), AnAde lineas:
[PRECHECK]: simbolo=<X> | hits_grep=N | archivos_leidos_completos=<lista> | confianza=low/med/high

Si archivos_leidos_completos < archivos donde grep dio hits -> confianza=low -> ESCALAR Lexosi antes de proseguir.

Omision 2+ turns consecutivos mismo AR -> root-discipline-auditor flag violacion.
"@

$payload = @{
    hookSpecificOutput = @{
        hookEventName     = "UserPromptSubmit"
        additionalContext = $reminderText
    }
}
$json = $payload | ConvertTo-Json -Depth 5 -Compress
[Console]::Out.WriteLine($json)
Write-DebugLog "EXIT 0 (reminder injected)"
exit 0
