# Dispara a varredura de highscores agora, dentro da VM (sem esperar as 09h).
# Usa o token de admin de data\server.json deste PC e a conexão SSH "artemis-vm" (deploy\GUIA-VM.md).
# Pode levar até ~40 minutos (são 90 mundos). Não duplica o dia: a comparação é sempre com o último valor guardado.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$cfg = Get-Content "data\server.json" -Raw | ConvertFrom-Json
$tok = $cfg.admin_token
if (-not $tok) { throw "Não achei o admin_token em data\server.json." }

Write-Host "Disparando a varredura na VM (pode levar até ~40 minutos)..." -ForegroundColor Cyan
$remoto = "curl -fsS -m 3000 -X POST http://localhost:8000/api/admin/xp-snapshot -H 'X-Admin-Token: $tok'"
$b64 = [Convert]::ToBase64String((New-Object System.Text.UTF8Encoding($false)).GetBytes($remoto))
$saida = & ssh -o BatchMode=yes -o ServerAliveInterval=60 artemis-vm "echo $b64 | base64 -d | bash"
if ($LASTEXITCODE -ne 0) { throw "A varredura não respondeu. Confira a conexão com a VM (deploy\GUIA-VM.md)." }
Write-Host "Resposta da VM:" -ForegroundColor Green
$saida
