#requires -Version 5.1
# probe_matching_logic.ps1 — Fase 5.1b matching bug probe
# Tests H1-H5 hypothesis isolated. Output JSON per H verdict.

$ErrorActionPreference = "Continue"

$PhrasesPath = "F:\multiagent-system\scripts\metrics\distinctive_phrases.json"
# NOTE: SampleJsonl points to a specific historical dev session (pre-cutover 2026-05-29).
# Path obsolete post-cutover (F--multiagent-system-dev deleted). Update before re-run with a
# current session JSONL from %USERPROFILE%\.claude\projects\F--multiagent-system\<sid>\subagents\.
$SampleJsonl = "$env:USERPROFILE\.claude\projects\F--multiagent-system-dev\1a8f2e48-06e2-4ef2-a866-5d14d474b197\subagents\agent-a0044dd045772e335.jsonl"
$TargetSkill = "planner-uefn"

Write-Output "===== Fase 5.1b matching probe ====="
Write-Output ""

# --- H1: ConvertFrom-Json -AsHashtable vs PSCustomObject iteration ---
Write-Output "=== H1: PSCustomObject vs Hashtable iteration ==="
$raw = Get-Content -LiteralPath $PhrasesPath -Raw -Encoding UTF8

# Method A: regular ConvertFrom-Json (PSCustomObject)
$pscustom = $raw | ConvertFrom-Json
Write-Output "  PSCustomObject keys via PSObject.Properties:"
$keys_pscustom = @($pscustom.PSObject.Properties.Name)
Write-Output "    count: $($keys_pscustom.Count)"
Write-Output "    first 3: $($keys_pscustom[0..2] -join ', ')"

# Method B: -AsHashtable (PS 6+ only — may fail PS 5.1)
$ashashtable_works = $false
try {
    $hashtable = $raw | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    $ashashtable_works = $true
    $keys_ht = @($hashtable.Keys)
    Write-Output "  Hashtable keys via .Keys:"
    Write-Output "    count: $($keys_ht.Count)"
} catch {
    Write-Output "  -AsHashtable FAILED: $_"
}

# Test PSCustomObject dynamic property access with HYPHEN
Write-Output "  PSCustomObject access via dot.access ('.$TargetSkill'):"
$phrases_dot = $pscustom.$TargetSkill
Write-Output "    type: $($phrases_dot.GetType().Name), count: $($phrases_dot.Count)"

# Test via PSObject.Properties[].Value
Write-Output "  PSCustomObject access via PSObject.Properties:"
$phrases_props = $pscustom.PSObject.Properties[$TargetSkill].Value
Write-Output "    type: $($phrases_props.GetType().Name), count: $($phrases_props.Count)"

Write-Output ""

# --- H5: Response text extraction ---
Write-Output "=== H5: Response text extraction ==="
$responseText = ""
$msgCount = 0
$textBlocks = 0
Get-Content -LiteralPath $SampleJsonl -Encoding UTF8 | ForEach-Object {
    if ([string]::IsNullOrWhiteSpace($_)) { return }
    try {
        $obj = $_ | ConvertFrom-Json -ErrorAction Stop
        $msg = $obj.message
        if ($msg -and $msg.role -eq "assistant") {
            $msgCount++
            foreach ($block in $msg.content) {
                if ($block.type -eq "text") {
                    $textBlocks++
                    $responseText += $block.text + " "
                }
            }
        }
    } catch {}
}
Write-Output "  assistant_messages: $msgCount"
Write-Output "  text_blocks: $textBlocks"
Write-Output "  responseText length: $($responseText.Length)"
Write-Output "  first 200 chars: $($responseText.Substring(0, [Math]::Min(200, $responseText.Length)))"
Write-Output ""

# --- H2: .Contains() vs IndexOf OrdinalIgnoreCase ---
Write-Output "=== H2+H3: Matching method comparison ==="
$phrases = $pscustom.$TargetSkill
foreach ($phrase in $phrases) {
    $contains_default = $responseText.Contains($phrase)
    $contains_ord_ic = $responseText.IndexOf($phrase, [StringComparison]::OrdinalIgnoreCase) -ge 0
    $contains_ord = $responseText.IndexOf($phrase, [StringComparison]::Ordinal) -ge 0
    Write-Output "  phrase: '$phrase'"
    Write-Output "    .Contains():           $contains_default"
    Write-Output "    IndexOf Ordinal:       $contains_ord"
    Write-Output "    IndexOf OrdinalIgnoreCase: $contains_ord_ic"
}
Write-Output ""

# --- H4: Path resolution ---
Write-Output "=== H4: Path resolution test ==="
$ProjectsBase = Join-Path $env:USERPROFILE ".claude\projects\F--multiagent-system"
$session = "1a8f2e48-06e2-4ef2-a866-5d14d474b197"
$agentId = "a0044dd045772e335"
$path_test = Join-Path (Join-Path (Join-Path $ProjectsBase $session) "subagents") "agent-$agentId.jsonl"
Write-Output "  constructed path: $path_test"
Write-Output "  Test-Path: $(Test-Path -LiteralPath $path_test)"

Write-Output ""
Write-Output "===== Probe done ====="
exit 0
