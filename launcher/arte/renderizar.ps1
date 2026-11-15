# Gera launcher\arte\fundo.png (1720x1040) a partir de fundo.html, usando o Edge sem janela.
# Só precisa rodar de novo se mudar a arte. Depois, recompile o launcher (build-launcher.ps1).
$ErrorActionPreference = "Stop"
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge não encontrado." }
$html = "file:///" + ((Join-Path $PSScriptRoot "fundo.html") -replace '\\', '/')
$out = Join-Path $PSScriptRoot "fundo.png"
$perfil = Join-Path $env:TEMP "artemis-edge-arte"
Remove-Item $out -ErrorAction SilentlyContinue
& $edge --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$perfil" --force-device-scale-factor=2 `
    --window-size=860,520 --virtual-time-budget=8000 --screenshot="$out" $html 2>$null
for ($i = 0; $i -lt 30 -and -not (Test-Path $out); $i++) { Start-Sleep -Milliseconds 500 }
if (-not (Test-Path $out)) { throw "O Edge não gerou o PNG." }
Write-Host "Arte gerada: $out"
