<#
.SYNOPSIS
    Stop hook reactivo — detecta ARs cerrados (final_report.md mtime <2h)
    a los que les falta ALGUNO de los dos audit reports INDEPENDIENTES
    (outcome_audit_report.md / process_audit_report.md), escribe flag
    .auditor_pending en el AR dir para invocacion manual next session.

.DESCRIPTION
    Pattern paralelo a stop-knowledge-curator.ps1 (curator pending detection)
    pero per-AR flag file (NO archivo agregado global).

    Trigger: Stop event (cada turn end CC v2.1.146).
    Scan: AR_*/final_report.md mtime ultimas 2h.

    Independencia de juicio: un AR cerrado
    requiere DOS veredictos de agentes INDEPENDIENTES del ejecutor (root):
      - outcome_audit_report.md  (verdict de RESULTADO, emite outcome-auditor)
      - process_audit_report.md  (disciplina de rol, emite process-auditor)
    Backward-compat: el legacy root_audit_report.md cuenta como process satisfecho
    (ARs viejos no se re-auditan). Si existe el legacy, process NO se marca pendiente.

    Per AR: si falta CUALQUIERA de los dos audits requeridos Y NO existe
    .auditor_pending, escribe .auditor_pending con:
      - linea 0  : mensaje legacy human-readable (timestamp + que falta)
      - missing= : que audits faltan (outcome / process / outcome,process)
      - transcript_path= : path absoluto del transcript main-thread (.jsonl),
        extraido del payload stdin del Stop hook. Mecanismo anti-sesgo (D3):
        SessionStart lo inyecta y root lo relé VERBATIM al auditor (root NO
        inventa el path). Si el payload no trae transcript_path -> campo vacio
        + warning a stderr (fail-open, NO aborta).

    NO touch settings.json (registracion separada step 7).
    NO touch otros archivos AR.

.NOTES
    Exit 0 SIEMPRE (Stop hook contract).
    Errores -> trap + debug log + warning a stderr (NUNCA throw / exit != 0).
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
    "<repo_root>\config\paths.json"
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

# --- Consume stdin + extraer transcript_path del payload (D3) ---
# El payload stdin del Stop hook es JSON e incluye transcript_path (path absoluto
# del transcript main-thread .jsonl). Fail-open: si no parsea o no esta presente,
# $TranscriptPath queda "" + warning (NO aborta).
$TranscriptPath = ""
try {
    $stdinRaw = [Console]::In.ReadToEnd()
    if ($stdinRaw -and $stdinRaw.Trim().Length -gt 0) {
        $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop
        if ($payload.transcript_path) {
            $TranscriptPath = [string]$payload.transcript_path
        }
    }
} catch {
    Write-DebugLog "stdin parse failed (fail-open, transcript_path vacio): $($_.Exception.Message)"
}
if ([string]::IsNullOrWhiteSpace($TranscriptPath)) {
    [Console]::Error.WriteLine("[stop-no-auditor.ps1] WARN: transcript_path ausente en payload stdin; flag se escribira sin path (auditor lo resolvera por session_id).")
    Write-DebugLog "transcript_path ausente en payload"
} else {
    Write-DebugLog "transcript_path resuelto: $TranscriptPath"
}

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
        $finalReport    = Join-Path $ar.FullName "final_report.md"
        $outcomeReport  = Join-Path $ar.FullName "outcome_audit_report.md"
        $processReport  = Join-Path $ar.FullName "process_audit_report.md"
        $legacyReport   = Join-Path $ar.FullName "root_audit_report.md"
        $pendingFlag    = Join-Path $ar.FullName ".auditor_pending"

        if (-not (Test-Path -LiteralPath $finalReport)) { continue }

        # Determinar que audits INDEPENDIENTES faltan.
        #   outcome -> outcome_audit_report.md
        #   process -> process_audit_report.md  (legacy root_audit_report.md cuenta como satisfecho)
        $missing = @()
        if (-not (Test-Path -LiteralPath $outcomeReport)) { $missing += "outcome" }
        if (-not ((Test-Path -LiteralPath $processReport) -or (Test-Path -LiteralPath $legacyReport))) { $missing += "process" }

        # Cleanup orphan flag: ambos audits satisfechos -> remove stale .auditor_pending
        if ($missing.Count -eq 0) {
            if (Test-Path -LiteralPath $pendingFlag) {
                try {
                    Remove-Item -LiteralPath $pendingFlag -Force -ErrorAction SilentlyContinue
                    $cleaned++
                    Write-DebugLog "cleanup: .auditor_pending removed (outcome+process satisfechos) in $($ar.Name)"
                } catch {
                    Write-DebugLog "cleanup failed $($ar.Name): $($_.Exception.Message)"
                }
            }
            continue
        }

        # Falta algun audit: si ya hay flag, no re-escribir (one-shot).
        if (Test-Path -LiteralPath $pendingFlag)        { continue }

        $finalItem = Get-Item -LiteralPath $finalReport -ErrorAction SilentlyContinue
        if ($null -eq $finalItem)                       { continue }
        if ($finalItem.LastWriteTime -le $cutoff)       { continue }

        $timestamp   = (Get-Date).ToString("o")
        $missingCsv  = $missing -join ","
        # Formato KV multilinea (retrocompat: linea 0 = mensaje legacy human-readable).
        # SessionStart (step 6) parsea missing= y transcript_path=.
        $lines = @(
            "[$timestamp] AR closed sin audit independiente (falta: $missingCsv). Invocar auditor(es) next session.",
            "missing=$missingCsv",
            "transcript_path=$TranscriptPath"
        )
        $content = ($lines -join "`n") + "`n"
        try {
            [System.IO.File]::WriteAllText($pendingFlag, $content, [System.Text.UTF8Encoding]::new($false))
            $flagged++
            Write-DebugLog "flagged: $($ar.Name) (missing=$missingCsv, transcript_path='$TranscriptPath')"
        } catch {
            [Console]::Error.WriteLine("[stop-no-auditor.ps1] WARN: write .auditor_pending fallo en $($ar.Name): $($_.Exception.Message)")
            Write-DebugLog "write failed $($ar.Name): $($_.Exception.Message)"
        }
    }
} catch {
    Write-DebugLog "scan error: $($_.Exception.Message)"
    exit 0
}

Write-DebugLog "EXIT flagged=$flagged cleaned=$cleaned"
exit 0
