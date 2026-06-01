<#
.SYNOPSIS
    PreToolUse hook (matcher Write|Edit) — hard-block scope-territory role-discipline
    agent_type-aware. Reemplaza el advisory exit-0 (0% enforcement empírico) por un
    hard-block `permissionDecision=deny` por territorio, con override sentinel-file
    root one-shot TTL 1h. Cross-ref AR_2026-06-01_p3-hard-block-scope-territory.

.DESCRIPTION
    Lee stdin JSON de Claude Code v2.1.146. Discrimina al caller por `agent_type`
    (string exacto del subagent; AUSENTE -> root). Defensa role-discipline, NO
    security boundary.

    Flujo (orden importa):
      1. read stdin -> parse JSON. Fallo o vacio -> fail-open ALLOW (passthrough).
      2. filter tool_name in {Write, Edit}; otro -> passthrough.
      3. normalizar file_path: \ -> /, lowercase, trim.
      4. NEVER-block check PRIMERO -> ALLOW inmediato (anti lock-out):
           - `.verse` / `content/verse/`
           - `AR_*/final_report.md`
           - `config/*.json`
           - `hooks/*`
      5. DENY-territory match (5 patterns role-map). No-match -> passthrough.
      6. Territorio bloqueado:
           - agent_type == rol-legitimo-del-territorio -> ALLOW (subagent en su trabajo).
           - root O subagent-equivocado O territorio root-only -> SENTINEL CHECK:
               * sentinel valido + no expirado (TTL <=1h) -> ALLOW + consume (delete) + override log.
               * sentinel expirado / timestamp invalido -> DENY + sweep sentinel + deny log.
               * sin sentinel -> DENY + deny log.
      7. exit 0 SIEMPRE (JSON permissionDecision). Logs auto-create (Add-Content).

    Role-map (territorio -> rol legitimo), datos empiricos role_map_probe.md:
      docs/agent_runs/AR_*/plan.md            -> planner
      docs/agent_runs/AR_*/hypotheses.md      -> (root-sentinel-only)
      docs/agent_runs/AR_*/curator_report.md  -> knowledge-curator
      agent_templates/*.md                    -> implementer
      .claude/agents/*.md                     -> (root-sentinel-only)

    Sentinel-file (override de ROOT one-shot):
      Path:      docs/agent_runs/AR_<activo>/.scope_override
      Formato:   KV lineas `target=` / `reason=` / `timestamp=`
      Vida:      one-shot (borrado al consumir) + TTL 1h
      Timestamp: (Get-Date).ToString("o") — NUNCA mtime/LastWriteTime.
      Semantica: override de ROOT. Subagents legitimos NO lo necesitan.

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
    "F:\multiagent-system\config\paths.json"
}

$RepoRoot     = Split-Path -Parent (Split-Path -Parent $PathsJson)
$HooksDir     = Join-Path $RepoRoot "hooks"
$AgentRunsDir = Join-Path $RepoRoot "docs\agent_runs"
$DebugMode    = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"

# Repo root normalizado (lowercase, forward-slash) para anclar NEVER-block paths al repo real.
$RepoNorm    = ($RepoRoot -replace '\\', '/').ToLower().TrimEnd('/')
$CfgPattern  = '^' + [regex]::Escape("$RepoNorm/config/") + '[^/]+\.json$'
$HookPattern = '^' + [regex]::Escape("$RepoNorm/hooks/")

# Constante TTL del sentinel override (horas).
$SentinelTtlHours = 1

# --- Logging (Add-Content: crea archivo si falta + append; ISO8601 timestamps) ---
function Write-DebugLog($msg) {
    if (-not $DebugMode) { return }
    $logPath = Join-Path $HooksDir ".debug.log"
    $ts = (Get-Date).ToString("o")
    try { Add-Content -Path $logPath -Value "[$ts] [pretooluse-block-scope-territory.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
}

function Write-DenyLog($agentType, $filePath, $territory, $reason) {
    $logPath = Join-Path $HooksDir ".deny.log"
    $ts = (Get-Date).ToString("o")
    try { Add-Content -Path $logPath -Value "[$ts] DENY-SCOPE agent=$agentType file=$filePath territory=$territory reason=$reason" -ErrorAction SilentlyContinue } catch {}
}

function Write-OverrideLog($agentType, $filePath, $arDir, $reason) {
    $logPath = Join-Path $HooksDir ".override.log"
    $ts = (Get-Date).ToString("o")
    try { Add-Content -Path $logPath -Value "[$ts] OVERRIDE-SENTINEL agent=$agentType file=$filePath ar=$arDir reason=$reason" -ErrorAction SilentlyContinue } catch {}
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
    [Console]::Error.WriteLine("[pretooluse-block-scope-territory] stdin read failed; fail-open ALLOW")
    Emit-PassThrough
}
if ([string]::IsNullOrWhiteSpace($stdinRaw)) {
    [Console]::Error.WriteLine("[pretooluse-block-scope-territory] stdin empty; fail-open ALLOW")
    Emit-PassThrough
}

# --- 2. Parse JSON (fail-open ALLOW) ---
$payload = $null
try { $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop } catch {
    [Console]::Error.WriteLine("[pretooluse-block-scope-territory] stdin not JSON; fail-open ALLOW")
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

# --- 5. Normalizar file_path (lowercase: patrones siguientes son lowercase) ---
$norm = ($filePath -replace '\\', '/').ToLower().Trim()

# --- 6. NEVER-block check PRIMERO (anti lock-out) ---
if ($norm -match '\.verse$' -or
    $norm -match 'content/verse/' -or
    $norm -match 'docs/agent_runs/ar_[^/]+/final_report\.md$' -or
    $norm -match $CfgPattern -or
    $norm -match $HookPattern) {
    Write-DebugLog "NEVER-BLOCK allow file=$filePath agent=$agentType"
    Emit-Allow
}

# --- 7. DENY-territory match (determina $territory + $legitRole) ---
$territory = $null
$legitRole = $null

if ($norm -match 'docs/agent_runs/ar_[^/]+/plan\.md$') {
    $territory = "plan.md"; $legitRole = "planner"
}
elseif ($norm -match 'docs/agent_runs/ar_[^/]+/hypotheses\.md$') {
    $territory = "hypotheses.md"; $legitRole = $null            # root-sentinel-only
}
elseif ($norm -match 'docs/agent_runs/ar_[^/]+/curator_report\.md$') {
    $territory = "curator_report.md"; $legitRole = "knowledge-curator"
}
elseif ($norm -match 'agent_templates/[^/]+\.md$') {
    $territory = "agent_templates"; $legitRole = "implementer"
}
elseif ($norm -match '\.claude/agents/[^/]+\.md$') {
    $territory = ".claude/agents"; $legitRole = $null           # root-sentinel-only
}
else {
    Emit-PassThrough   # no territorio gestionado
}

Write-DebugLog "TERRITORY=$territory legitRole=$legitRole agent=$agentType file=$filePath"

# --- 8a. Subagent legitimo de su propio territorio -> ALLOW ---
if ($null -ne $legitRole -and $agentType -eq $legitRole) {
    Write-DebugLog "ALLOW legit subagent agent=$agentType territory=$territory"
    Emit-Allow
}

# --- 8b. Root o subagent-equivocado o territorio root-only -> SENTINEL CHECK ---
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

# --- 8b-i. Sin sentinel -> DENY ---
if ($null -eq $matched) {
    $denyReason = "Block scope-territory: territorio '$territory' restringido. caller=$agentType. " +
                  "Root: crea AR_*/.scope_override con target=$filePath reason=<motivo> timestamp=<ISO8601> para autorizar UNA edicion (one-shot, TTL ${SentinelTtlHours}h). " +
                  "Subagent legitimo del territorio pasa sin sentinel; este caller no lo es. Cross-ref AR_2026-06-01_p3-hard-block-scope-territory."
    Write-DenyLog $agentType $filePath $territory "no-sentinel"
    Emit-Deny $denyReason
}

# --- 8b-ii. Sentinel encontrado -> validar TTL ---
$ts = $null
$tsValid = $true
try {
    $ts = [datetime]::Parse($matched.Timestamp)
} catch {
    $tsValid = $false
}

if (-not $tsValid) {
    try { Remove-Item -LiteralPath $matched.Sentinel -Force -ErrorAction SilentlyContinue } catch {}
    $denyReason = "Block scope-territory: sentinel para '$territory' tiene timestamp invalido ('$($matched.Timestamp)'). Sentinel barrido. " +
                  "Root: recrea AR_*/.scope_override con timestamp=<ISO8601 valido, p.ej (Get-Date).ToString('o')>. caller=$agentType."
    Write-DenyLog $agentType $filePath $territory "sentinel-bad-timestamp"
    Emit-Deny $denyReason
}

$elapsedHours = ((Get-Date) - $ts).TotalHours
if ($elapsedHours -gt $SentinelTtlHours) {
    try { Remove-Item -LiteralPath $matched.Sentinel -Force -ErrorAction SilentlyContinue } catch {}
    $denyReason = "Block scope-territory: sentinel para '$territory' expirado (edad $([math]::Round($elapsedHours,2))h > TTL ${SentinelTtlHours}h). Sentinel barrido. " +
                  "Root: recrea AR_*/.scope_override con timestamp actual para autorizar. caller=$agentType."
    Write-DenyLog $agentType $filePath $territory "sentinel-expired"
    Emit-Deny $denyReason
}

# --- 8b-iii. Sentinel valido y no expirado -> consumir (one-shot) + ALLOW ---
try { Remove-Item -LiteralPath $matched.Sentinel -Force -ErrorAction SilentlyContinue } catch {}
Write-OverrideLog $agentType $filePath $matched.Dir.Name $matched.Reason
Write-DebugLog "OVERRIDE-SENTINEL allow agent=$agentType territory=$territory ar=$($matched.Dir.Name)"
Emit-Allow
