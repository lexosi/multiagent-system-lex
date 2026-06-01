<#
.SYNOPSIS
    PreToolUse hook (matcher Write|Edit) — hard-block writes a plan.md de cualquier AR
    si el caller NO es subagent `planner`. Anti-overreach RC1 (AR_2026-05-27_stage1-hardening).

.DESCRIPTION
    Lee stdin JSON de Claude Code v2.1.146. Si tool_input.file_path matchea
    `docs/agent_runs/AR_*/plan.md` (case-insensitive, normalize \ -> /):
      - agent_type == "planner" -> ALLOW + audit log
      - $env:MULTIAGENT_PLAN_MD_OVERRIDE == "1" -> ALLOW + warning + override log
      - otherwise -> DENY (permissionDecision=deny)

    Fail-open: parse errors / missing fields -> ALLOW + stderr warning.
    Razon: hook NO es security boundary, es role discipline; falso-negativo (allow) <<
    falso-positivo (deny correcto workflow).

.NOTES
    Trigger: PreToolUse matcher "Write|Edit"
    Output: exit 0 always + JSON permissionDecision (deny|allow)

    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> log a hooks\.debug.log
    Deny log: SIEMPRE append a hooks\.deny.log (no condicional debug)
    Override log: SIEMPRE append a hooks\.override.log si override usado
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

# Bootstrap: derive $HooksDir from $env:MULTIAGENT_PATHS_CONFIG (override) or PROD default.
# Backward compat: sin env var -> PROD path (F:\multiagent-system\config\paths.json -> repo root -> hooks).
$PathsJson = if ($env:MULTIAGENT_PATHS_CONFIG -and (Test-Path -LiteralPath $env:MULTIAGENT_PATHS_CONFIG)) {
    $env:MULTIAGENT_PATHS_CONFIG
} else {
    "F:\multiagent-system\config\paths.json"
}

$RepoRoot   = Split-Path -Parent (Split-Path -Parent $PathsJson)
$HooksDir   = Join-Path $RepoRoot "hooks"
$DebugMode  = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"
$OverrideOn = $env:MULTIAGENT_PLAN_MD_OVERRIDE -eq "1"

function Write-DebugLog($msg) {
    if ($DebugMode) {
        $logPath = Join-Path $HooksDir ".debug.log"
        $ts = (Get-Date).ToString("o")
        try { Add-Content -Path $logPath -Value "[$ts] [pretooluse-block-plan-md-non-planner.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
    }
}

function Write-DenyLog($agentType, $filePath, $reason) {
    $logPath = Join-Path $HooksDir ".deny.log"
    $ts = (Get-Date).ToString("o")
    try { Add-Content -Path $logPath -Value "[$ts] DENY agent=$agentType file=$filePath reason=$reason" -ErrorAction SilentlyContinue } catch {}
}

function Write-OverrideLog($agentType, $filePath) {
    $logPath = Join-Path $HooksDir ".override.log"
    $ts = (Get-Date).ToString("o")
    try { Add-Content -Path $logPath -Value "[$ts] OVERRIDE agent=$agentType file=$filePath env=MULTIAGENT_PLAN_MD_OVERRIDE=1" -ErrorAction SilentlyContinue } catch {}
}

function Emit-Allow() {
    $payload = @{
        hookSpecificOutput = @{
            hookEventName      = "PreToolUse"
            permissionDecision = "allow"
        }
    }
    $json = $payload | ConvertTo-Json -Depth 5 -Compress
    [Console]::Out.Write($json)
    exit 0
}

function Emit-Deny($reason) {
    $payload = @{
        hookSpecificOutput = @{
            hookEventName            = "PreToolUse"
            permissionDecision       = "deny"
            permissionDecisionReason = $reason
        }
    }
    $json = $payload | ConvertTo-Json -Depth 5 -Compress
    [Console]::Out.Write($json)
    exit 0
}

function Emit-PassThrough() {
    # No file_path match o tool fuera de scope -> ALLOW sin overhead
    exit 0
}

# --- 1. Leer stdin (fail-open) ---
$stdinRaw = ""
try { $stdinRaw = [Console]::In.ReadToEnd() } catch {
    [Console]::Error.WriteLine("[pretooluse-block-plan-md-non-planner] stdin read failed; fail-open ALLOW")
    Emit-PassThrough
}
if ([string]::IsNullOrWhiteSpace($stdinRaw)) { Emit-PassThrough }

$payload = $null
try { $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop } catch {
    [Console]::Error.WriteLine("[pretooluse-block-plan-md-non-planner] stdin not JSON; fail-open ALLOW")
    Emit-PassThrough
}

$toolName  = $payload.tool_name
$toolInput = $payload.tool_input
$agentType = $payload.agent_type
if (-not $agentType) { $agentType = "<unknown>" }

if (-not $toolName -or -not $toolInput) { Emit-PassThrough }

# --- 2. Scope filter: solo Write|Edit ---
if ($toolName -ne "Write" -and $toolName -ne "Edit") { Emit-PassThrough }

$filePath = $toolInput.file_path
if ([string]::IsNullOrWhiteSpace($filePath)) { Emit-PassThrough }

# --- 3. Regex match plan.md AR ---
$normalized = $filePath -replace '\\', '/'
if ($normalized -notmatch '(?i)docs/agent_runs/AR_[^/]+/plan\.md$') { Emit-PassThrough }

Write-DebugLog "MATCH agent=$agentType file=$filePath override=$OverrideOn"

# --- 4. Decision ---
if ($agentType -eq "planner") {
    Write-DebugLog "ALLOW planner legitimate"
    Emit-Allow
}

if ($OverrideOn) {
    Write-OverrideLog $agentType $filePath
    [Console]::Error.WriteLine("[pretooluse-block-plan-md-non-planner] OVERRIDE active (MULTIAGENT_PLAN_MD_OVERRIDE=1): allowing plan.md write by agent=$agentType. Audit: hooks/.override.log")
    Emit-Allow
}

$denyReason = "Block: plan.md writes restricted to ``planner`` subagent (anti-overreach RC1, AR_2026-05-27_stage1-hardening). Caller=$agentType. Override: `$env:MULTIAGENT_PLAN_MD_OVERRIDE=1` for legitimate edge cases. Verbatim CLAUDE.md regla: root invoca planner para plan.md, no Edit/Write directo."
Write-DenyLog $agentType $filePath "non-planner caller"
Emit-Deny $denyReason
