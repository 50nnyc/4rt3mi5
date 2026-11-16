# Gera o executável (PyInstaller) e o instalador (Inno Setup) do app desktop.
# Uso:  .\build.ps1
# Saída: dist\4rt3mi5-Setup-<versão>.exe  e  dist\latest.json
param([string]$DownloadBaseUrl = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Test-Path .venv\Scripts\python.exe) { Set-Alias python (Resolve-Path .venv\Scripts\python.exe) }

$version = (python -c "import artemis; print(artemis.__version__)").Trim()
Write-Host "Versao: $version"

python -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { throw "Testes falharam" }

# O app desktop leva junto a interface (artemis/web) e abre numa janela WebView2.
# --icon: ícone do .exe (área de trabalho, menu Iniciar e barra de tarefas); o .ico vai junto para a janela.
python -m PyInstaller --noconfirm --clean --windowed --name 4rt3mi5 --icon artemis/desktop/4rt3mi5.ico `
    --add-data "artemis/web;web" --add-data "artemis/desktop/4rt3mi5.ico;." --exclude-module fastapi --exclude-module uvicorn run_desktop.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) { throw "Inno Setup nao encontrado. Instale com: winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou" }

$setup = "dist\4rt3mi5-Setup-$version.exe"
$sha = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
if (-not $DownloadBaseUrl) { $DownloadBaseUrl = "https://github.com/50nnyc/4rt3mi5/releases/download/v$version" }
# Launcher congelado (launcher\4rt3mi5-Launcher.exe): vai junto em toda Release, sempre com os mesmos bytes.
# Se alguém recompilar sem querer, o hash muda e a reputação do SmartScreen se perde: aqui isso trava o build.
$launcher = "launcher\4rt3mi5-Launcher.exe"
$launcherSha = (Get-FileHash $launcher -Algorithm SHA256).Hash.ToLower()
$esperado = ((Get-Content launcher\SHA256.txt -TotalCount 1) -split '\s+')[0].ToLower()
if ($launcherSha -ne $esperado) { throw "launcher\4rt3mi5-Launcher.exe mudou ($launcherSha), mas launcher\SHA256.txt diz $esperado." }
Copy-Item $launcher dist\4rt3mi5-Launcher.exe -Force
$manifest = [ordered]@{
    version         = $version
    url             = "$DownloadBaseUrl/4rt3mi5-Setup-$version.exe"
    sha256          = $sha
    launcher_sha256 = $launcherSha
    notes           = ""
}
$manifest | ConvertTo-Json | Out-File -Encoding utf8 dist\latest.json
Write-Host "Pronto: $setup"
Write-Host "Manifesto: dist\latest.json"
