<#
.SYNOPSIS
    PreToolUse hook (matcher Edit|Write) — bloquea writes a archivos protegidos:
    .git/, CLAUDE.md fuera de markers AUTO-CURATED, persistence Verse files.

.DESCRIPTION
    Lee stdin JSON de Claude Code, evalua tool_name + tool_input.file_path
    contra reglas de proteccion. Devuelve permissionDecision deny si viola.

    Reglas:
      A. .git/ (cualquier path) -> BLOCK absoluto
      B. Persistence Verse files (Content\Verse\Core\*Persistence*.verse) -> BLOCK
      C. CLAUDE.md user-global:
         - Write -> BLOCK absoluto (sobrescribe markers)
         - Edit:
            * old_string no encontrado -> BLOCK (bug de agente, hint markers)
            * markers AUTO-CURATED no existen -> BLOCK
            * old_string cae fuera o cruza markers -> BLOCK
            * old_string integro dentro de markers -> ALLOW
      D. Bash/PowerShell con `git *` apuntando a proyectos UEFN (<uefn_root>\*) -> BLOCK
         Proyectos UEFN usan Push Changes interno + save manual Lexosi. Cero git.

.NOTES
    Trigger: PreToolUse matcher "Edit|Write|Bash|PowerShell"
    Output: exit 0 + JSON permissionDecision (deny|allow|defer)

    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> log a hooks\.debug.log
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

# --- Bootstrap paths (env override -> repo root -> debug log) ---
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
        try { Add-Content -Path $logPath -Value "[$timestamp] [pretooluse-guard-protected-files.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
    }
}

# --- Helpers de output ---
function Emit-Deny($reason) {
    $payload = @{
        hookSpecificOutput = @{
            hookEventName            = "PreToolUse"
            permissionDecision       = "deny"
            permissionDecisionReason = $reason
        }
    }
    $json = $payload | ConvertTo-Json -Depth 5 -Compress
    [Console]::Out.WriteLine($json)
    Write-DebugLog "DENY: $reason"
    exit 0
}

function Emit-Allow() {
    Write-DebugLog "ALLOW"
    exit 0
}

# --- 1. Leer stdin ---
$stdinRaw = ""
try {
    $stdinRaw = [Console]::In.ReadToEnd()
} catch {
    Write-DebugLog "stdin read failed: $($_.Exception.Message); ALLOW (fail-open)"
    Emit-Allow
}
if ([string]::IsNullOrWhiteSpace($stdinRaw)) {
    Write-DebugLog "empty stdin; ALLOW (fail-open)"
    Emit-Allow
}

$payload = $null
try {
    $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-DebugLog "stdin not JSON: $($_.Exception.Message); ALLOW (fail-open)"
    Emit-Allow
}

$toolName  = $payload.tool_name
$toolInput = $payload.tool_input
$cwd       = $payload.cwd

if (-not $toolName -or -not $toolInput) {
    Write-DebugLog "missing tool_name or tool_input; ALLOW (fail-open)"
    Emit-Allow
}

Write-DebugLog "ENTRY tool=$toolName cwd=$cwd"

# --- Regla D: Bash/PowerShell con `git *` sobre <uefn_root>\* ---
# Proyectos UEFN no usan git. Save = Push Changes interno + manual Lexosi.
if ($toolName -eq "Bash" -or $toolName -eq "PowerShell") {
    $cmd = $toolInput.command
    if (-not [string]::IsNullOrWhiteSpace($cmd)) {
        $cmdLower = $cmd.ToLower()
        # Detecta `git ` o `git\` o inicio `git ` como subcomando.
        # Patron: git como primera palabra O tras `;`, `&&`, `||`, `|`, `\n`, ` (`
        $isGitCmd = $cmdLower -match '(^|\s|;|&&|\|\|)git\s' -or $cmdLower -match '(^|\s|;|&&|\|\|)git\.exe\s'

        if ($isGitCmd) {
            # Path bajo <uefn_root>\ (cualquier separador)
            $targetsUefn = $cmdLower -match 'f:[\\/]+uefnprojects[\\/]'
            # O cwd inicia bajo <uefn_root>\
            $cwdLower = ""
            if (-not [string]::IsNullOrWhiteSpace($cwd)) { $cwdLower = $cwd.ToLower() }
            $cwdInUefn = $cwdLower -match '^f:[\\/]+uefnprojects[\\/]' -or $cwdLower -match '^/f/uefnprojects/' -or $cwdLower -match '^/mnt/f/uefnprojects/'

            if ($targetsUefn -or $cwdInUefn) {
                Emit-Deny "Proyectos UEFN en <uefn_root>\* NO usan git. Save = Push Changes (UEFN editor interno) + manual Lexosi. Comando bloqueado: '$cmd'. Si necesitas inspeccion read-only, usa Read/Glob/Grep en su lugar."
            }
        }
    }
}

# --- 2. Resolver file_path absoluto ---
$filePath = $toolInput.file_path
if ([string]::IsNullOrWhiteSpace($filePath)) {
    Write-DebugLog "no file_path in tool_input; ALLOW"
    Emit-Allow
}

# Resolver relative -> absolute usando cwd
$absPath = $filePath
if (-not [System.IO.Path]::IsPathRooted($filePath)) {
    if (-not [string]::IsNullOrWhiteSpace($cwd)) {
        try { $absPath = [System.IO.Path]::GetFullPath((Join-Path $cwd $filePath)) } catch {}
    }
} else {
    try { $absPath = [System.IO.Path]::GetFullPath($filePath) } catch {}
}
Write-DebugLog "absPath=$absPath"

# --- Regla A: .git/ (cualquier path) ---
if ($absPath -match '\\\.git\\') {
    Emit-Deny "Files inside .git/ are protected. Path: $absPath"
}

# --- Regla B: Persistence Verse files ---
if ($absPath -match '(?i)Content\\Verse\\Core\\[^\\]*Persistence[^\\]*\.verse$') {
    Emit-Deny "Persistence Verse files require explicit Version bump declared in plan.md. Phase 4 does not yet auto-detect approved bumps. Escalate to Lexosi or update plan.md and request root approval. Path: $absPath"
}

# --- Regla C: CLAUDE.md user-global ---
$claudeMdPath = "$env:USERPROFILE\.claude\CLAUDE.md"
$isClaudeMd = ($absPath -ieq $claudeMdPath)

if ($isClaudeMd) {
    if ($toolName -eq "Write") {
        Emit-Deny "Write to CLAUDE.md overwrites entire file including AUTO-CURATED markers. Use Edit restricted to the marker-bounded zone (<!-- AUTO-CURATED:START --> ... <!-- AUTO-CURATED:END -->)."
    }

    if ($toolName -eq "Edit") {
        if (-not (Test-Path -LiteralPath $claudeMdPath)) {
            Write-DebugLog "CLAUDE.md does not exist; ALLOW (Edit will fail natively)"
            Emit-Allow
        }

        $oldString = $toolInput.old_string
        $newString = $toolInput.new_string

        if ($null -eq $oldString) {
            Emit-Deny "CLAUDE.md Edit missing old_string parameter."
        }

        $content = ""
        try {
            $content = Get-Content -LiteralPath $claudeMdPath -Raw -Encoding UTF8
        } catch {
            Write-DebugLog "CLAUDE.md read failed: $($_.Exception.Message); ALLOW (fail-open)"
            Emit-Allow
        }

        # Localizar markers
        $startMarker = '<!-- AUTO-CURATED:START -->'
        $endMarker   = '<!-- AUTO-CURATED:END -->'
        $startIdx = $content.IndexOf($startMarker)
        $endIdx   = $content.IndexOf($endMarker)
        if ($startIdx -lt 0 -or $endIdx -lt 0 -or $endIdx -le $startIdx) {
            Emit-Deny "CLAUDE.md missing AUTO-CURATED markers (or malformed). Required: '<!-- AUTO-CURATED:START -->' ... '<!-- AUTO-CURATED:END -->'. Cannot determine safe edit zone."
        }

        # Localizar old_string en el archivo (primera ocurrencia exacta)
        $oldIdx = $content.IndexOf($oldString)
        if ($oldIdx -lt 0) {
            Emit-Deny "CLAUDE.md: old_string not found in file. Verify the exact content before retry. Hint: the file has markers <!-- AUTO-CURATED:START/END --> defining the only writable zone (lines $($content.Substring(0,$startIdx).Split([char]10).Length)..$($content.Substring(0,$endIdx).Split([char]10).Length))."
        }
        $oldEndIdx = $oldIdx + $oldString.Length

        # Verificar integridad: oldIdx > startIdx + len(startMarker) AND oldEndIdx < endIdx
        $minAllowed = $startIdx + $startMarker.Length
        $maxAllowed = $endIdx
        if ($oldIdx -lt $minAllowed -or $oldEndIdx -gt $maxAllowed) {
            $oldStartLine = ($content.Substring(0, $oldIdx).Split([char]10)).Length
            $oldEndLine   = ($content.Substring(0, $oldEndIdx).Split([char]10)).Length
            $startLine    = ($content.Substring(0, $startIdx).Split([char]10)).Length
            $endLine      = ($content.Substring(0, $endIdx).Split([char]10)).Length
            Emit-Deny "CLAUDE.md Edit crosses or falls outside AUTO-CURATED zone. Edit covers lines ${oldStartLine}..${oldEndLine}; safe zone is lines ${startLine}..${endLine}. Only knowledge-curator may edit between markers, and only within them."
        }

        # Verificar que new_string no introduce markers nuevos (intento de extender zona)
        if ($newString -and ($newString.Contains($startMarker) -or $newString.Contains($endMarker))) {
            Emit-Deny "CLAUDE.md Edit attempts to write AUTO-CURATED marker tokens in new_string. Markers must be edited manually by Lexosi only."
        }

        Write-DebugLog "CLAUDE.md Edit within markers: ALLOW"
        Emit-Allow
    }
}

# --- Default: ALLOW ---
Emit-Allow
