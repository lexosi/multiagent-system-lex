<#
.SYNOPSIS
    PreToolUse hook (matcher Edit|Write) — advisory warning root scope creep cuando root edita
    archivos role-appropriate subagent. NO bloqueante.
    Pattern paralelo B3 pretooluse-verse-kb-advisory.ps1.

.DESCRIPTION
    Lee stdin JSON CC. Evalua tool_input.file_path contra patterns role-appropriate subagent.

    Match patterns role-appropriate (sin excepcion):
      - .verse$ OR Content/Verse/        -> specialist-verse
      - agent_templates/*.md OR
        .claude/agents/*.md              -> implementer (flujo formal post-planner)
      - docs/agent_runs/AR_*/plan.md
        OR steps.md                      -> planner
      - docs/agent_runs/AR_*/hypotheses.md -> hypothesis_tracker (Python wrapper)
      - docs/agent_runs/AR_*/curator_report.md -> knowledge-curator

    Excepciones legitimas (silent, NO warning):
      - docs/agent_runs/AR_*/final_report.md   (root reporting)
      - docs/rebuild_b_*.md                    (root reporting)
      - F:/multiagent-system/config/*.json     (infra configuration)

    Si match patron sin excepcion -> emit additionalContext warning + exit 0.
    Si match patron con excepcion -> silent exit 0.
    Si no match -> silent exit 0.

    Contract: NUNCA bloquea (exit 0 siempre). Solo advisory.
    Defense-in-depth secundario — primary mechanism es CLAUDE.md constraints
    + root-discipline-auditor post-AR audit.

.NOTES
    Trigger: PreToolUse matcher "Edit|Write"
    Output: exit 0 + JSON hookSpecificOutput.additionalContext (warning) o silent

    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> log a hooks\.debug.log

    Cross-ref: AR_2026-05-21_B5-scope-advisory-real-smoke-b2 Step 1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

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
        $timestamp = (Get-Date).ToString("o")
        try { Add-Content -Path $DebugLogPath -Value "[$timestamp] [pretooluse-root-scope-advisory.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
    }
}

# --- Helpers output ---
function Emit-Advisory($message) {
    $payload = @{
        hookSpecificOutput = @{
            hookEventName     = "PreToolUse"
            additionalContext = $message
        }
    }
    $json = $payload | ConvertTo-Json -Depth 5 -Compress
    [Console]::Out.WriteLine($json)
    Write-DebugLog "ADVISORY: $message"
    exit 0
}

function Emit-Silent() {
    Write-DebugLog "SILENT (no match or exception applies)"
    exit 0
}

# --- 1. Leer stdin ---
$stdinRaw = ""
try {
    $stdinRaw = [Console]::In.ReadToEnd()
} catch {
    Write-DebugLog "stdin read failed: $($_.Exception.Message); SILENT (fail-open)"
    Emit-Silent
}
if ([string]::IsNullOrWhiteSpace($stdinRaw)) {
    Write-DebugLog "empty stdin; SILENT (fail-open)"
    Emit-Silent
}

# --- 2. Parse JSON ---
$payload = $null
try {
    $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-DebugLog "JSON parse failed: $($_.Exception.Message); emit generic advisory"
    Emit-Advisory "[ADVISORY] pretooluse-root-scope-advisory: stdin payload no parseable. Verifica hook config si root scope creep no detectado runtime."
}

# --- 3. Extract tool_name + file_path ---
$toolName = $null
$filePath = $null
try {
    $toolName = $payload.tool_name
    $filePath = $payload.tool_input.file_path
} catch {
    Write-DebugLog "payload missing tool_name/file_path; SILENT"
    Emit-Silent
}

if ([string]::IsNullOrWhiteSpace($toolName) -or [string]::IsNullOrWhiteSpace($filePath)) {
    Write-DebugLog "tool_name or file_path empty; SILENT"
    Emit-Silent
}

# --- 4. Filter Edit|Write only ---
$isEditOrWrite = $toolName -eq "Edit" -or $toolName -eq "Write"
if (-not $isEditOrWrite) {
    Write-DebugLog "tool_name '$toolName' not Edit/Write; SILENT"
    Emit-Silent
}

# Normalize path separators (Windows uses \, regex friendlier with /)
$normalizedPath = $filePath -replace '\\', '/'

# --- 5. Check excepciones legitimas (silent) ---
$isFinalReport = $normalizedPath -match 'docs/agent_runs/AR_[^/]+/final_report\.md$'
$isRebuildDoc = $normalizedPath -match 'docs/rebuild_b_[^/]+\.md$'
$isConfigJson = $normalizedPath -match '/multiagent-system/config/[^/]+\.json$'

if ($isFinalReport -or $isRebuildDoc -or $isConfigJson) {
    Write-DebugLog "exception applies (final_report/rebuild_b/config); SILENT"
    Emit-Silent
}

# --- 6. Pattern match role-appropriate subagent ---
$matchedAgent = $null
$matchReason = $null

if ($normalizedPath -match '\.verse$' -or $normalizedPath -match 'Content/Verse/') {
    $matchedAgent = "specialist-verse"
    $matchReason = "Verse code touched (.verse extension or Content/Verse/ path)"
}
elseif ($normalizedPath -match 'agent_templates/[^/]+\.md$' -or $normalizedPath -match '\.claude/agents/[^/]+\.md$') {
    $matchedAgent = "implementer (flujo formal post-planner)"
    $matchReason = "Agent template/mirror edit (agent_templates/*.md or .claude/agents/*.md)"
}
elseif ($normalizedPath -match 'docs/agent_runs/AR_[^/]+/(plan|steps)\.md$') {
    $matchedAgent = "planner"
    $matchReason = "AR plan.md/steps.md edit (docs/agent_runs/AR_*/plan|steps.md)"
}
elseif ($normalizedPath -match 'docs/agent_runs/AR_[^/]+/hypotheses\.md$') {
    $matchedAgent = "hypothesis_tracker (Python wrapper)"
    $matchReason = "AR hypotheses.md edit (docs/agent_runs/AR_*/hypotheses.md)"
}
elseif ($normalizedPath -match 'docs/agent_runs/AR_[^/]+/curator_report\.md$') {
    $matchedAgent = "knowledge-curator"
    $matchReason = "AR curator_report.md edit (docs/agent_runs/AR_*/curator_report.md)"
}

if (-not $matchedAgent) {
    Write-DebugLog "no pattern match; SILENT"
    Emit-Silent
}

# --- 7. Match sin excepcion -> emit advisory warning ---
$warning = "[ADVISORY] Root scope creep posible. file_path='$filePath' match patron role-appropriate subagent '$matchedAgent'. Razon: $matchReason. Considera invocar '$matchedAgent' via Task tool en lugar de root direct Edit/Write. Si root edit intencional (system maintenance / reporting / config) -> ignora warning. Hook secondary advisory NO bloqueante."
Emit-Advisory $warning
