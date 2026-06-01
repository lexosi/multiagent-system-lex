<#
.SYNOPSIS
    Stop hook reactivo — detecta ARs cerrados (final_report.md mtime <2h)
    sin root_audit_report.md hermano, escribe flag .auditor_pending
    en el AR dir para invocacion manual next session.

.DESCRIPTION
    Pattern paralelo a stop-knowledge-curator.ps1 (curator pending detection)
    pero per-AR flag file (NO archivo agregado global).

    Trigger: Stop event (cada turn end CC v2.1.146).
    Scan: AR_*/final_report.md mtime ultimas 2h.
    Per AR: si NO existe root_audit_report.md hermano Y NO existe .auditor_pending,
    escribe .auditor_pending con timestamp + msg.

    NO touch settings.json (registracion separada step 7).
    NO touch otros archivos AR.

.NOTES
    Exit 0 SIEMPRE (Stop hook contract).
    Errores -> trap silent + debug log (NUNCA stderr).
    Encoding flag file: UTF-8 sin BOM via [System.IO.File]::WriteAllText.
    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> hooks\.debug.log
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
trap { exit 0 }

# --- Bootstrap paths ---
$PathsJson = if ($env:MULTIAGENT_PATHS_CONFIG -and (Test-Path -LiteralPath $env:MULTIAGENT_PATHS_CONFIG)) {
    $env:MULTIAGENT_PATHS_CONFIG
} else {
    "F:\multiagent-system\config\paths.json"
}

$RepoRoot     = Split-Path -Parent (Split-Path -Parent $PathsJson)
$AgentRunsDir = Join-Path $RepoRoot "docs\agent_runs"

# --- Constantes ---
$WindowHours   = 2
$DebugMode     = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"

function Write-DebugLog($msg) {
    if (-not $DebugMode) { return }
    try {
        $logPath = Join-Path $RepoRoot "hooks\.debug.log"
        $timestamp = (Get-Date).ToString("o")
        Add-Content -Path $logPath -Value "[$timestamp] [stop-no-auditor.ps1] $msg" -ErrorAction SilentlyContinue
    } catch {}
}

# --- Consume stdin (descarta) ---
try { [Console]::In.ReadToEnd() | Out-Null } catch {}

Write-DebugLog "ENTRY"

if (-not (Test-Path -LiteralPath $AgentRunsDir)) {
    Write-DebugLog "no agent_runs dir; exit"
    exit 0
}

$cutoff = (Get-Date).AddHours(-$WindowHours)
$flagged = 0
$cleaned = 0

try {
    $arDirs = Get-ChildItem -LiteralPath $AgentRunsDir -Directory -Filter "AR_*" -ErrorAction SilentlyContinue
    foreach ($ar in $arDirs) {
        $finalReport  = Join-Path $ar.FullName "final_report.md"
        $auditReport  = Join-Path $ar.FullName "root_audit_report.md"
        $pendingFlag  = Join-Path $ar.FullName ".auditor_pending"

        if (-not (Test-Path -LiteralPath $finalReport)) { continue }

        # Cleanup orphan flag: audit report exists -> remove stale .auditor_pending
        if ((Test-Path -LiteralPath $auditReport) -and (Test-Path -LiteralPath $pendingFlag)) {
            try {
                Remove-Item -LiteralPath $pendingFlag -Force -ErrorAction SilentlyContinue
                $cleaned++
                Write-DebugLog "cleanup: .auditor_pending removed (root_audit_report.md exists) in $($ar.Name)"
            } catch {
                Write-DebugLog "cleanup failed $($ar.Name): $($_.Exception.Message)"
            }
            continue
        }

        if (Test-Path -LiteralPath $auditReport)        { continue }
        if (Test-Path -LiteralPath $pendingFlag)        { continue }

        $finalItem = Get-Item -LiteralPath $finalReport -ErrorAction SilentlyContinue
        if ($null -eq $finalItem)                       { continue }
        if ($finalItem.LastWriteTime -le $cutoff)       { continue }

        $timestamp = (Get-Date).ToString("o")
        $content = "[$timestamp] AR closed sin root-discipline-auditor. Invocar manualmente next session."
        try {
            [System.IO.File]::WriteAllText($pendingFlag, $content, [System.Text.UTF8Encoding]::new($false))
            $flagged++
            Write-DebugLog "flagged: $($ar.Name)"
        } catch {
            Write-DebugLog "write failed $($ar.Name): $($_.Exception.Message)"
        }
    }
} catch {
    Write-DebugLog "scan error: $($_.Exception.Message)"
    exit 0
}

Write-DebugLog "EXIT flagged=$flagged cleaned=$cleaned"
exit 0
