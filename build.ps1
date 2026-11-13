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
python -m PyInstaller --noconfirm --clean --windowed --name 4rt3mi5 `
    --add-data "artemis/web;web" --exclude-module fastapi --exclude-module uvicorn run_desktop.py
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
if (-not $DownloadBaseUrl) { $DownloadBaseUrl = "https://github.com/SEU_USUARIO/4rt3mi5/releases/download/v$version" }
$manifest = [ordered]@{
    version = $version
    url     = "$DownloadBaseUrl/4rt3mi5-Setup-$version.exe"
    sha256  = $sha
    notes   = ""
}
$manifest | ConvertTo-Json | Out-File -Encoding utf8 dist\latest.json
Write-Host "Pronto: $setup"
Write-Host "Manifesto: dist\latest.json"
