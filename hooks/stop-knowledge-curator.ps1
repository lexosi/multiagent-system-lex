<#
.SYNOPSIS
    Stop hook — detecta AR cerrados (final_report.md recien creado sin curator_report.md
    correspondiente) y registra ar_ids en .curator_pending para proxima sesion.

.DESCRIPTION
    Stop hook fires al fin de CADA turn — no hay evento "AR cerrado" nativo.
    Heuristica: scan F:\multiagent-system\docs\agent_runs\AR_*\final_report.md,
    filtra mtime < 5min Y sin curator_report.md hermano, registra en
    F:\multiagent-system\.curator_pending (JSON merge si ya existe).

    SessionStart proxima sesion lee .curator_pending y notifica al root
    via additionalContext. One-shot (consume y borra).

.NOTES
    Trigger: Stop (sin matcher).
    Exit code: 0 SIEMPRE (Stop hook nunca debe bloquear turn).
    Errores -> log file, NUNCA stderr (evita ruido en transcript).

    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> log a hooks\.debug.log
#>

[CmdletBinding()]
param()

# ---- DEFENSIVE: este hook NUNCA debe abortar el turn ----
$ErrorActionPreference = "Continue"
trap {
    # capturar cualquier error no manejado y exit 0
    # Nota: trap puede dispararse antes de que el bloque de constantes cargue $LogPath;
    # fallback inline derivado de $PSScriptRoot evita NullRef. Trap se EJECUTA on-error,
    # no on-define — orden de loading garantiza $LogPath disponible salvo error early.
    try {
        $trapLogPath = if ($LogPath) { $LogPath } else { Join-Path $PSScriptRoot ".stop-curator.log" }
        $timestamp = (Get-Date).ToString("o")
        Add-Content -Path $trapLogPath -Value "[$timestamp] TRAP: $($_.Exception.Message)" -ErrorAction SilentlyContinue
    } catch {
        Write-Host "[stop-curator trap] log failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    exit 0
}

# --- Bootstrap: resolver paths.json + repo root con env var override ---
# Precedence: MULTIAGENT_PATHS_CONFIG env var > hardcoded PROD fallback
$PathsJson = if ($env:MULTIAGENT_PATHS_CONFIG -and (Test-Path -LiteralPath $env:MULTIAGENT_PATHS_CONFIG)) {
    $env:MULTIAGENT_PATHS_CONFIG
} else {
    "F:\multiagent-system\config\paths.json"  # default PROD fallback
}

$RepoRoot       = Split-Path -Parent (Split-Path -Parent $PathsJson)
$AgentRunsDir   = Join-Path $RepoRoot "docs\agent_runs"
$CuratorPending = Join-Path $RepoRoot ".curator_pending"
$LogPath        = Join-Path $RepoRoot "hooks\.stop-curator.log"
$DebugLogPath   = Join-Path $RepoRoot "hooks\.debug.log"
$WindowMinutes  = 5

# --- Debug helper ---
$DebugMode = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"
function Write-DebugLog($msg) {
    if ($DebugMode) {
        $timestamp = (Get-Date).ToString("o")
        try { Add-Content -Path $DebugLogPath -Value "[$timestamp] [stop-knowledge-curator.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
    }
}

function Write-OpLog($msg) {
    try {
        $timestamp = (Get-Date).ToString("o")
        Add-Content -Path $LogPath -Value "[$timestamp] $msg" -ErrorAction SilentlyContinue
    } catch {}
}

# --- Consume stdin (descarta) ---
try { [Console]::In.ReadToEnd() | Out-Null } catch {}

Write-DebugLog "ENTRY"

# --- 1. Verificar agent_runs dir ---
if (-not (Test-Path -LiteralPath $AgentRunsDir)) {
    Write-DebugLog "no agent_runs dir; nothing to scan"
    exit 0
}

# --- 2. Scan AR_*/final_report.md ---
$cutoff = (Get-Date).AddMinutes(-$WindowMinutes)
$candidates = @()
try {
    $arDirs = Get-ChildItem -LiteralPath $AgentRunsDir -Directory -Filter "AR_*" -ErrorAction SilentlyContinue
    foreach ($ar in $arDirs) {
        $finalReport = Join-Path $ar.FullName "final_report.md"
        $curatorReport = Join-Path $ar.FullName "curator_report.md"
        if ((Test-Path -LiteralPath $finalReport) -and (-not (Test-Path -LiteralPath $curatorReport))) {
            $finalItem = Get-Item -LiteralPath $finalReport
            if ($finalItem.LastWriteTime -gt $cutoff) {
                $candidates += $ar.Name
                Write-DebugLog "candidate: $($ar.Name) (mtime: $($finalItem.LastWriteTime.ToString('o')))"
            }
        }
    }
} catch {
    Write-OpLog "scan error: $($_.Exception.Message)"
    Write-DebugLog "scan error: $($_.Exception.Message)"
    exit 0
}

if ($candidates.Count -eq 0) {
    Write-DebugLog "no candidates; exit"
    exit 0
}

# --- 3. Merge con .curator_pending existente ---
$existingIds = @()
if (Test-Path -LiteralPath $CuratorPending) {
    try {
        $existing = Get-Content -LiteralPath $CuratorPending -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
        if ($existing.ar_ids) { $existingIds = @($existing.ar_ids) }
    } catch {
        Write-DebugLog ".curator_pending corrupt; overwrite: $($_.Exception.Message)"
    }
}

$mergedIds = ($existingIds + $candidates) | Sort-Object -Unique
$payload = @{
    detected_at = (Get-Date).ToString("o")
    ar_ids      = $mergedIds
}

# --- 4. Escribir .curator_pending ---
try {
    $payload | ConvertTo-Json -Depth 3 | Out-File -FilePath $CuratorPending -Encoding utf8 -Force
    Write-OpLog "wrote curator_pending: $($mergedIds -join ', ')"
    Write-DebugLog "wrote curator_pending ($($mergedIds.Count) ids)"
} catch {
    Write-OpLog "write failed: $($_.Exception.Message)"
    Write-DebugLog "write failed: $($_.Exception.Message)"
}

exit 0
