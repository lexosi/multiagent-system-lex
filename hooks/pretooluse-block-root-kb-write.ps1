<#
.SYNOPSIS
    PreToolUse hook (matcher Write|Edit) - hard-block escrituras a la KB
    (knowledge base) por parte de root o subagents no-curator. agent_type-aware.
    Territorio unico = knowledge base (paths.json `knowledge_base` -> default
    <knowledge_root>, archivos `.md`). Enforce QUIEN+DONDE, no contenido. Override
    sentinel-file root one-shot TTL 1h (mismo mecanismo que
    pretooluse-block-scope-territory.ps1). Cross-ref AR_2026-06-27_system-redesign
    (redisenio Fase 1, C2 / anillo KB) + c2_signal_probe.md.

.DESCRIPTION
    Lee stdin JSON de Claude Code v2.1.146. Discrimina al caller por `agent_type`
    (string exacto del subagent; AUSENTE -> root). Defensa role-discipline, NO
    security boundary. El proposito: root NO debe escribir la KB de su creencia;
    solo `knowledge-curator` cura la KB (los specialists NO la curan).

    Flujo (orden importa):
      1. read stdin -> parse JSON. Fallo o vacio -> fail-open ALLOW (passthrough).
      2. filter tool_name in {Write, Edit}; otro -> passthrough (exit 0 sin JSON).
      3. resolver KB root: $env:MULTIAGENT_PATHS_CONFIG (override) o PROD default
         -> leer key `knowledge_base` del JSON -> fallback <knowledge_root> si falla.
         Normalizar a forward-slash lowercase.
      4. normalizar file_path: \ -> /, lowercase, trim.
      5. Match territorio KB: file_path bajo la raiz KB anclada Y termina en `.md`.
         Ancla via [regex]::Escape sobre raiz normalizada (NO substring 'knowledge'
         suelto: evita falso match a <repo_root>\knowledge\...). No-match
         -> passthrough.
      6. Territorio KB bloqueado -> discriminacion por agent_type:
           - agent_type == "knowledge-curator" -> ALLOW (unico rol legitimo).
           - agent_type ausente (= root) -> SENTINEL CHECK:
               * sentinel valido + no expirado (TTL <=1h) -> ALLOW + consume (delete) + override log.
               * sentinel expirado / timestamp invalido -> DENY + sweep sentinel + deny log.
               * sin sentinel -> DENY + deny log.
           - cualquier otro subagent -> DENY + deny log.
      7. exit 0 SIEMPRE (JSON permissionDecision). Logs auto-create (Add-Content).

    Sentinel-file (override de ROOT one-shot) - REUSO verbatim de scope-territory:
      Path:      docs/agent_runs/AR_<activo>/.scope_override
      Formato:   KV lineas `target=` / `reason=` / `timestamp=`
      Vida:      one-shot (borrado al consumir) + TTL 1h
      Timestamp: (Get-Date).ToString("o") - NUNCA mtime/LastWriteTime.
      Semantica: override de ROOT. knowledge-curator NO lo necesita.

.NOTES
    Trigger: PreToolUse matcher "Write|Edit"
    Output: exit 0 always + JSON permissionDecision (deny|allow) o passthrough sin JSON.

    Fail-open: parse errors / stdin vacio / excepciones -> ALLOW + stderr warning.
    Razon: hook NO es security boundary, es role discipline; falso-negativo (allow) <<
    falso-positivo (deny correcto workflow / lock-out).

    Debug:        $env:MULTIAGENT_HOOKS_DEBUG = "1" -> log a hooks\.debug.log
    Deny log:     SIEMPRE append a hooks\.deny.log (no condicional debug)
    Override log: SIEMPRE append a hooks\.override.log al consumir sentinel
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

# Bootstrap: derive paths from $env:MULTIAGENT_PATHS_CONFIG (override) or PROD default.
$PathsJson = if ($env:MULTIAGENT_PATHS_CONFIG -and (Test-Path -LiteralPath $env:MULTIAGENT_PATHS_CONFIG)) {
    $env:MULTIAGENT_PATHS_CONFIG
} else {
    "<repo_root>\config\paths.json"
}

$RepoRoot     = Split-Path -Parent (Split-Path -Parent $PathsJson)
$HooksDir     = Join-Path $RepoRoot "hooks"
$AgentRunsDir = Join-Path $RepoRoot "docs\agent_runs"
$DebugMode    = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"

# Constante TTL del sentinel override (horas).
$SentinelTtlHours = 1

# Resolver raiz KB: leer key `knowledge_base` del paths.json; fallback <knowledge_root>.
$KbRoot = "<knowledge_root>"
try {
    if (Test-Path -LiteralPath $PathsJson) {
        $cfg = Get-Content -LiteralPath $PathsJson -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ($cfg.knowledge_base -and -not [string]::IsNullOrWhiteSpace($cfg.knowledge_base)) {
            $KbRoot = $cfg.knowledge_base
        }
    }
} catch {
    # fallback ya seteado; KB root resuelto a default.
}

# Raiz KB normalizada (lowercase, forward-slash, sin trailing slash) anclada para match.
$KbNorm    = ($KbRoot -replace '\\', '/').ToLower().TrimEnd('/')
$KbPattern = '^' + [regex]::Escape("$KbNorm/") + '.+\.md$'

# --- Logging (Add-Content: crea archivo si falta + append; ISO8601 timestamps) ---
function Write-DebugLog($msg) {
    if (-not $DebugMode) { return }
    $logPath = Join-Path $HooksDir ".debug.log"
    $ts = (Get-Date).ToString("o")
    try { Add-Content -Path $logPath -Value "[$ts] [pretooluse-block-root-kb-write.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
}

function Write-DenyLog($agentType, $filePath, $reason) {
    $logPath = Join-Path $HooksDir ".deny.log"
    $ts = (Get-Date).ToString("o")
    try { Add-Content -Path $logPath -Value "[$ts] DENY-KB agent=$agentType file=$filePath reason=$reason" -ErrorAction SilentlyContinue } catch {}
}

function Write-OverrideLog($agentType, $filePath, $arDir, $reason) {
    $logPath = Join-Path $HooksDir ".override.log"
    $ts = (Get-Date).ToString("o")
    try { Add-Content -Path $logPath -Value "[$ts] OVERRIDE-SENTINEL-KB agent=$agentType file=$filePath ar=$arDir reason=$reason" -ErrorAction SilentlyContinue } catch {}
}

# --- Emit (exit 0 SIEMPRE) ---
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
    # Fuera de scope / no-match / fail-open: ALLOW implicito sin JSON.
    exit 0
}

# --- 1. Leer stdin (fail-open ALLOW) ---
$stdinRaw = ""
try { $stdinRaw = [Console]::In.ReadToEnd() } catch {
    [Console]::Error.WriteLine("[pretooluse-block-root-kb-write] stdin read failed; fail-open ALLOW")
    Emit-PassThrough
}
if ([string]::IsNullOrWhiteSpace($stdinRaw)) {
    [Console]::Error.WriteLine("[pretooluse-block-root-kb-write] stdin empty; fail-open ALLOW")
    Emit-PassThrough
}

# --- 2. Parse JSON (fail-open ALLOW) ---
$payload = $null
try { $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop } catch {
    [Console]::Error.WriteLine("[pretooluse-block-root-kb-write] stdin not JSON; fail-open ALLOW")
    Emit-PassThrough
}

# --- 3. Extraer campos ---
$toolName  = $payload.tool_name
$toolInput = $payload.tool_input
$agentType = $payload.agent_type
if (-not $agentType) { $agentType = "<unknown>" }   # root = agent_type ausente

# --- 4. Scope filter: solo Write|Edit ---
if ($toolName -ne "Write" -and $toolName -ne "Edit") { Emit-PassThrough }

$filePath = $toolInput.file_path
if ([string]::IsNullOrWhiteSpace($filePath)) { Emit-PassThrough }

# --- 5. Normalizar file_path (lowercase: patron KB es lowercase) ---
$norm = ($filePath -replace '\\', '/').ToLower().Trim()

# --- 6. Match territorio KB: bajo raiz KB anclada Y `.md` ---
if ($norm -notmatch $KbPattern) {
    # No es la KB -> no es asunto de este hook.
    Emit-PassThrough
}

Write-DebugLog "KB-TERRITORY match file=$filePath agent=$agentType kbRoot=$KbNorm"

# --- 7a. knowledge-curator -> ALLOW (unico rol legitimo) ---
if ($agentType -eq "knowledge-curator") {
    Write-DebugLog "ALLOW knowledge-curator file=$filePath"
    Emit-Allow
}

# --- 7b. Subagent no-curator (no root) -> DENY directo (sin sentinel) ---
if ($agentType -ne "<unknown>") {
    $denyReason = "Block KB-write: ``<knowledge_root>\*`` es territorio root-restringido (root NO escribe KB de su creencia - redisenio Fase 1 C2/anillo KB). " +
                  "caller=$agentType no es knowledge-curator. knowledge-curator escribe KB sin sentinel; specialists NO curan KB. " +
                  "Enforce quien+donde, no contenido. Cross-ref c2_signal_probe.md."
    Write-DenyLog $agentType $filePath "subagent-not-curator"
    Emit-Deny $denyReason
}

# --- 7c. Root (agent_type ausente) -> SENTINEL CHECK ---
$matched = $null
try {
    if (Test-Path -LiteralPath $AgentRunsDir) {
        $arDirs = Get-ChildItem -LiteralPath $AgentRunsDir -Directory -Filter "AR_*" -ErrorAction SilentlyContinue
        foreach ($dir in $arDirs) {
            $sentinel = Join-Path $dir.FullName ".scope_override"
            if (-not (Test-Path -LiteralPath $sentinel)) { continue }

            $sentTarget    = $null
            $sentReason    = $null
            $sentTimestamp = $null
            try {
                $raw = Get-Content -LiteralPath $sentinel -Raw -ErrorAction Stop
                foreach ($line in ($raw -split "`r?`n")) {
                    $trimmed = $line.Trim()
                    if ($trimmed -eq "") { continue }
                    $idx = $trimmed.IndexOf("=")
                    if ($idx -lt 1) { continue }
                    $k = $trimmed.Substring(0, $idx).Trim().ToLower()
                    $v = $trimmed.Substring($idx + 1).Trim()
                    switch ($k) {
                        "target"    { $sentTarget = $v }
                        "reason"    { $sentReason = $v }
                        "timestamp" { $sentTimestamp = $v }
                    }
                }
            } catch {
                Write-DebugLog "sentinel read failed $($dir.Name): $($_.Exception.Message)"
                continue
            }

            if ([string]::IsNullOrWhiteSpace($sentTarget)) { continue }
            $targetNorm = ($sentTarget -replace '\\', '/').ToLower().Trim()
            if ($targetNorm -eq $norm) {
                $matched = @{
                    Dir       = $dir
                    Sentinel  = $sentinel
                    Reason    = $sentReason
                    Timestamp = $sentTimestamp
                }
                break
            }
        }
    }
} catch {
    Write-DebugLog "sentinel scan error: $($_.Exception.Message)"
    $matched = $null
}

# --- 7c-i. Sin sentinel -> DENY ---
if ($null -eq $matched) {
    $denyReason = "Block KB-write: ``<knowledge_root>\*`` es territorio root-restringido (root NO escribe KB de su creencia - redisenio Fase 1 C2/anillo KB). " +
                  "caller=root. knowledge-curator escribe KB sin sentinel; root crea AR_*/.scope_override con target=$filePath reason=<motivo> timestamp=<ISO8601> para UNA edicion (one-shot TTL ${SentinelTtlHours}h). " +
                  "Enforce quien+donde, no contenido. Cross-ref c2_signal_probe.md."
    Write-DenyLog "<unknown>" $filePath "no-sentinel"
    Emit-Deny $denyReason
}

# --- 7c-ii. Sentinel encontrado -> validar TTL ---
$ts = $null
$tsValid = $true
try {
    $ts = [datetime]::Parse($matched.Timestamp)
} catch {
    $tsValid = $false
}

if (-not $tsValid) {
    try { Remove-Item -LiteralPath $matched.Sentinel -Force -ErrorAction SilentlyContinue } catch {}
    $denyReason = "Block KB-write: sentinel para KB-write tiene timestamp invalido ('$($matched.Timestamp)'). Sentinel barrido. " +
                  "Root: recrea AR_*/.scope_override con timestamp=<ISO8601 valido, p.ej (Get-Date).ToString('o')>. caller=root. Cross-ref c2_signal_probe.md."
    Write-DenyLog "<unknown>" $filePath "sentinel-bad-timestamp"
    Emit-Deny $denyReason
}

$elapsedHours = ((Get-Date) - $ts).TotalHours
if ($elapsedHours -gt $SentinelTtlHours) {
    try { Remove-Item -LiteralPath $matched.Sentinel -Force -ErrorAction SilentlyContinue } catch {}
    $denyReason = "Block KB-write: sentinel para KB-write expirado (edad $([math]::Round($elapsedHours,2))h > TTL ${SentinelTtlHours}h). Sentinel barrido. " +
                  "Root: recrea AR_*/.scope_override con timestamp actual para autorizar. caller=root. Cross-ref c2_signal_probe.md."
    Write-DenyLog "<unknown>" $filePath "sentinel-expired"
    Emit-Deny $denyReason
}

# --- 7c-iii. Sentinel valido y no expirado -> consumir (one-shot) + ALLOW ---
try { Remove-Item -LiteralPath $matched.Sentinel -Force -ErrorAction SilentlyContinue } catch {}
Write-OverrideLog "<unknown>" $filePath $matched.Dir.Name $matched.Reason
Write-DebugLog "OVERRIDE-SENTINEL-KB allow agent=root file=$filePath ar=$($matched.Dir.Name)"
Emit-Allow
