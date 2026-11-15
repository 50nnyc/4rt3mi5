# Traz para este PC o backup mais novo do banco que está na VM (cópia fora da nuvem).
# O servidor já faz um backup por dia em data/backups na VM; se a VM sumir, eles somem junto.
# Este script copia o mais novo para backup-vm\ neste PC e guarda os 30 mais recentes.
#
#   Uma vez na mão:     powershell -ExecutionPolicy Bypass -File deploy\puxar-backup.ps1
#   Todo dia sozinho:   deploy\puxar-backup.bat   (instala no Agendador de Tarefas)
param(
    [string]$VmHost = "artemis-vm",
    [string]$Pasta = "4rt3mi5",
    [int]$Guardar = 30
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Destino = Join-Path $Root "backup-vm"   # backup*/ já está no .gitignore
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$Log = Join-Path $Destino "puxar-backup.log"
function Log([string]$m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

try {
    $nome = (& ssh -o BatchMode=yes -o ConnectTimeout=20 $VmHost "ls -1 ~/$Pasta/data/backups/artemis-*.db 2>/dev/null | sort | tail -n1").Trim()
    if (-not $nome) { throw "Nenhum backup encontrado na VM (o servidor faz o primeiro na primeira hora no ar)." }
    $arquivo = Split-Path -Leaf $nome
    $local = Join-Path $Destino $arquivo
    if (Test-Path $local) { Log "Já tinha $arquivo."; Write-Host "Já tinha $arquivo."; exit 0 }
    & scp -q -o BatchMode=yes "${VmHost}:$nome" $local
    if ($LASTEXITCODE -ne 0) { throw "Falha no scp." }
    Get-ChildItem $Destino -Filter "artemis-*.db" | Sort-Object Name -Descending | Select-Object -Skip $Guardar | Remove-Item -Force
    Log "Copiado $arquivo ($([math]::Round((Get-Item $local).Length / 1MB, 1)) MB)."
    Write-Host "Backup copiado: $local"
} catch {
    Log "ERRO: $($_.Exception.Message)"
    Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
