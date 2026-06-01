<#
.SYNOPSIS
    Stop hook — captura skills token tax per turn-end. Static upper-bound
    heuristica (CC v2.1.146 Stop payload NO expone subagents Task-invocados —
    documented limitation MVP P5 Hybrid Fase 5).

.DESCRIPTION
    Por cada agent .md en .claude\agents\:
      1. Parse frontmatter skills: (YAML list, 2-space indent).
      2. Resolver path skill SKILL.md, medir chars.
      3. approx_tokens = floor(chars_sum / 4).
    Append JSONL line a metrics_dir\skills_token_tax.jsonl.

    NO touch otros hooks Fase 4 / RC1 / RC9.
    NO touch settings.json (registracion step 4 separate).

.NOTES
    Trigger: Stop (cada turn end).
    Exit code: 0 SIEMPRE (Stop hook contract — nunca bloquea turn).
    Errores -> debug log + stderr silent, NUNCA throw.
    Encoding output: UTF-8 sin BOM via [System.IO.File]::AppendAllText.

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
    "F:\multiagent-system\config\paths.json"  # default PROD fallback
}
$RepoRoot        = Split-Path -Parent (Split-Path -Parent $PathsJson)
$AgentsDir       = Join-Path $RepoRoot ".claude\agents"
$SkillsDir       = Join-Path $RepoRoot ".claude\skills"
$MetricsFallback = Join-Path $RepoRoot ".metrics"
$DebugMode       = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"

function Write-DebugLog($msg) {
    if (-not $DebugMode) { return }
    try {
        $logPath = Join-Path $RepoRoot "hooks\.debug.log"
        $ts = (Get-Date).ToString("o")
        Add-Content -Path $logPath -Value "[$ts] [stop-capture-skills-token-tax.ps1] $msg" -ErrorAction SilentlyContinue
    } catch {}
}

# --- Consume stdin (descarta) ---
try { [Console]::In.ReadToEnd() | Out-Null } catch {}

Write-DebugLog "ENTRY"

# --- Resolver metrics_dir desde paths.json (fallback literal) ---
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

$OutFile = Join-Path $MetricsDir "skills_token_tax.jsonl"

# --- Verificar agents dir ---
if (-not (Test-Path -LiteralPath $AgentsDir)) {
    Write-DebugLog "no agents dir; exit"
    exit 0
}

# --- Parse skills: YAML field from frontmatter ---
function Get-SkillsFromAgent($agentPath) {
    $skills = @()
    try {
        $lines = [System.IO.File]::ReadAllLines($agentPath)
    } catch { return $skills }

    if ($lines.Count -lt 2) { return $skills }
    if ($lines[0] -notmatch '^---\s*$') { return $skills }

    $inFm = $true
    $inSkills = $false
    for ($i = 1; $i -lt $lines.Count; $i++) {
        $ln = $lines[$i]
        if ($ln -match '^---\s*$') { break }
        if (-not $inSkills) {
            if ($ln -match '^skills:\s*$') { $inSkills = $true; continue }
        } else {
            # Skill list entry: "  - <name>"
            if ($ln -match '^\s\s-\s+(.+?)\s*$') {
                $skills += $Matches[1].Trim()
            } elseif ($ln -match '^\S') {
                # Non-indented line = siguiente field, stop
                break
            }
        }
    }
    return $skills
}

# --- Per agent compute ---
$perAgent = @()
$totalTokens = 0

try {
    $agentFiles = Get-ChildItem -LiteralPath $AgentsDir -Filter "*.md" -File -ErrorAction SilentlyContinue
    foreach ($af in $agentFiles) {
        $skillNames = Get-SkillsFromAgent $af.FullName
        $charsSum = 0
        foreach ($sn in $skillNames) {
            $skillFile = Join-Path $SkillsDir (Join-Path $sn "SKILL.md")
            if (Test-Path -LiteralPath $skillFile) {
                try {
                    $content = [System.IO.File]::ReadAllText($skillFile)
                    $charsSum += $content.Length
                } catch {
                    Write-DebugLog "skill read fail $sn : $($_.Exception.Message)"
                }
            } else {
                Write-DebugLog "skill missing: $sn (agent $($af.BaseName))"
            }
        }
        $approxTokens = [int][Math]::Floor($charsSum / 4)
        $totalTokens += $approxTokens
        $perAgent += [PSCustomObject]@{
            agent           = $af.BaseName
            skills_count    = $skillNames.Count
            skills_chars_sum = $charsSum
            approx_tokens   = $approxTokens
        }
    }
} catch {
    Write-DebugLog "agents scan error: $($_.Exception.Message)"
    exit 0
}

# --- Consume _pending_turn_tasks.jsonl (Fase 5.1 dynamic per-task) ---
# Fail-open: si missing/malformed -> new fields = defaults, static metrics intactas.
$PendingFile         = Join-Path $MetricsDir "_pending_turn_tasks.jsonl"
$invokedSubagents    = @()
$actuallyLoaded      = @()
$actualApproxTokens  = 0
$pendingEntries      = @()  # cached for Fase 5.1b agentId lookup

if (Test-Path -LiteralPath $PendingFile) {
    try {
        $lines = Get-Content -LiteralPath $PendingFile -Encoding UTF8 -ErrorAction Stop
        foreach ($ln in $lines) {
            if ([string]::IsNullOrWhiteSpace($ln)) { continue }
            try {
                $obj = $ln | ConvertFrom-Json -ErrorAction Stop
                if ($obj.subagent_type) {
                    $invokedSubagents += [string]$obj.subagent_type
                    # Cache entry with tool_use_id (primary correlation key per AR_2026-05-29_fase5-1f)
                    # and agentId (backward-compat fallback) for Fase 5.1b response correlation.
                    $pendingEntries += [PSCustomObject]@{
                        subagent_type = [string]$obj.subagent_type
                        agentId       = if ($obj.agentId) { [string]$obj.agentId } else { "" }
                        session_id    = if ($obj.session_id) { [string]$obj.session_id } else { "" }
                        tool_use_id   = if ($obj.tool_use_id) { [string]$obj.tool_use_id } else { "" }
                    }
                }
            } catch {
                Write-DebugLog "pending line malformed (skip): $($_.Exception.Message)"
            }
        }
        # Dedupe (force array even si Select-Object -Unique devuelve scalar 1 elem)
        $invokedSubagents = @($invokedSubagents | Select-Object -Unique)

        # Subset per_agent matching invocados
        foreach ($agentEntry in $perAgent) {
            if ($invokedSubagents -contains $agentEntry.agent) {
                $actuallyLoaded += [PSCustomObject]@{
                    agent         = $agentEntry.agent
                    approx_tokens = $agentEntry.approx_tokens
                }
                $actualApproxTokens += $agentEntry.approx_tokens
            }
        }

        # Delete ephemeral buffer post-consume (avoid stale next turn)
        Remove-Item -LiteralPath $PendingFile -Force -ErrorAction SilentlyContinue
        Write-DebugLog "pending consumed: invoked=$($invokedSubagents.Count) loaded=$($actuallyLoaded.Count) actual=$actualApproxTokens"
    } catch {
        Write-DebugLog "pending file unreadable (fail-open): $($_.Exception.Message)"
    }
} else {
    Write-DebugLog "no pending file (dynamic fields default empty)"
}

# --- Fase 5.1b: per-skill usage detection (false-positive surfacing) ---
# Fail-open 3 puntos: distinctive_phrases.json missing/malformed, subagent JSONL
# missing, JSONL line malformed -> empty per_skill_usage (no crash).
# MVP simplification: append entries ONLY si matches >= 1 (cited). Aggregator
# (step 7+) computa false-positive como: loaded - cited.
$PerSkillUsage = @()
$DistinctivePhrasesPath = Join-Path $RepoRoot "scripts\metrics\distinctive_phrases.json"
$ProjectsBase = Join-Path $env:USERPROFILE ".claude\projects\F--multiagent-system"

$distinctivePhrases = $null
if (Test-Path -LiteralPath $DistinctivePhrasesPath) {
    try {
        $rawPhrases = [System.IO.File]::ReadAllText($DistinctivePhrasesPath)
        $distinctivePhrases = $rawPhrases | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Write-DebugLog "distinctive_phrases.json malformed (fail-open): $($_.Exception.Message)"
        $distinctivePhrases = $null
    }
} else {
    Write-DebugLog "distinctive_phrases.json missing (fail-open)"
}

if ($distinctivePhrases -and $pendingEntries.Count -gt 0 -and (Test-Path -LiteralPath $ProjectsBase)) {
    # Build list of skill names (keys of distinctivePhrases PSCustomObject)
    $skillNamesAll = @()
    try {
        $skillNamesAll = @($distinctivePhrases.PSObject.Properties | ForEach-Object { $_.Name })
    } catch {
        Write-DebugLog "distinctive_phrases keys extract fail: $($_.Exception.Message)"
    }

    foreach ($pe in $pendingEntries) {
        # New architectural pivot (AR_2026-05-29_fase5-1f): correlation key = tool_use_id.
        # CC v2.1.146 PreToolUse payload emits tool_use_id but NOT agentId (generated at
        # spawn post-PreToolUse phase). Resolve agentId by scanning meta.json filesystem
        # under <ProjectsBase>\<session_id>\subagents\agent-<HEX17>.meta.json and matching
        # field "toolUseId" == pe.tool_use_id. Extract <HEX17> from filename.
        # Backward-compat: if tool_use_id empty AND agentId non-empty (legacy / future CC
        # version that emits agentId-on-PreToolUse) -> use legacy path build.

        $resolvedAgentId = ""

        if (-not [string]::IsNullOrWhiteSpace($pe.tool_use_id)) {
            # Determine session scope: prefer pe.session_id, else all sessions.
            $sessionDirs = @()
            if (-not [string]::IsNullOrWhiteSpace($pe.session_id)) {
                $sd = Join-Path $ProjectsBase $pe.session_id
                if (Test-Path -LiteralPath $sd) { $sessionDirs += $sd }
            } else {
                try {
                    $allSessions = Get-ChildItem -LiteralPath $ProjectsBase -Directory -ErrorAction SilentlyContinue
                    foreach ($s in $allSessions) { $sessionDirs += $s.FullName }
                } catch {
                    Write-DebugLog "session enumerate fail for tool_use_id=$($pe.tool_use_id): $($_.Exception.Message)"
                }
            }

            foreach ($sd in $sessionDirs) {
                $subagentsDir = Join-Path $sd "subagents"
                if (-not (Test-Path -LiteralPath $subagentsDir)) { continue }
                try {
                    $metaFiles = Get-ChildItem -LiteralPath $subagentsDir -Filter "*.meta.json" -File -ErrorAction SilentlyContinue
                } catch {
                    Write-DebugLog "subagents dir read fail $($subagentsDir): $($_.Exception.Message)"
                    continue
                }
                foreach ($mf in $metaFiles) {
                    try {
                        $metaRaw = [System.IO.File]::ReadAllText($mf.FullName)
                        $meta = $metaRaw | ConvertFrom-Json -ErrorAction Stop
                    } catch {
                        # malformed meta.json -> skip
                        continue
                    }
                    if ($meta.toolUseId -and ([string]$meta.toolUseId -eq $pe.tool_use_id)) {
                        # Extract HEX17 from filename "agent-<HEX17>.meta.json"
                        $bn = $mf.BaseName  # "agent-<HEX17>.meta"
                        if ($bn -match '^agent-([a-f0-9]{17})\.meta$') {
                            $resolvedAgentId = $Matches[1]
                            Write-DebugLog "resolved agentId=$resolvedAgentId for tool_use_id=$($pe.tool_use_id)"
                            break
                        }
                    }
                }
                if (-not [string]::IsNullOrWhiteSpace($resolvedAgentId)) { break }
            }
        }

        # Backward-compat fallback: legacy agentId path.
        if ([string]::IsNullOrWhiteSpace($resolvedAgentId) -and -not [string]::IsNullOrWhiteSpace($pe.agentId)) {
            $resolvedAgentId = $pe.agentId
        }

        if ([string]::IsNullOrWhiteSpace($resolvedAgentId)) {
            Write-DebugLog "pending entry $($pe.subagent_type) unresolved (tool_use_id=$($pe.tool_use_id) agentId=$($pe.agentId)); skip"
            continue
        }

        # Build candidate JSONL paths using resolvedAgentId.
        $candidatePaths = @()
        if (-not [string]::IsNullOrWhiteSpace($pe.session_id)) {
            $candidatePaths += (Join-Path $ProjectsBase (Join-Path $pe.session_id (Join-Path "subagents" "agent-$resolvedAgentId.jsonl")))
        } else {
            try {
                $sessions = Get-ChildItem -LiteralPath $ProjectsBase -Directory -ErrorAction SilentlyContinue
                foreach ($s in $sessions) {
                    $p = Join-Path $s.FullName (Join-Path "subagents" "agent-$resolvedAgentId.jsonl")
                    if (Test-Path -LiteralPath $p) { $candidatePaths += $p }
                }
            } catch {
                Write-DebugLog "session scan fail for agentId=$resolvedAgentId : $($_.Exception.Message)"
            }
        }

        $jsonlPath = $null
        foreach ($cp in $candidatePaths) {
            if (Test-Path -LiteralPath $cp) { $jsonlPath = $cp; break }
        }

        if (-not $jsonlPath) {
            Write-DebugLog "subagent JSONL missing agentId=$($pe.agentId) (fail-open)"
            continue
        }

        # Extract concatenated assistant response text from JSONL
        $responseText = ""
        try {
            $jsonlLines = Get-Content -LiteralPath $jsonlPath -Encoding UTF8 -ErrorAction Stop
            foreach ($jl in $jsonlLines) {
                if ([string]::IsNullOrWhiteSpace($jl)) { continue }
                try {
                    $jobj = $jl | ConvertFrom-Json -ErrorAction Stop
                    if ($jobj.message -and $jobj.message.role -eq "assistant" -and $jobj.message.content) {
                        foreach ($cnode in $jobj.message.content) {
                            if ($cnode.type -eq "text" -and $cnode.text) {
                                $responseText += [string]$cnode.text + "`n"
                            }
                        }
                    }
                } catch {
                    # malformed line -> skip (fail-open)
                }
            }
        } catch {
            Write-DebugLog "subagent JSONL unreadable $($jsonlPath): $($_.Exception.Message)"
            continue
        }

        if ([string]::IsNullOrWhiteSpace($responseText)) {
            Write-DebugLog "subagent $($pe.agentId) empty response text; skip"
            continue
        }

        # For each skill, count distinct phrase matches. Append only if matches >= 1.
        foreach ($skillName in $skillNamesAll) {
            $phrases = $distinctivePhrases.$skillName
            if (-not $phrases) { continue }
            $matchesCount = 0
            foreach ($phrase in $phrases) {
                if ([string]::IsNullOrWhiteSpace($phrase)) { continue }
                # Case-sensitive substring match (literal)
                if ($responseText.Contains([string]$phrase)) {
                    $matchesCount++
                }
            }
            if ($matchesCount -ge 1) {
                $PerSkillUsage += [PSCustomObject]@{
                    skill         = $skillName
                    agent         = $pe.subagent_type
                    status        = "cited"
                    matches_count = $matchesCount
                }
            }
        }
    }
    Write-DebugLog "per_skill_usage entries: $($PerSkillUsage.Count)"
} else {
    Write-DebugLog "per_skill_usage skipped (no phrases / no pending / no projects dir)"
}

# --- Build JSONL record ---
$turnId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$record = [PSCustomObject]@{
    ts                          = (Get-Date).ToString("o")
    turn_id                     = $turnId
    per_agent                   = $perAgent
    total_approx_tokens         = $totalTokens
    subagents_invoked_this_turn = $invokedSubagents
    per_agent_actually_loaded   = $actuallyLoaded
    actual_approx_tokens        = $actualApproxTokens
    per_skill_usage             = $PerSkillUsage
}

try {
    $json = $record | ConvertTo-Json -Depth 5 -Compress
    [System.IO.File]::AppendAllText($OutFile, ($json + "`n"), [System.Text.UTF8Encoding]::new($false))
    Write-DebugLog "appended turn_id=$turnId total=$totalTokens agents=$($perAgent.Count)"
} catch {
    Write-DebugLog "append fail: $($_.Exception.Message)"
}

exit 0
