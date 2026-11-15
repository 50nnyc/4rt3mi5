# Compila o launcher (launcher\4rt3mi5-Launcher.exe) com o csc do .NET Framework 4, que já vem no Windows.
#
# ATENÇÃO: o launcher é CONGELADO de propósito. Cada compilação gera bytes diferentes, e bytes diferentes
# perdem a reputação do SmartScreen (o aviso "O Windows protegeu o computador" volta). Só recompile se for
# realmente necessário; depois envie o arquivo novo para a Microsoft e para o VirusTotal outra vez.
#
# Uso:  powershell -ExecutionPolicy Bypass -File launcher\build-launcher.ps1 [-Saida caminho.exe]
param([string]$Saida = "")
$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$raiz = Split-Path $dir -Parent
if (-not $Saida) { $Saida = Join-Path $dir "4rt3mi5-Launcher.exe" }
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe" }
if (-not (Test-Path $csc)) { throw "csc.exe do .NET Framework 4 não encontrado." }

$fundo = Join-Path $dir "arte\fundo.png"
if (-not (Test-Path $fundo)) { throw "Falta a arte: rode launcher\arte\renderizar.ps1" }

# Ícone (.ico) a partir do ícone do app, com vários tamanhos em PNG dentro
Add-Type -AssemblyName System.Drawing
$ico = Join-Path $env:TEMP "artemis-launcher.ico"
$src = [System.Drawing.Image]::FromFile((Join-Path $raiz "artemis\web\icon-512.png"))
$tamanhos = 256, 64, 48, 32, 16
$pngs = foreach ($t in $tamanhos) {
    $bmp = New-Object System.Drawing.Bitmap $t, $t
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = "HighQualityBicubic"; $g.SmoothingMode = "AntiAlias"; $g.PixelOffsetMode = "HighQuality"
    $g.DrawImage($src, 0, 0, $t, $t); $g.Dispose()
    $ms = New-Object IO.MemoryStream; $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    , $ms.ToArray()
}
$src.Dispose()
$fs = [IO.File]::Create($ico); $bw = New-Object IO.BinaryWriter $fs
$bw.Write([UInt16]0); $bw.Write([UInt16]1); $bw.Write([UInt16]$tamanhos.Count)
$offset = 6 + 16 * $tamanhos.Count
for ($i = 0; $i -lt $tamanhos.Count; $i++) {
    $t = $tamanhos[$i]; $b = if ($t -ge 256) { 0 } else { $t }
    $bw.Write([byte]$b); $bw.Write([byte]$b); $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([UInt16]1); $bw.Write([UInt16]32); $bw.Write([UInt32]$pngs[$i].Length); $bw.Write([UInt32]$offset)
    $offset += $pngs[$i].Length
}
foreach ($p in $pngs) { $bw.Write($p) }
$bw.Close()

& $csc /nologo /target:winexe /optimize+ /platform:anycpu /codepage:65001 `
    "/out:$Saida" "/win32icon:$ico" "/win32manifest:$(Join-Path $dir 'app.manifest')" `
    "/resource:$fundo,fundo.png" /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll `
    (Join-Path $dir "Launcher.cs")
if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar o launcher." }
$sha = (Get-FileHash $Saida -Algorithm SHA256).Hash.ToLower()
Write-Host "Launcher: $Saida"
Write-Host "SHA-256:  $sha"
