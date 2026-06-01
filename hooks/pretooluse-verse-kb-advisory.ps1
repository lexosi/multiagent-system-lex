<#
.SYNOPSIS
    PreToolUse hook (matcher Edit|Write) — advisory warning cuando agente toca codigo Verse.
    Emite warning recordando KB Read auto pre-task (tier_1_always: VERSE_SYNTAX_GUIDE.md +
    verse-domain-rules.md + KB_GAPS.md). NO bloqueante.

.DESCRIPTION
    Lee stdin JSON de Claude Code, evalua tool_name + tool_input.file_path.

    Pattern match (simplificado B3 — cero detection session state):
      Si tool_name in ["Edit","Write"] AND tool_input.file_path match
      (.verse$ OR Content/Verse/) -> emit warning via additionalContext + exit 0.
      Si NO match -> silent exit 0.

    Contract: NUNCA bloquea (no permissionDecision="deny"). Solo advisory.
    Defense-in-depth secundario — primary mechanism es specialist-verse template
    instruction "KB Read auto pre-task" (Gap 4 B3).

.NOTES
    Trigger: PreToolUse matcher "Edit|Write"
    Output: exit 0 + JSON hookSpecificOutput.additionalContext (warning) o silent

    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> log a hooks\.debug.log

    Cross-ref: AR_2026-05-20_B3-kb-verse-uefn-consulta-automatica Step 6
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

# --- Bootstrap paths discovery (env var override -> default PROD) ---
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
        try { Add-Content -Path $DebugLogPath -Value "[$timestamp] [pretooluse-verse-kb-advisory.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
    }
}

# --- Helpers de output ---
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
    Write-DebugLog "SILENT (no match)"
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

# --- 2. Parse JSON payload ---
$payload = $null
try {
    $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop
} catch {
    # Silent-failure -> loud-failure guard: emit warning generic + exit 0 (no block)
    Write-DebugLog "JSON parse failed: $($_.Exception.Message); emit generic advisory"
    Emit-Advisory "[ADVISORY] pretooluse-verse-kb-advisory: stdin payload no parseable. Verifica hook config si Verse code touched sin advisory esperada."
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

# --- 4. Pattern match: Edit|Write + (.verse$ OR Content/Verse/) ---
$isEditOrWrite = $toolName -eq "Edit" -or $toolName -eq "Write"
if (-not $isEditOrWrite) {
    Write-DebugLog "tool_name '$toolName' not Edit/Write; SILENT"
    Emit-Silent
}

# Normalize path separators for match (Windows uses \, regex friendlier with /)
$normalizedPath = $filePath -replace '\\', '/'

$isVerseExtension = $normalizedPath -match '\.verse$'
$isVerseContentPath = $normalizedPath -match 'Content/Verse/'

if (-not ($isVerseExtension -or $isVerseContentPath)) {
    Write-DebugLog "file_path '$filePath' not Verse (no .verse$ or Content/Verse/); SILENT"
    Emit-Silent
}

# --- 5. Match -> emit advisory warning ---
$warning = "[ADVISORY] Verse code touched. Reminder: ensure tier_1_always KB (VERSE_SYNTAX_GUIDE.md + verse-domain-rules.md + KB_GAPS.md) read before reasoning. specialist-verse template Read auto primary. This hook = secondary advisory."
Emit-Advisory $warning
