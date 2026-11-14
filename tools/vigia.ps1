# Vigia do 4rt3mi5: confere se o site responde no PC (localhost) e pela internet (ngrok).
# Roda pelo Agendador de Tarefas do Windows a cada 5 minutos (instale com vigia.bat).
#  - Servidor local parado  -> tenta "docker compose --profile public up -d".
#  - So o ngrok sem responder -> tenta reiniciar o container do ngrok.
#  - Continuou fora do ar     -> notificacao do Windows. Quando volta, outra notificacao.
# O resultado fica em data/vigia.json (o painel /admin mostra) e o historico em data/vigia.log.
# Nada aqui mostra o dominio do ngrok nem o token: os dois ficam so no arquivo .env.
param([switch]$Teste)

$Root = Split-Path -Parent $PSScriptRoot
$Data = Join-Path $Root "data"
$StatusFile = Join-Path $Data "vigia.json"
$LogFile = Join-Path $Data "vigia.log"
New-Item -ItemType Directory -Force -Path $Data | Out-Null

function Log([string]$msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Get-NgrokDomain {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) { return $null }
    $line = Get-Content $envFile | Where-Object { $_ -match '^\s*NGROK_DOMAIN\s*=' } | Select-Object -First 1
    if (-not $line) { return $null }
    $d = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    return ($d -replace '^https?://', '' -replace '/+$', '')
}

function Test-Health([string]$url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15 -Headers @{ "ngrok-skip-browser-warning" = "1" }
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Show-Notification([string]$title, [string]$text) {
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        $t = [System.Security.SecurityElement]::Escape($title)
        $b = [System.Security.SecurityElement]::Escape($text)
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show(
            [Windows.UI.Notifications.ToastNotification]::new($xml))
    } catch {
        Log "Falha ao mostrar notificação: $($_.Exception.Message)"
    }
}

function Invoke-Compose([string[]]$composeArgs) {
    Push-Location $Root
    try {
        & docker compose --profile public @composeArgs *> $null
        Log "docker compose $($composeArgs -join ' ') -> código $LASTEXITCODE"
    } catch {
        Log "Não consegui rodar o docker: $($_.Exception.Message)"
    } finally { Pop-Location }
}

if ($Teste) {
    Show-Notification "4rt3mi5 · vigia instalado" "Vou conferir o site a cada 5 minutos e avisar aqui se ele sair do ar."
}

$domain = Get-NgrokDomain
$localUrl = "http://localhost:8000/api/health"
$publicUrl = if ($domain) { "https://$domain/api/health" } else { $null }

$local = Test-Health $localUrl
$public = if ($publicUrl) { Test-Health $publicUrl } else { $null }
$fix = $null

if (-not $local) {
    $fix = "servidor reiniciado"
    Log "Servidor local não respondeu: subindo os containers."
    Invoke-Compose @("up", "-d")
    Start-Sleep -Seconds 45
    $local = Test-Health $localUrl
    if ($publicUrl) { $public = Test-Health $publicUrl }
} elseif ($public -eq $false) {
    $fix = "ngrok reiniciado"
    Log "Site pela internet não respondeu: reiniciando o ngrok."
    Invoke-Compose @("restart", "ngrok")
    Start-Sleep -Seconds 25
    $public = Test-Health $publicUrl
}

$ok = $local -and ($public -ne $false)
$message = if ($ok) { "Tudo certo" }
           elseif (-not $local) { "O servidor no PC não responde (o Docker está aberto?)" }
           else { "O servidor responde no PC, mas não pela internet (ngrok)" }

$prev = $null
if (Test-Path $StatusFile) {
    try { $prev = Get-Content $StatusFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $prev = $null }
}
$now = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
$downSince = $null
if (-not $ok) {
    $downSince = if ($prev -and -not $prev.ok -and $prev.down_since) { $prev.down_since } else { $now }
}

$status = [ordered]@{
    checked_at = $now; ok = $ok; local = $local; public = $public
    message = $message; down_since = $downSince; last_fix = $fix
}
($status | ConvertTo-Json) | Out-File -FilePath $StatusFile -Encoding utf8

$wasOk = (-not $prev) -or $prev.ok
if (-not $ok -and $wasOk) {
    Log "FORA DO AR: $message"
    Show-Notification "4rt3mi5 fora do ar" "$message. Tentei arrumar sozinho e não deu; confira o Docker."
} elseif ($ok -and -not $wasOk) {
    Log "Voltou ao ar."
    Show-Notification "4rt3mi5 voltou ao ar" "O site respondeu de novo (no PC e pela internet)."
} elseif ($fix -and $ok) {
    Log "Estava fora do ar e voltou depois de: $fix."
}
