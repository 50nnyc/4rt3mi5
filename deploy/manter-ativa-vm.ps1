# Rodada EXTRA do "manter a VM ativa", disparada deste PC em horário sorteado (além do cron da VM).
# Deixa o uso de CPU da VM menos previsível: o cron da VM já sorteia atraso e duração; este aqui soma rodadas
# em horários que nada na VM consegue prever.
#
#   Uma vez na mão (sem esperar):   powershell -ExecutionPolicy Bypass -File deploy\manter-ativa-vm.ps1 -Agora
#   Agendar (de hora em hora):      deploy\manter-ativa-vm.bat   (instala no Agendador de Tarefas)
#
# Em cada hora agendada: sorteia se roda (3 em cada 4 vezes) e quanto espera (0 a 40 min) antes de pedir à VM
# uma rodada curta de CPU (deploy/manter-ativa.sh --extra: 30 a 75 s, prioridade mínima). O SSH volta na hora.
# Nada daqui mostra IP, domínio ou token.
param(
    [switch]$Agora,
    [string]$VmHost = "artemis-vm",
    [string]$Pasta = "4rt3mi5"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $Root "data\manter-ativa-vm.log"   # data/ fica fora do Git
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
function Log([string]$m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

try {
    if (-not $Agora) {
        if ((Get-Random -Minimum 0 -Maximum 4) -eq 0) { Log "Sorteio: esta hora fica sem rodada extra."; exit 0 }
        $espera = Get-Random -Minimum 0 -Maximum 2401   # 0 a 40 min
        Log "Sorteio: rodada extra em $([math]::Round($espera / 60, 1)) min."
        Start-Sleep -Seconds $espera
    }
    $r = & ssh -o BatchMode=yes -o ConnectTimeout=20 $VmHost "~/$Pasta/deploy/manter-ativa.sh --extra"
    if ($LASTEXITCODE -ne 0 -or "$r" -notmatch "ok") { throw "A VM não respondeu (ssh código $LASTEXITCODE)." }
    Log "Rodada extra pedida à VM."
    Write-Host "Rodada extra pedida à VM."
    # o log fica com as últimas 500 linhas
    $linhas = Get-Content $Log -Encoding utf8
    if ($linhas.Count -gt 600) { $linhas | Select-Object -Last 500 | Set-Content $Log -Encoding utf8 }
} catch {
    Log "ERRO: $($_.Exception.Message)"
    Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
