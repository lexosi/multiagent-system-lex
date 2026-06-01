<#
.SYNOPSIS
    SessionStart hook — regenera ~/.claude/agents/*.md desde agent_templates/*.md
    sustituyendo placeholders {{paths.X.Y}} con valores de paths.json.

.DESCRIPTION
    Lee templates desde F:\multiagent-system\agent_templates\*.md (source-of-truth
    versionable). Sustituye placeholders {{paths.X.Y}} usando paths.json.
    Escribe resultado a $env:USERPROFILE\.claude\agents\*.md (runtime, leido por
    Claude Code).

    Idempotente via state file (.placeholders_state.json) con SHA256 de paths.json
    + hash agregado de templates + SHA256 agents.json + SHA256 models.json.
    Si nada cambio -> SKIP rapido.

    Tambien sustituye {{model}} en frontmatter via agents.json[<name>].tier ->
    models.json.tiers[<tier>] -> model value. Normaliza claude-opus-* -> "opus"
    (CC frontmatter short name). Loud failure si claude_md + tier resuelve a
    deepseek-* (Lexosi-enforced: claude_md SIEMPRE tier=high+opus).

    Tambien lee F:\multiagent-system\.curator_pending (escrito por Hook 2 Stop)
    y, si existe, inyecta additionalContext informando al root.

.NOTES
    Trigger: SessionStart matchers startup|resume|clear|compact.
    Compatibilidad: Windows PowerShell 5.1.

    Exit codes:
      0 = ok (skip o regen)
      1 = paths.json no encontrado
      2 = paths.json malformado
      3 = fallo escribiendo archivo de salida
      4 = template dir no encontrado
      5 = contradiction agents.json/models.json (claude_md + deepseek model)

    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> log a hooks\.debug.log
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# --- Constantes ---
# Bootstrap: resolver paths.json + repo root con env var override.
# Precedence: MULTIAGENT_PATHS_CONFIG env var > hardcoded PROD fallback.
# Para dev sandbox, set $env:MULTIAGENT_PATHS_CONFIG = '<sandbox-dir>\config\paths.json'. Default = PROD.
# CC v2.1.142 Windows: solo carga project-level .claude\agents\ (bug #31392).
# User-level $env:USERPROFILE\.claude\agents\ es ignorado en runtime.
# P5 Hybrid Fase 4 (2026-05-28): skills regen nested. Source SKILL.md viven en
# agent_templates\skills\<name>\SKILL.md. Runtime target .claude\skills\<name>\SKILL.md
# (project-level, CC v2.1.146 lo lee). Mismo pattern UTF-8 sin BOM que agents.
$PathsJson = if ($env:MULTIAGENT_PATHS_CONFIG -and (Test-Path -LiteralPath $env:MULTIAGENT_PATHS_CONFIG)) {
    $env:MULTIAGENT_PATHS_CONFIG
} else {
    "F:\multiagent-system\config\paths.json"  # default PROD fallback
}

# Derive repo root from paths.json location (paths.json lives at $RepoRoot\config\paths.json)
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PathsJson)

# Derived paths (all relative to $RepoRoot, consistent dev/prod via env override)
$TemplatesDir         = Join-Path $RepoRoot "agent_templates"
$RuntimeDir           = Join-Path $RepoRoot ".claude\agents"
$SkillsTemplatesDir   = Join-Path $TemplatesDir "skills"
$SkillsRuntimeDir     = Join-Path $RepoRoot ".claude\skills"
$ConfigPath           = $PathsJson
$AgentsConfigPath     = Join-Path $RepoRoot "config\agents.json"
$ModelsConfigPath     = Join-Path $RepoRoot "config\models.json"
$StatePath            = Join-Path $RepoRoot ".placeholders_state.json"
$CuratorPending       = Join-Path $RepoRoot ".curator_pending"
$LastModelReviewPath  = Join-Path $RepoRoot ".last_model_review"
$DefaultModelReviewHours = 72

# --- Debug helper ---
$DebugMode = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"
function Write-DebugLog($msg) {
    if ($DebugMode) {
        $logPath = Join-Path $RepoRoot "hooks\.debug.log"
        $timestamp = (Get-Date).ToString("o")
        try { Add-Content -Path $logPath -Value "[$timestamp] [session-start-substitute-paths.ps1] $msg" -ErrorAction SilentlyContinue } catch {}
    }
}

# --- Helper: emit additionalContext y exit ---
function Emit-AdditionalContext($contextText, $exitCode = 0) {
    if ([string]::IsNullOrWhiteSpace($contextText)) {
        exit $exitCode
    }
    $payload = @{
        hookSpecificOutput = @{
            hookEventName     = "SessionStart"
            additionalContext = $contextText
        }
    }
    $json = $payload | ConvertTo-Json -Depth 5 -Compress
    [Console]::Out.WriteLine($json)
    exit $exitCode
}

# --- Consume stdin (no se usa) ---
try {
    $stdinRaw = [Console]::In.ReadToEnd()
    Write-DebugLog "stdin bytes: $($stdinRaw.Length)"
} catch {
    Write-DebugLog "stdin read failed (ok, no critical): $($_.Exception.Message)"
}

Write-DebugLog "ENTRY"

# --- 1. Verificar templates dir ---
if (-not (Test-Path -LiteralPath $TemplatesDir)) {
    Write-DebugLog "EXIT 4: templates dir missing: $TemplatesDir"
    [Console]::Error.WriteLine("Templates dir not found: $TemplatesDir")
    exit 4
}

# --- 2. Verificar config ---
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Write-DebugLog "EXIT 1: paths.json missing: $ConfigPath"
    [Console]::Error.WriteLine("Config not found: $ConfigPath")
    exit 1
}

# --- 3. Cargar paths.json + calcular hash ---
try {
    $rawConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
    $config = $rawConfig | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-DebugLog "EXIT 2: malformed JSON in $ConfigPath : $($_.Exception.Message)"
    [Console]::Error.WriteLine("Malformed JSON in ${ConfigPath}: $($_.Exception.Message)")
    exit 2
}
$pathsHash = [BitConverter]::ToString(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
        [System.Text.Encoding]::UTF8.GetBytes($rawConfig)
    )
).Replace("-", "")
Write-DebugLog "paths.json hash: $($pathsHash.Substring(0,16))..."

# --- 3.5 Cargar agents.json + models.json (model placeholder resolution) ---
# Defensive: missing/malformed -> log warning, leave hash empty, skip model substitution downstream.
# claude_md frontmatter compatibility: claude-opus-* values normalized to "opus" short name.
$agentsConfig = $null
$modelsConfig = $null
$agentsHash = ""
$modelsHash = ""

if (Test-Path -LiteralPath $AgentsConfigPath) {
    try {
        $rawAgents = Get-Content -LiteralPath $AgentsConfigPath -Raw -Encoding UTF8
        $agentsConfig = $rawAgents | ConvertFrom-Json -ErrorAction Stop
        $agentsHash = [BitConverter]::ToString(
            [System.Security.Cryptography.SHA256]::Create().ComputeHash(
                [System.Text.Encoding]::UTF8.GetBytes($rawAgents)
            )
        ).Replace("-", "")
        Write-DebugLog "agents.json hash: $($agentsHash.Substring(0,16))..."
    } catch {
        Write-DebugLog "WARN: agents.json malformed: $($_.Exception.Message)"
        [Console]::Error.WriteLine("WARN: agents.json malformed ${AgentsConfigPath}: $($_.Exception.Message)")
        $agentsConfig = $null
    }
} else {
    Write-DebugLog "WARN: agents.json missing: $AgentsConfigPath"
}

if (Test-Path -LiteralPath $ModelsConfigPath) {
    try {
        $rawModels = Get-Content -LiteralPath $ModelsConfigPath -Raw -Encoding UTF8
        $modelsConfig = $rawModels | ConvertFrom-Json -ErrorAction Stop
        $modelsHash = [BitConverter]::ToString(
            [System.Security.Cryptography.SHA256]::Create().ComputeHash(
                [System.Text.Encoding]::UTF8.GetBytes($rawModels)
            )
        ).Replace("-", "")
        Write-DebugLog "models.json hash: $($modelsHash.Substring(0,16))..."
    } catch {
        Write-DebugLog "WARN: models.json malformed: $($_.Exception.Message)"
        [Console]::Error.WriteLine("WARN: models.json malformed ${ModelsConfigPath}: $($_.Exception.Message)")
        $modelsConfig = $null
    }
} else {
    Write-DebugLog "WARN: models.json missing: $ModelsConfigPath"
}

# --- 4. Calcular hash agregado de templates ---
$templateFiles = Get-ChildItem -LiteralPath $TemplatesDir -Filter *.md -File -ErrorAction SilentlyContinue
if ($templateFiles.Count -eq 0) {
    Write-DebugLog "EXIT 4: no templates in $TemplatesDir"
    [Console]::Error.WriteLine("No .md templates in $TemplatesDir")
    exit 4
}
$tplConcat = ($templateFiles | Sort-Object Name | ForEach-Object {
    "$($_.Name):$($_.Length):$($_.LastWriteTimeUtc.Ticks)"
}) -join "|"
$tplHash = [BitConverter]::ToString(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
        [System.Text.Encoding]::UTF8.GetBytes($tplConcat)
    )
).Replace("-", "")
Write-DebugLog "templates hash: $($tplHash.Substring(0,16))... ($($templateFiles.Count) files)"

# --- 4.5 Calcular hash agregado de skills (nested SKILL.md) ---
# P5 Hybrid Fase 4: scan recursivo agent_templates\skills\<name>\SKILL.md.
# Concat usa RelativePath para distinguir nombre dir padre (skill name).
# Si dir no existe -> hash vacio (no skills configured, no-op silent).
$skillsHash = ""
$skillFiles = @()
if (Test-Path -LiteralPath $SkillsTemplatesDir) {
    $skillFiles = Get-ChildItem -LiteralPath $SkillsTemplatesDir -Filter SKILL.md -Recurse -File -ErrorAction SilentlyContinue
    if ($skillFiles.Count -gt 0) {
        $skillConcat = ($skillFiles | Sort-Object FullName | ForEach-Object {
            $rel = $_.FullName.Substring($SkillsTemplatesDir.Length).TrimStart('\','/')
            "${rel}:$($_.Length):$($_.LastWriteTimeUtc.Ticks)"
        }) -join "|"
        $skillsHash = [BitConverter]::ToString(
            [System.Security.Cryptography.SHA256]::Create().ComputeHash(
                [System.Text.Encoding]::UTF8.GetBytes($skillConcat)
            )
        ).Replace("-", "")
        Write-DebugLog "skills hash: $($skillsHash.Substring(0,16))... ($($skillFiles.Count) SKILL.md files)"
    } else {
        Write-DebugLog "skills dir present but no SKILL.md found"
    }
} else {
    Write-DebugLog "skills templates dir absent: $SkillsTemplatesDir"
}

# --- 5. Leer state ---
$state = $null
if (Test-Path -LiteralPath $StatePath) {
    try {
        $state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Write-DebugLog "state file corrupt, ignoring: $($_.Exception.Message)"
        $state = $null
    }
}

$skipRegen = $false
# Backward-compat: state files antiguos sin `skills_hash` field -> `$state.skills_hash`
# devuelve $null -> mismatch contra $skillsHash (non-empty si hay skills) -> trigger
# regen first-run post-deploy. Si no hay skills dir -> $skillsHash="" -> match $null
# -> NO bloquea skip. Aditivo limpio.
if ($state -and $state.paths_json_hash -eq $pathsHash -and $state.templates_hash -eq $tplHash `
    -and $state.agents_json_hash -eq $agentsHash -and $state.models_json_hash -eq $modelsHash `
    -and $state.skills_hash -eq $skillsHash) {
    $skipRegen = $true
    Write-DebugLog "SKIP regen: state matches (paths+templates+agents+models+skills)"
} else {
    Write-DebugLog "REGEN: state miss or hash diff (paths/templates/agents/models/skills)"
}

# --- 6. Regenerar si necesario ---
$contextLines = @()
if (-not $skipRegen) {

    function Get-FlatPlaceholders {
        param([Parameter(Mandatory)] $Node, [string]$Prefix = "paths")
        $result = @{}
        foreach ($prop in $Node.PSObject.Properties) {
            $key = "$Prefix.$($prop.Name)"
            $val = $prop.Value
            if ($val -is [string]) {
                $result["{{$key}}"] = $val
            } elseif ($val -is [pscustomobject]) {
                $nested = Get-FlatPlaceholders -Node $val -Prefix $key
                foreach ($k in $nested.Keys) { $result[$k] = $nested[$k] }
            }
        }
        return $result
    }
    $placeholders = Get-FlatPlaceholders -Node $config
    Write-DebugLog "loaded $($placeholders.Count) placeholders"

    # Resolve-ModelPlaceholder: sustituye {{model}} en template content via
    # agents.json[<name>].tier -> models.json.tiers[<tier>] -> model value.
    # Normaliza claude-opus-* -> "opus" (CC short name compat frontmatter).
    # Error loud si claude_md + tier resuelve a deepseek-* (contradicción Lexosi-enforced).
    # Si name/tier/model missing -> warning + leave placeholder intact (visible next session).
    function Resolve-ModelPlaceholder {
        param(
            [Parameter(Mandatory)][string]$Content,
            [Parameter(Mandatory)][string]$TemplateName,
            $AgentsCfg,
            $ModelsCfg,
            [ref]$Warnings
        )
        # Skip if no {{model}} placeholder present.
        if (-not [regex]::IsMatch($Content, '\{\{model\}\}')) {
            return $Content
        }
        if (-not $AgentsCfg -or -not $ModelsCfg) {
            $msg = "${TemplateName}: {{model}} placeholder present but agents.json/models.json unavailable"
            $Warnings.Value += $msg
            Write-DebugLog "WARN $msg"
            return $Content
        }
        # Extract `name:` from frontmatter (must appear before second `---`).
        $nameMatch = [regex]::Match($Content, '(?m)^name:\s*(\S+)\s*$')
        if (-not $nameMatch.Success) {
            $msg = "${TemplateName}: cannot extract `name:` from frontmatter"
            $Warnings.Value += $msg
            Write-DebugLog "WARN $msg"
            return $Content
        }
        $agentName = $nameMatch.Groups[1].Value
        $agentEntry = $null
        if ($AgentsCfg.agents.PSObject.Properties.Name -contains $agentName) {
            $agentEntry = $AgentsCfg.agents.$agentName
        }
        if (-not $agentEntry) {
            $msg = "${TemplateName}: agent '$agentName' not in agents.json"
            $Warnings.Value += $msg
            Write-DebugLog "WARN $msg"
            return $Content
        }
        $tier = $agentEntry.tier
        if ([string]::IsNullOrWhiteSpace($tier)) {
            $msg = "${TemplateName}: agent '$agentName' has null/empty tier"
            $Warnings.Value += $msg
            Write-DebugLog "WARN $msg"
            return $Content
        }
        $modelValue = $null
        if ($ModelsCfg.tiers.PSObject.Properties.Name -contains $tier) {
            $modelValue = $ModelsCfg.tiers.$tier
        }
        if ([string]::IsNullOrWhiteSpace($modelValue)) {
            $msg = "${TemplateName}: tier '$tier' not in models.json.tiers"
            $Warnings.Value += $msg
            Write-DebugLog "WARN $msg"
            return $Content
        }
        # Contradiction check: claude_md + deepseek-* = invariant violation.
        $agentType = $agentEntry.type
        if ($agentType -eq "claude_md" -and $modelValue -match '^deepseek-') {
            $errMsg = "${TemplateName}: CONTRADICTION agent '$agentName' is claude_md but tier '$tier' resolves to '$modelValue' (DeepSeek). Lexosi-enforced: claude_md SIEMPRE tier=high+opus."
            Write-DebugLog "ERROR $errMsg"
            throw $errMsg
        }
        # Normalize claude-opus-* -> "opus" (CC frontmatter short name).
        $resolved = $modelValue
        if ($modelValue -match '^claude-opus') {
            $resolved = "opus"
        }
        Write-DebugLog "model resolved: $agentName (tier=$tier) -> $resolved"
        return [regex]::Replace($Content, '\{\{model\}\}', { param($m) $resolved })
    }
    $modelWarnings = @()

    if (-not (Test-Path -LiteralPath $RuntimeDir)) {
        try {
            New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
        } catch {
            Write-DebugLog "EXIT 3: cannot create runtime dir: $($_.Exception.Message)"
            [Console]::Error.WriteLine("Cannot create runtime dir ${RuntimeDir}: $($_.Exception.Message)")
            exit 3
        }
    }

    $regenCount = 0
    $unresolvedWarnings = @()
    foreach ($tpl in $templateFiles) {
        $content = Get-Content -LiteralPath $tpl.FullName -Raw -Encoding UTF8
        foreach ($ph in $placeholders.Keys) {
            $escaped = [regex]::Escape($ph)
            if ([regex]::IsMatch($content, $escaped)) {
                $val = $placeholders[$ph]
                $content = [regex]::Replace($content, $escaped, { param($m) $val })
            }
        }
        # Resolve {{model}} placeholder via agents.json + models.json (loud failure on contradiction).
        try {
            $content = Resolve-ModelPlaceholder -Content $content -TemplateName $tpl.Name `
                -AgentsCfg $agentsConfig -ModelsCfg $modelsConfig -Warnings ([ref]$modelWarnings)
        } catch {
            Write-DebugLog "EXIT 5: model resolution contradiction in $($tpl.Name): $($_.Exception.Message)"
            [Console]::Error.WriteLine("ERROR model resolution: $($_.Exception.Message)")
            exit 5
        }
        $leftover = [regex]::Matches($content, '\{\{paths\.[a-zA-Z_.-]+\}\}')
        if ($leftover.Count -gt 0) {
            $uniq = ($leftover | ForEach-Object { $_.Value } | Sort-Object -Unique) -join ", "
            $unresolvedWarnings += "$($tpl.Name): $uniq"
            Write-DebugLog "WARN unresolved in $($tpl.Name): $uniq"
        }
        $outPath = Join-Path $RuntimeDir $tpl.Name
        try {
            # CRITICAL: UTF-8 SIN BOM. CC v2.1.14x Windows falla silencioso si .md tiene BOM
            # (primeros bytes EF BB BF rompen YAML frontmatter parser -> agente NO se carga).
            # `Out-File -Encoding utf8` en Windows PowerShell 5.1 ESCRIBE BOM por default.
            # Usar .NET API directa con UTF8Encoding(false) que omite BOM.
            [System.IO.File]::WriteAllText($outPath, $content, [System.Text.UTF8Encoding]::new($false))
            $regenCount++
        } catch {
            Write-DebugLog "EXIT 3: write failed $outPath : $($_.Exception.Message)"
            [Console]::Error.WriteLine("Failed writing ${outPath}: $($_.Exception.Message)")
            exit 3
        }
    }
    Write-DebugLog "regenerated $regenCount files"

    # --- 6.5 Regenerar skills (P5 Hybrid Fase 4) ---
    # Pattern paralelo a agents loop pero nested: agent_templates\skills\<name>\SKILL.md
    # -> .claude\skills\<name>\SKILL.md. Cleanup orphans: dirs runtime no listados en
    # hashset templates names -> Remove-Item -Recurse -Force. Hashset construido ANTES
    # del loop write (mitigacion riesgo borrar skills validos si write fail mid-loop).
    $skillsRegenCount = 0
    $skillsOrphansRemoved = @()
    if (Test-Path -LiteralPath $SkillsTemplatesDir) {
        if (-not (Test-Path -LiteralPath $SkillsRuntimeDir)) {
            try {
                New-Item -ItemType Directory -Force -Path $SkillsRuntimeDir | Out-Null
            } catch {
                Write-DebugLog "EXIT 3: cannot create skills runtime dir: $($_.Exception.Message)"
                [Console]::Error.WriteLine("Cannot create skills runtime dir ${SkillsRuntimeDir}: $($_.Exception.Message)")
                exit 3
            }
        }

        # Build hashset names templates ANTES de write loop (cleanup safety).
        $validSkillNames = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($sk in $skillFiles) {
            [void]$validSkillNames.Add($sk.Directory.Name)
        }

        foreach ($sk in $skillFiles) {
            $skillName = $sk.Directory.Name
            $content = Get-Content -LiteralPath $sk.FullName -Raw -Encoding UTF8
            foreach ($ph in $placeholders.Keys) {
                $escaped = [regex]::Escape($ph)
                if ([regex]::IsMatch($content, $escaped)) {
                    $val = $placeholders[$ph]
                    $content = [regex]::Replace($content, $escaped, { param($m) $val })
                }
            }
            # Resolve-ModelPlaceholder: SKILL.md no contienen `name:` agent-style hoy,
            # asi que sin {{model}} -> early return passthrough. Si en futuro un SKILL.md
            # incluyera {{model}} sin name:, fallaria con warning "cannot extract name:".
            try {
                $content = Resolve-ModelPlaceholder -Content $content -TemplateName "skills\$skillName\SKILL.md" `
                    -AgentsCfg $agentsConfig -ModelsCfg $modelsConfig -Warnings ([ref]$modelWarnings)
            } catch {
                Write-DebugLog "EXIT 5: skill model resolution contradiction in $skillName : $($_.Exception.Message)"
                [Console]::Error.WriteLine("ERROR skill model resolution: $($_.Exception.Message)")
                exit 5
            }
            $leftover = [regex]::Matches($content, '\{\{paths\.[a-zA-Z_.-]+\}\}')
            if ($leftover.Count -gt 0) {
                $uniq = ($leftover | ForEach-Object { $_.Value } | Sort-Object -Unique) -join ", "
                $unresolvedWarnings += "skills\$skillName\SKILL.md: $uniq"
                Write-DebugLog "WARN unresolved in skills\$skillName : $uniq"
            }

            $outSkillDir = Join-Path $SkillsRuntimeDir $skillName
            $outPath = Join-Path $outSkillDir "SKILL.md"
            try {
                if (-not (Test-Path -LiteralPath $outSkillDir)) {
                    New-Item -ItemType Directory -Force -Path $outSkillDir | Out-Null
                }
                # CRITICAL: UTF-8 SIN BOM (mismo invariante que agents).
                [System.IO.File]::WriteAllText($outPath, $content, [System.Text.UTF8Encoding]::new($false))
                $skillsRegenCount++
            } catch {
                Write-DebugLog "EXIT 3: skill write failed $outPath : $($_.Exception.Message)"
                [Console]::Error.WriteLine("Failed writing skill ${outPath}: $($_.Exception.Message)")
                exit 3
            }
        }

        # Cleanup orphans: dirs en runtime no presentes en hashset templates names.
        if (Test-Path -LiteralPath $SkillsRuntimeDir) {
            $runtimeSkillDirs = Get-ChildItem -LiteralPath $SkillsRuntimeDir -Directory -ErrorAction SilentlyContinue
            foreach ($rsd in $runtimeSkillDirs) {
                if (-not $validSkillNames.Contains($rsd.Name)) {
                    try {
                        Remove-Item -LiteralPath $rsd.FullName -Recurse -Force -ErrorAction Stop
                        $skillsOrphansRemoved += $rsd.Name
                        Write-DebugLog "orphan skill dir removed: $($rsd.Name)"
                    } catch {
                        Write-DebugLog "WARN: orphan skill dir remove failed ($($rsd.Name)): $($_.Exception.Message)"
                        [Console]::Error.WriteLine("WARN: orphan skill dir remove failed $($rsd.FullName): $($_.Exception.Message)")
                    }
                }
            }
        }
        Write-DebugLog "skills regenerated: $skillsRegenCount, orphans removed: $($skillsOrphansRemoved.Count)"
    } else {
        Write-DebugLog "skills templates dir absent, skipping skills regen"
    }

    $newState = @{
        paths_json_hash  = $pathsHash
        templates_hash   = $tplHash
        agents_json_hash = $agentsHash
        models_json_hash = $modelsHash
        skills_hash      = $skillsHash
        last_run_iso     = (Get-Date).ToString("o")
        files_generated  = $regenCount
        skills_generated = $skillsRegenCount
    }
    try {
        $newState | ConvertTo-Json -Depth 3 | Out-File -FilePath $StatePath -Encoding utf8 -Force
    } catch {
        Write-DebugLog "WARN: state write failed (non-fatal): $($_.Exception.Message)"
        [Console]::Error.WriteLine("WARN: state write failed: $($_.Exception.Message)")
    }

    $contextLines += "[multiagent-system] regenerated $regenCount agent files (paths.json or templates or agents.json or models.json or skills changed)"
    if ($skillsRegenCount -gt 0) {
        $contextLines += "[multiagent-system] regenerated $skillsRegenCount skill files"
    }
    if ($skillsOrphansRemoved.Count -gt 0) {
        $contextLines += "[multiagent-system] removed $($skillsOrphansRemoved.Count) orphan skill dirs: $($skillsOrphansRemoved -join ', ')"
    }
    if ($unresolvedWarnings.Count -gt 0) {
        $contextLines += "[multiagent-system] WARNING unresolved placeholders in: $($unresolvedWarnings -join '; ')"
    }
    if ($modelWarnings.Count -gt 0) {
        $contextLines += "[multiagent-system] WARNING unresolved {{model}} placeholders in: $($modelWarnings -join '; ')"
    }
}

# --- 7. Curator pending check ---
if (Test-Path -LiteralPath $CuratorPending) {
    try {
        $curRaw = Get-Content -LiteralPath $CuratorPending -Raw -Encoding UTF8
        $cur = $curRaw | ConvertFrom-Json -ErrorAction Stop
        if ($cur.ar_ids -and $cur.ar_ids.Count -gt 0) {
            $arList = $cur.ar_ids -join ", "
            $contextLines += "[multiagent-system] PENDING knowledge-curator runs (final_report.md sin curator_report.md): $arList"
            Write-DebugLog "curator pending: $arList"
        }
        try {
            Remove-Item -LiteralPath $CuratorPending -Force -ErrorAction Stop
        } catch {
            Write-DebugLog "WARN: .curator_pending remove failed: $($_.Exception.Message)"
            $contextLines += "[multiagent-system] WARNING: .curator_pending remove failed ($($_.Exception.Message)) - next session may re-flag same ARs"
        }
    } catch {
        Write-DebugLog "WARN: .curator_pending corrupt or unreadable: $($_.Exception.Message)"
    }
}

# --- 7.5 Model review pending check ---
# Lee cadence desde paths.json (review_cadences.model_allocator_hours, default 72).
# Si .last_model_review mtime >= cadence → flag pending.
try {
    $cadenceHours = $DefaultModelReviewHours
    if ($config -and $config.review_cadences -and $config.review_cadences.model_allocator_hours) {
        try { $cadenceHours = [int]$config.review_cadences.model_allocator_hours } catch { Write-DebugLog "cadence parse failed, using default $DefaultModelReviewHours" }
    }

    $needsReview = $false
    $reviewAgeHours = $null

    if (-not (Test-Path -LiteralPath $LastModelReviewPath)) {
        $needsReview = $true
        Write-DebugLog "model-review: no .last_model_review file → flagging pending"
    } else {
        $lastWrite = (Get-Item -LiteralPath $LastModelReviewPath).LastWriteTime
        $reviewAgeHours = [Math]::Round(((Get-Date) - $lastWrite).TotalHours, 1)
        if ($reviewAgeHours -ge $cadenceHours) {
            $needsReview = $true
            Write-DebugLog "model-review: age $reviewAgeHours h >= cadence $cadenceHours h → flagging pending"
        } else {
            Write-DebugLog "model-review: age $reviewAgeHours h < cadence $cadenceHours h → ok"
        }
    }

    if ($needsReview) {
        $ageMsg = if ($null -eq $reviewAgeHours) { "never run" } else { "last $reviewAgeHours h ago" }
        $contextLines += "[multiagent-system] [MODEL-REVIEW-PENDING] cadence $cadenceHours h ($ageMsg). Invoke `model-allocator` subagent to audit model assignments. Output: docs\model_reviews\MR_<date>.md"
    }
} catch {
    Write-DebugLog "WARN: model-review pending check failed: $($_.Exception.Message)"
}

# --- 7.6 Auditor pending check (P1-A2: backlog agregado → additionalContext, NO delete) ---
# Per-AR flags (.auditor_pending escrito por stop-no-auditor.ps1). NO borra: cleanup = ownership
# de stop-no-auditor (borra al aparecer root_audit_report.md). [*]=target-code vs infra por SEÑAL
# REAL COMBINADA (2 señales OR, validado empírico smoke 2026-06-01):
#   (1) artefacto Verse físico en AR dir (*.verse* snapshot = tocó código Verse target). Captura
#       ARs UEFN viejos que NO citan root absoluto en plan/final_report (FN de señal-2 sola:
#       entity-mult-missing, entity-removable, scaled-entity-reward-rate).
#   (2) plan.md/final_report.md cita ROOT de proyecto target absoluto
#       (<uefn_root>\ | <projects_root>\ | F:\dev-projects\). Captura blender/unreal-py target.
# NO substrings genéricos .verse/Content (prose-FP td-fase-5-1b), NO campo files_changed
# (ausente 76/80 reports), NO git diff per-AR (cutover 05-29 bulk-recover rompe rango).
# Resultado: 0 FP en 9 infra ARs + TP en entity/scaled-entity/blender/uefn/unreal target.
try {
    $arRunsDir = Join-Path $RepoRoot "docs\agent_runs"
    if (Test-Path -LiteralPath $arRunsDir) {
        $pendingDirs = Get-ChildItem -LiteralPath $arRunsDir -Directory -Filter "AR_*" -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ".auditor_pending") }

        if ($pendingDirs.Count -gt 0) {
            $targetRootRe = '(?i)F:[\\/](UEFNProjects|asset-projects|dev-projects)[\\/]'
            $targetCode = @(); $infra = @()
            foreach ($d in $pendingDirs) {
                $isTarget = $false
                # Señal 1: artefacto Verse físico en el AR dir.
                if (Get-ChildItem -LiteralPath $d.FullName -Filter "*.verse*" -File -ErrorAction SilentlyContinue | Select-Object -First 1) {
                    $isTarget = $true
                }
                # Señal 2 (si no Verse): root de proyecto target absoluto en plan/final_report.
                if (-not $isTarget) {
                    foreach ($fn in @("plan.md", "final_report.md")) {
                        $p = Join-Path $d.FullName $fn
                        if (Test-Path -LiteralPath $p) {
                            try {
                                $txt = Get-Content -LiteralPath $p -Raw -Encoding UTF8 -ErrorAction Stop
                                if ($txt -match $targetRootRe) { $isTarget = $true; break }
                            } catch { Write-DebugLog "auditor pending: read failed $($d.Name)/$fn" }
                        }
                    }
                }
                if ($isTarget) { $targetCode += "  [*] $($d.Name)" } else { $infra += "      $($d.Name)" }
            }
            $ordered = @($targetCode) + @($infra)
            $contextLines += "[multiagent-system] [AUDITOR-PENDING] $($pendingDirs.Count) AR sin root_audit_report.md ([*]=toco proyecto target, auditar primero):`n" + ($ordered -join "`n")
            Write-DebugLog "auditor pending: $($pendingDirs.Count) ($($targetCode.Count) target, $($infra.Count) infra)"
        }
    }
} catch {
    Write-DebugLog "WARN: auditor pending check failed: $($_.Exception.Message)"
}

# --- 8. Emit ---
$ctx = if ($contextLines.Count -gt 0) { $contextLines -join "`n" } else { "" }
Write-DebugLog "EXIT 0 (context lines: $($contextLines.Count))"
Emit-AdditionalContext -contextText $ctx -exitCode 0
