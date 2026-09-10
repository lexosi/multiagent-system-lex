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
      C-proyecto. CLAUDE.md de proyecto (con markers AUTO-CURATED, no user, no "audit"):
         - Write -> BLOCK (zona 3: sobrescribe markers, incluido knowledge-curator)
         - Edit dentro de markers -> ALLOW solo knowledge-curator (zona 1, curada)
         - Edit fuera/cruza markers -> ALLOW (zona 2, doctrina del sistema = root)
         - sin markers / fichero no existe -> passthrough (no lock-out)
      D. Bash/PowerShell con `git *` apuntando a proyectos UEFN (<uefn_root>\*) -> BLOCK
         Proyectos UEFN usan Push Changes interno + save manual <user>. Cero git.
      E. Audit reports independientes (anti-falsificacion, 1:1 rol->archivo):
         - outcome_audit_report.md -> solo lo escribe agent_type "outcome-auditor"
         - process_audit_report.md -> solo lo escribe agent_type "process-auditor"
         - cualquier otro caller (root = agent_type ausente -> <unknown>) -> BLOCK
         Impide self-grading: root NO fabrica su propio verdict de cierre.
         Legacy root_audit_report.md difunto (sin regla, backward-compat lectura only).

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
    "<repo_root>\config\paths.json"
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
    # Force UTF-8 on raw stdin: the caller (Claude Code) pipes UTF-8 JSON, but the
    # ambient console codepage would mangle non-ASCII old_string -> false DENY. Fixes C-usuario AND C-proyecto.
    $stdinRaw = ([System.IO.StreamReader]::new([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)).ReadToEnd()
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
# Proyectos UEFN no usan git. Save = Push Changes interno + manual <user>.
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
                Emit-Deny "Proyectos UEFN en <uefn_root>\* NO usan git. Save = Push Changes (UEFN editor interno) + manual <user>. Comando bloqueado: '$cmd'. Si necesitas inspeccion read-only, usa Read/Glob/Grep en su lugar."
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
    Emit-Deny "Persistence Verse files require explicit Version bump declared in plan.md. Phase 4 does not yet auto-detect approved bumps. Escalate to <user> or update plan.md and request root approval. Path: $absPath"
}

# --- Regla E: anti-falsificacion audit reports (1:1 rol->archivo) ---
# Cada audit report independiente solo lo escribe SU auditor. Impide que root
# (agent_type ausente -> <unknown>) u otro subagent fabrique/edite el verdict.
# agent_type confirmado empirico en el sistema de produccion: "outcome-auditor" / "process-auditor";
# root = campo ausente. Mismo patron de lectura que block-scope-territory.ps1.
# Legacy root_audit_report.md: SIN regla (difunto, backward-compat lectura only).
$agentTypeE = $payload.agent_type
if (-not $agentTypeE) { $agentTypeE = "<unknown>" }   # root = agent_type ausente
$fileNameE = [System.IO.Path]::GetFileName($absPath)

if ($fileNameE -ieq "outcome_audit_report.md") {
    if ($agentTypeE -ne "outcome-auditor") {
        Emit-Deny "outcome_audit_report.md solo lo escribe el subagent 'outcome-auditor' (verdict de RESULTADO independiente). Caller='$agentTypeE' (root/ausente=<unknown>). Self-grading bloqueado: root NO fabrica su propio verdict. Path: $absPath"
    }
}
elseif ($fileNameE -ieq "process_audit_report.md") {
    if ($agentTypeE -ne "process-auditor") {
        Emit-Deny "process_audit_report.md solo lo escribe el subagent 'process-auditor' (verdict de DISCIPLINA de rol independiente). Caller='$agentTypeE' (root/ausente=<unknown>). Self-grading bloqueado: root NO fabrica su propio audit. Path: $absPath"
    }
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
            Emit-Deny "CLAUDE.md Edit attempts to write AUTO-CURATED marker tokens in new_string. Markers must be edited manually by <user> only."
        }

        Write-DebugLog "CLAUDE.md Edit within markers: ALLOW"
        Emit-Allow
    }
}

# --- Regla C-proyecto: CLAUDE.md de proyecto (con zona AUTO-CURATED) ---
# Distinta de Regla C-usuario (arriba, hardcode user path). Aqui: cualquier
# CLAUDE.md que NO sea el de usuario, exista, tenga markers bien formados y NO
# sea un clon/fork de auditoria. DIFERENCIA CLAVE vs C-usuario: la zona FUERA de
# markers (zona 2 = doctrina del sistema) se PERMITE (trabajo legitimo de root),
# mientras C-usuario la DENIEGA. Sin markers -> passthrough (mata lock-out).
$fileNameP = [System.IO.Path]::GetFileName($absPath)
if (($fileNameP -ieq "CLAUDE.md") -and (-not $isClaudeMd) -and (-not $absPath.ToLower().Contains("audit")) -and (Test-Path -LiteralPath $absPath)) {

    $contentP = $null
    try {
        $contentP = Get-Content -LiteralPath $absPath -Raw -Encoding UTF8
    } catch {
        Write-DebugLog "project CLAUDE.md read failed: $($_.Exception.Message); ALLOW (fail-open)"
        Emit-Allow
    }

    # Re-declara localmente los literales de marker (scope C-usuario no alcanza aqui).
    $startMarker = '<!-- AUTO-CURATED:START -->'
    $endMarker   = '<!-- AUTO-CURATED:END -->'
    # Anchored to line-start on purpose: a CLAUDE.md that DOCUMENTS its own marker
    # syntax in prose (as this project's does) defeats first-occurrence IndexOf. Do NOT simplify to IndexOf.
    $mStartP = [regex]::Match($contentP, '(?m)^<!-- AUTO-CURATED:START -->')
    $mEndP   = [regex]::Match($contentP, '(?m)^<!-- AUTO-CURATED:END -->')

    # Solo enforcamos con markers bien formados. Markerless -> passthrough (no lock-out).
    if ($mStartP.Success -and $mEndP.Success -and $mEndP.Index -gt $mStartP.Index) {
        $startIdxP = $mStartP.Index
        $endIdxP   = $mEndP.Index

        $agentTypeP = $payload.agent_type
        if (-not $agentTypeP) { $agentTypeP = "<unknown>" }   # root = agent_type ausente

        if ($toolName -eq "Write") {
            # Zona 3: Write sobrescribe markers -> deny para TODOS, incluido knowledge-curator.
            Emit-Deny "Write to project CLAUDE.md overwrites the entire file including AUTO-CURATED markers (zona 3: deny for everyone, knowledge-curator included). Use Edit restricted to the marker-bounded zone (<!-- AUTO-CURATED:START --> ... <!-- AUTO-CURATED:END -->). Path: $absPath"
        }

        if ($toolName -eq "Edit") {
            $oldStringP = $toolInput.old_string
            $newStringP = $toolInput.new_string

            if ($null -eq $oldStringP) {
                Emit-Deny "Project CLAUDE.md Edit missing old_string parameter. Path: $absPath"
            }

            $oldIdxP = $contentP.IndexOf($oldStringP)
            if ($oldIdxP -lt 0) {
                Emit-Deny "Project CLAUDE.md: old_string not found in file (likely agent bug). Verify the exact content before retry. Path: $absPath"
            }
            $oldEndIdxP = $oldIdxP + $oldStringP.Length

            $minAllowedP = $startIdxP + $startMarker.Length
            $maxAllowedP = $endIdxP

            # new_string no puede introducir marker tokens (intento de extender/mover la
            # zona curada). Aplica a AMBAS zonas -> antes del branching zona 1 / zona 2.
            if ($newStringP -and ($newStringP.Contains($startMarker) -or $newStringP.Contains($endMarker))) {
                Emit-Deny "Project CLAUDE.md Edit attempts to write AUTO-CURATED marker tokens in new_string (attempt to extend/move the curated zone). Path: $absPath"
            }

            if ($oldIdxP -ge $minAllowedP -and $oldEndIdxP -le $maxAllowedP) {
                # Zona 1: DENTRO de markers = conocimiento curado. Solo knowledge-curator.
                if ($agentTypeP -eq "knowledge-curator") {
                    Write-DebugLog "project CLAUDE.md Edit within markers by knowledge-curator: ALLOW"
                    Emit-Allow
                } else {
                    Emit-Deny "Project CLAUDE.md Edit falls inside the AUTO-CURATED zone (zona 1: curated knowledge). Only knowledge-curator may edit between markers. Caller='$agentTypeP' (root/absent=<unknown>). Path: $absPath"
                }
            } else {
                # Zona 2: FUERA o cruza markers = doctrina del sistema (roster, hooks,
                # invariantes, comandos). Trabajo legitimo de root. DIFERENCIA CLAVE vs
                # Regla C-usuario, que en esta misma zona DENIEGA. Aqui se PERMITE.
                Write-DebugLog "project CLAUDE.md Edit outside markers (zona 2, system doctrine): ALLOW"
                Emit-Allow
            }
        }
    }
}

# --- Default: ALLOW ---
Emit-Allow
