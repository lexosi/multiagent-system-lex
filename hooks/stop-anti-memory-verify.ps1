<#
.SYNOPSIS
    Stop hook reactivo - enforcement anti-memoria (capa dura). Detecta cuando
    <user> pego una ruta de captura (<captures_dir>\*.png) en su ULTIMO
    mensaje real y el asistente NO la verifico (ni Read del .png ni delegacion
    a subagente-dueno) antes de terminar el turno. Si es asi, emite un BLOCK
    (decision=block) para forzar la verificacion. Anti-memoria: prohibido
    afirmar sobre una captura sin haberla leido o delegado.

.DESCRIPTION
    Trigger: Stop event (cada turn end CC v2.1.146).

    Firma detectada (CONFIRMADA empiricamente en PROBE step 9 del AR):
      1. Payload stdin JSON trae transcript_path (+ session_id).
      2. El transcript .jsonl tiene 1 entry JSON por linea.
      3. El ULTIMO mensaje REAL de usuario (type=="user" && message.role=="user"
         con content string O array con algun bloque type=="text") contiene una
         ruta "<captures_dir>\<algo>.png". Los entries type=="user" cuyo content son
         SOLO bloques type=="tool_result" son ecos de tool, NO mensajes de <user>
         -> se DESCARTAN (en un transcript aparecieron 194 entries type=="user"
         y la mayoria eran tool_result).
      4. SATISFECHO (no viola) si DESPUES de ese user-real hay:
           - un tool_use name=="Read" cuyo input.file_path termina en el basename
             de alguna captura, O
           - un tool_use name=="Agent" (CC v2.1.146; "Task" por compat) cuyo input
             (prompt o cualquier string) contiene el basename o el substring
             "<captures_dir>" (delegacion al subagente-dueno).
      5. VIOLACION = captura en el ultimo user-real Y ni Read ni delegacion posterior.

    Dedup one-shot (ANTI-LOOP, critico): un Stop hook que re-bloquea el mismo turno
    entraria en loop infinito y brickearia la sesion. signature = session_id +
    identificador-unico-del-user-real (uuid > timestamp > hash del texto). State
    file hooks\.anti_memory_state (append-only, 1 signature por linea). Si la
    signature YA existe -> exit 0 (ya se aviso una vez, NO re-bloquear). Si no
    existe -> append + emitir BLOCK una sola vez.

    NO registrado aun en settings.json (eso es step 12, gate aparte). Este archivo
    solo se crea; su activacion es una decision separada.

    Cross-ref: AR_2026-07-02_anti-memory-verification-gate,
    briefs/ANTI_MEMORY_VERIFICATION.md, RFC #45427.

.NOTES
    Exit 0 SIEMPRE (Stop hook contract). El BLOCK lo hace el JSON de stdout, NO el
    exit code. Fail-open TOTAL: trap { exit 0 } + try/catch por-linea; ningun path
    hace exit != 0 ni lanza.
    Invariante PS5.1: ASCII-only (cero acentos / cero em-dash / cero no-ASCII en
    todo el archivo, comentarios incluidos) + sin BOM. State/log escritos con
    Add-Content -Encoding ascii.
    Debug: $env:MULTIAGENT_HOOKS_DEBUG = "1" -> hooks\.debug.log
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
trap { exit 0 }

# --- Bootstrap paths (mismo patron que stop-no-auditor.ps1) ---
$PathsJson = if ($env:MULTIAGENT_PATHS_CONFIG -and (Test-Path -LiteralPath $env:MULTIAGENT_PATHS_CONFIG)) {
    $env:MULTIAGENT_PATHS_CONFIG
} else {
    "<repo_root>\config\paths.json"
}

$RepoRoot   = Split-Path -Parent (Split-Path -Parent $PathsJson)
$StateFile  = Join-Path $RepoRoot "hooks\.anti_memory_state"
$ActionLog  = Join-Path $RepoRoot "hooks\.anti_memory.log"
$DebugMode  = $env:MULTIAGENT_HOOKS_DEBUG -eq "1"

function Write-DebugLog($msg) {
    if (-not $DebugMode) { return }
    try {
        $logPath = Join-Path $RepoRoot "hooks\.debug.log"
        $timestamp = (Get-Date).ToString("o")
        Add-Content -Path $logPath -Value "[$timestamp] [stop-anti-memory-verify.ps1] $msg" -ErrorAction SilentlyContinue
    } catch {}
}

function Write-ActionLog($msg) {
    try {
        $timestamp = (Get-Date).ToString("o")
        Add-Content -Path $ActionLog -Value "[$timestamp] $msg" -Encoding ascii -ErrorAction SilentlyContinue
    } catch {}
}

# --- Consume stdin + extraer transcript_path y session_id ---
$TranscriptPath = ""
$SessionId      = ""
try {
    $stdinRaw = [Console]::In.ReadToEnd()
    if ($stdinRaw -and $stdinRaw.Trim().Length -gt 0) {
        $payload = $stdinRaw | ConvertFrom-Json -ErrorAction Stop
        if ($payload.transcript_path) { $TranscriptPath = [string]$payload.transcript_path }
        if ($payload.session_id)      { $SessionId      = [string]$payload.session_id }
    }
} catch {
    Write-DebugLog "stdin parse failed (fail-open): $($_.Exception.Message)"
    exit 0
}

Write-DebugLog "ENTRY transcript_path='$TranscriptPath' session_id='$SessionId'"

# Passthrough: sin transcript_path o archivo inexistente.
if ([string]::IsNullOrWhiteSpace($TranscriptPath)) {
    Write-DebugLog "transcript_path vacio; passthrough"
    exit 0
}
if (-not (Test-Path -LiteralPath $TranscriptPath)) {
    Write-DebugLog "transcript_path no existe; passthrough"
    exit 0
}

# --- Leer el .jsonl entero (1 entry JSON por linea) ---
$lines = @()
try {
    $lines = [System.IO.File]::ReadAllLines($TranscriptPath)
} catch {
    Write-DebugLog "ReadAllLines fallo; passthrough: $($_.Exception.Message)"
    exit 0
}
if ($lines.Count -eq 0) { exit 0 }

# --- Regex captura <captures_dir>\<basename>.png ---
# Tras ConvertFrom-Json los backslashes ya estan des-escapados a '\' literal.
# La clase de caracteres excluye separadores -> group(1) es un unico segmento (basename).
$capRegex = [regex]::new('<captures_dir>[\\/]+([^\\/":<>|?*]+\.png)', 'IgnoreCase')

# --- Pase unico: localizar ultimo user-real + recolectar tool_use de assistant ---
$lastUserIdx  = -1
$lastUserId   = ""
$lastUserText = ""
$asstActions  = New-Object System.Collections.ArrayList

for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ([string]::IsNullOrWhiteSpace($line)) { continue }

    $obj = $null
    try {
        $obj = $line | ConvertFrom-Json -ErrorAction Stop
    } catch {
        # Linea corrupta: se salta.
        continue
    }
    if ($null -eq $obj) { continue }

    $etype = [string]$obj.type

    # --- Mensaje de usuario real ---
    if ($etype -eq "user" -and $obj.message -and ([string]$obj.message.role -eq "user")) {
        $content = $obj.message.content
        $isReal  = $false
        $text    = ""
        if ($content -is [string]) {
            $isReal = $true
            $text   = $content
        } elseif ($null -ne $content) {
            # Array de bloques: real solo si hay algun bloque type=="text".
            foreach ($blk in $content) {
                if ($null -eq $blk) { continue }
                $btype = [string]$blk.type
                if ($btype -eq "text") {
                    $isReal = $true
                    if ($blk.text) { $text += ([string]$blk.text) + "`n" }
                }
            }
        }
        if ($isReal) {
            $lastUserIdx  = $i
            $lastUserText = $text
            if ($obj.uuid)           { $lastUserId = [string]$obj.uuid }
            elseif ($obj.timestamp)  { $lastUserId = [string]$obj.timestamp }
            else                     { $lastUserId = "" }  # hash diferido si hace falta
        }
        continue
    }

    # --- Acciones del asistente (tool_use) ---
    if ($etype -eq "assistant" -and $obj.message) {
        $content = $obj.message.content
        if ($null -ne $content -and -not ($content -is [string])) {
            foreach ($blk in $content) {
                if ($null -eq $blk) { continue }
                if ([string]$blk.type -eq "tool_use") {
                    [void]$asstActions.Add([pscustomobject]@{
                        Idx   = $i
                        Name  = [string]$blk.name
                        Input = $blk.input
                    })
                }
            }
        }
        continue
    }
}

# Passthrough: no hay mensaje de usuario real.
if ($lastUserIdx -lt 0) {
    Write-DebugLog "sin user-real; passthrough"
    exit 0
}

# --- Extraer basenames de captura del ultimo user-real ---
$captureBasenames = New-Object System.Collections.Generic.HashSet[string]
foreach ($m in $capRegex.Matches($lastUserText)) {
    if ($m.Groups.Count -ge 2) {
        $bn = $m.Groups[1].Value.ToLower()
        if (-not [string]::IsNullOrWhiteSpace($bn)) { [void]$captureBasenames.Add($bn) }
    }
}

if ($captureBasenames.Count -eq 0) {
    Write-DebugLog "sin captura en user-real; passthrough"
    exit 0
}
Write-DebugLog "capturas en user-real: $($captureBasenames -join ', ')"

# --- Escanear acciones posteriores al user-real: Read o delegacion satisfacen ---
$satisfied = $false
foreach ($act in $asstActions) {
    if ($act.Idx -le $lastUserIdx) { continue }
    if ($null -eq $act.Input)      { continue }

    $name = $act.Name

    # SATISFECHO por Read del .png (match por basename, case-insensitive).
    if ($name -eq "Read" -and $act.Input.file_path) {
        $fp = ([string]$act.Input.file_path).ToLower().Replace('\', '/')
        foreach ($bn in $captureBasenames) {
            if ($fp.EndsWith($bn)) { $satisfied = $true; break }
        }
        if ($satisfied) { break }
    }

    # SATISFECHO por delegacion (Agent / Task): input contiene basename o "<captures_dir>".
    if ($name -eq "Agent" -or $name -eq "Task") {
        $inputStr = ""
        try {
            $inputStr = ($act.Input | ConvertTo-Json -Compress -Depth 20 -ErrorAction SilentlyContinue)
        } catch { $inputStr = "" }
        if ($inputStr) {
            $inputLower = $inputStr.ToLower()
            if ($inputLower.Contains("<captures_dir>")) { $satisfied = $true; break }
            foreach ($bn in $captureBasenames) {
                if ($inputLower.Contains($bn)) { $satisfied = $true; break }
            }
            if ($satisfied) { break }
        }
    }
}

if ($satisfied) {
    Write-DebugLog "verificacion satisfecha (Read o delegacion); passthrough"
    exit 0
}

# --- VIOLACION detectada: dedup one-shot antes de bloquear (anti-loop) ---

# Identificador unico del user-real: uuid/timestamp; fallback hash del texto.
$userUid = $lastUserId
if ([string]::IsNullOrWhiteSpace($userUid)) {
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($lastUserText)
        $hash = $sha.ComputeHash($bytes)
        $userUid = "h_" + ([System.BitConverter]::ToString($hash)).Replace("-", "").Substring(0, 16)
        $sha.Dispose()
    } catch {
        $userUid = "idx_$lastUserIdx"
    }
}

$signature = "$SessionId|$userUid"

# Ya avisado antes para este mismo turno -> NO re-bloquear (evita loop infinito).
$alreadyFlagged = $false
try {
    if (Test-Path -LiteralPath $StateFile) {
        $existing = [System.IO.File]::ReadAllLines($StateFile)
        foreach ($s in $existing) {
            if ($s -eq $signature) { $alreadyFlagged = $true; break }
        }
    }
} catch {
    Write-DebugLog "lectura state file fallo (fail-open, no bloquea de nuevo): $($_.Exception.Message)"
    exit 0
}

if ($alreadyFlagged) {
    Write-DebugLog "signature ya en state file; NO re-bloquear (one-shot): $signature"
    exit 0
}

# Registrar signature (append-only) ANTES de emitir el block.
try {
    Add-Content -Path $StateFile -Value $signature -Encoding ascii -ErrorAction Stop
} catch {
    # Si no puedo persistir la signature, NO bloqueo (evita loop si el write falla siempre).
    Write-DebugLog "append state file fallo; passthrough para evitar loop: $($_.Exception.Message)"
    exit 0
}

# --- Emitir BLOCK (el bloqueo lo hace el JSON de stdout, luego exit 0) ---
$bnList = ($captureBasenames -join ", ")
$reason = "<user> pego ruta(s) de captura ($bnList) en su ultimo mensaje. Read la captura O delegala al subagente-dueno por tipo (Verse->specialist-verse, UE->specialist-unreal, Blender->specialist-blender) ANTES de afirmar nada sobre ella. Anti-memoria capa dura: briefs/ANTI_MEMORY_VERIFICATION.md."

Write-ActionLog "BLOCK session=$SessionId uid=$userUid capturas='$bnList'"
Write-DebugLog "BLOCK emitido: $signature (capturas='$bnList')"

$out = @{ decision = "block"; reason = $reason } | ConvertTo-Json -Compress
[Console]::Out.Write($out)
exit 0
