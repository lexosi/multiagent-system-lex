<#
.SYNOPSIS
    PreToolUse hook (matcher Agent|Task) — captura runtime subagent invocations.
    Append entry a <metrics_dir>\_pending_turn_tasks.jsonl per Task tool call.
    Stop hook (stop-capture-skills-token-tax.ps1) consume + aggregates + clears.

.DESCRIPTION
    Refinement Fase 5.1 (AR_2026-05-28_p5-hybrid-fase5-1-dynamic-per-task).
    Resuelve caveat MVP Fase 5: Stop payload NO expone lista subagents Task-invocados
    este turn. Capture-on-PreToolUse + consume-on-Stop pattern (Opción C combined).

    Lee stdin JSON CC v2.1.146:
      tool_name in ("Agent","Task")
      tool_input.subagent_type
      tool_input.description (truncated 80)
      session_id

    Append JSONL entry: {ts, session_id, subagent_type, description}

    Fail-open SIEMPRE: trap global + try/catch. Cualquier error -> exit 0 + stderr warning.
    Pass-through ALLOW (sin permission output) en happy path.

.NOTES
    Trigger: PreToolUse matcher "Task"
    Exit code: 0 SIEMPRE
    Encoding: UTF-8 sin BOM via [System.IO.File]::AppendAllText + UTF8Encoding(false)

    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> hooks\.debug.log
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
trap { exit 0 }

# --- Bootstrap: resolver paths.json + repo root con env var override ---
$PathsJson = if ($env:MULTIAGENT_PATHS_CONFIG -and (Test-Path -LiteralPath $env:MULTIAGENT_PATHS_CONFIG)) {
    $env:MULTIAGENT_PATHS_CONFIG
} else {
    "<repo_root>\config\paths.json"  # default PROD fallback
}
$RepoRoot        = Split-Path -Parent (Split-Path -Parent $PathsJson)
$MetricsFallback = Join-Path $RepoRoot ".metrics"
$DebugMode       = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"

function Write-DebugLog($msg) {
    if (-not $DebugMode) { return }
    try {
        $logPath = Join-Path $RepoRoot "hooks\.debug.log"
        $ts = (Get-Date).ToString("o")
        Add-Content -Path $logPath -Value "[$ts] [pretooluse-capture-task-invocation.ps1] $msg" -ErrorAction SilentlyContinue
    } catch {}
}

# --- 1. Leer stdin (fail-open) ---
$stdinRaw = ""
try { $stdinRaw = [Console]::In.ReadToEnd() } catch {
    [Console]::Error.WriteLine("[pretooluse-capture-task-invocation] stdin read failed; fail-open exit 0")
    exit 0
}
if ([string]::IsNullOrWhiteSpace($stdinRaw)) { exit 0 }

$payload = $null
try { $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop } catch {
    [Console]::Error.WriteLine("[pretooluse-capture-task-invocation] stdin not JSON; fail-open exit 0")
    exit 0
}

# --- 2. Scope filter: solo Task ---
if ($payload.tool_name -ne "Agent" -and $payload.tool_name -ne "Task") { exit 0 }

$toolInput = $payload.tool_input
if (-not $toolInput) { exit 0 }

$subagentType = $toolInput.subagent_type
if ([string]::IsNullOrWhiteSpace($subagentType)) {
    Write-DebugLog "Task without subagent_type; skip"
    exit 0
}

$description = ""
if ($toolInput.description) {
    $description = [string]$toolInput.description
    if ($description.Length -gt 80) { $description = $description.Substring(0, 80) }
}

$sessionId = ""
if ($payload.session_id) { $sessionId = [string]$payload.session_id }

$agentId = ""
if ($payload.agentId) { $agentId = [string]$payload.agentId } elseif ($payload.agent_id) { $agentId = [string]$payload.agent_id }

$toolUseId = ""
if ($payload.tool_use_id) { $toolUseId = [string]$payload.tool_use_id }

# --- 3. Resolver metrics_dir (paths.json -> fallback) ---
$MetricsDir = $MetricsFallback
try {
    if (Test-Path -LiteralPath $PathsJson) {
        $raw = [System.IO.File]::ReadAllText($PathsJson)
        $cfg = $raw | ConvertFrom-Json -ErrorAction Stop
        if ($cfg.state_files -and $cfg.state_files.metrics_dir) {
            $MetricsDir = $cfg.state_files.metrics_dir
        }
    }
} catch {
    Write-DebugLog "paths.json parse fail: $($_.Exception.Message) -> fallback"
}

try {
    if (-not (Test-Path -LiteralPath $MetricsDir)) {
        New-Item -ItemType Directory -Force -Path $MetricsDir -ErrorAction Stop | Out-Null
    }
} catch {
    Write-DebugLog "metrics_dir create fail: $($_.Exception.Message)"
    exit 0
}

$OutFile = Join-Path $MetricsDir "_pending_turn_tasks.jsonl"

# --- 4. Append JSONL entry ---
try {
    $entry = [PSCustomObject]@{
        ts             = (Get-Date).ToString("o")
        session_id     = $sessionId
        subagent_type  = $subagentType
        description    = $description
        agentId        = $agentId
        tool_use_id    = $toolUseId
    }
    $json = $entry | ConvertTo-Json -Depth 3 -Compress
    [System.IO.File]::AppendAllText($OutFile, ($json + "`n"), [System.Text.UTF8Encoding]::new($false))
    Write-DebugLog "captured subagent=$subagentType session=$sessionId"
} catch {
    Write-DebugLog "append fail: $($_.Exception.Message)"
    [Console]::Error.WriteLine("[pretooluse-capture-task-invocation] append fail (fail-open): $($_.Exception.Message)")
}

exit 0
