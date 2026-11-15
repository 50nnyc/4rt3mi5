# Envia o 4rt3mi5 deste PC para a VM e (re)liga o servidor lá.
#
#   Atualizar só o código (o uso normal, depois da migração):
#     powershell -ExecutionPolicy Bypass -File deploy\enviar-para-vm.ps1
#
#   Migração (UMA vez): leva também a pasta data\ (banco + server.json) e o .env,
#   desligando o servidor deste PC antes para o banco ir inteiro:
#     powershell -ExecutionPolicy Bypass -File deploy\enviar-para-vm.ps1 -Migrar
#
# Usa o ssh/scp que já vem no Windows 11 e o apelido "artemis-vm" do arquivo %USERPROFILE%\.ssh\config
# (veja deploy\GUIA-VM.md). Nada daqui mostra domínio, IP ou token.
param(
    [switch]$Migrar,
    [string]$VmHost = "artemis-vm",
    [string]$Pasta = "4rt3mi5"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Passo([string]$t) { Write-Host "`n== $t" -ForegroundColor Cyan }

Passo "Testando o SSH ($VmHost)"
& ssh -o BatchMode=yes -o ConnectTimeout=15 $VmHost "echo ok" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Não consegui entrar na VM por SSH. Confira o %USERPROFILE%\.ssh\config (deploy\GUIA-VM.md, passo 3)." }

if ($Migrar) {
    if (-not (Test-Path "data\artemis.db")) { throw "Não achei data\artemis.db neste PC." }
    if (-not (Test-Path "data\server.json")) { throw "Não achei data\server.json (tem a senha do painel e o 'pepper' das senhas: sem ele ninguém consegue entrar)." }
    if (-not (Test-Path ".env")) { throw "Não achei o .env (token e domínio do ngrok)." }
    $resp = & ssh $VmHost "test -f ~/$Pasta/data/artemis.db && echo existe"
    if ($resp -eq "existe") { throw "A VM já tem um banco em ~/$Pasta/data. Para não apagar nada, a migração parou. Se quiser mesmo substituir, renomeie a pasta lá antes." }
    $temDocker = & ssh $VmHost "docker info >/dev/null 2>&1 && echo sim"
    if ($temDocker -ne "sim") { throw "A VM ainda não está com o Docker pronto. Rode antes, na VM:  bash ~/$Pasta/deploy/instalar-vm.sh  (e entre de novo no SSH)." }

    Passo "Desligando o servidor e o ngrok deste PC (o domínio do ngrok só pode estar ativo em um lugar)"
    & docker compose --profile public down
    try { schtasks /Delete /TN "4rt3mi5 vigia" /F | Out-Null; Write-Host "Vigia do Windows removido (ele religaria o servidor daqui)." } catch {}
}

Passo "Empacotando"
$pacote = Join-Path $env:TEMP "artemis-envio.tar.gz"
# Só o que o servidor precisa (lista fixa: rascunhos, ferramentas e arquivos do PC não vão para a VM).
# Atenção: o --exclude do tar do Windows não é ancorado ("data" pegaria também "artemis/data").
$itens = @("Dockerfile", "docker-compose.yml", "requirements-server.txt", ".dockerignore", ".env.example",
           "README.md", "artemis", "deploy")
$tarArgs = @("-czf", $pacote, "--exclude=__pycache__", "--exclude=*.pyc", "--exclude=*.log")
if ($Migrar) {
    $itens += @("data", ".env")
    # O -wal vai junto: se o desligamento não tiver gravado tudo no .db, as últimas alterações estão nele.
    $tarArgs += @("--exclude=data/backups", "--exclude=data/backup-*", "--exclude=*.bundle", "--exclude=data/vigia.json")
}
foreach ($i in $itens) { if (-not (Test-Path $i)) { throw "Faltou '$i' na pasta do projeto." } }
$tarArgs += $itens
& tar.exe @tarArgs
if ($LASTEXITCODE -ne 0) { throw "Falha ao empacotar." }
Write-Host ("Pacote: {0:N1} MB" -f ((Get-Item $pacote).Length / 1MB))

Passo "Enviando para a VM"
& scp -q $pacote "${VmHost}:/tmp/artemis-envio.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "Falha no envio (scp)." }
Remove-Item $pacote -Force

Passo "Instalando e ligando na VM"
# data/: dono = usuário do container (10001), grupo = usuário da VM, para os dois poderem escrever
$remoto = @"
set -e
mkdir -p ~/$Pasta && cd ~/$Pasta
tar --no-overwrite-dir -xzf /tmp/artemis-envio.tar.gz
rm -f /tmp/artemis-envio.tar.gz
find deploy -name '*.sh' -exec sed -i 's/\r$//' {} + && chmod +x deploy/*.sh
mkdir -p data
sudo chown -R 10001:`$(id -g) data && sudo chmod -R g+rwX data && sudo find data -type d -exec chmod g+s {} +
chmod 600 .env 2>/dev/null || true
if ! command -v docker >/dev/null 2>&1; then echo 'FALTA_DOCKER'; exit 0; fi
# Sem banco/.env ainda (antes da migração): não liga, senão nasceria um banco vazio com outra senha
if [ ! -f data/artemis.db ] || [ ! -f .env ]; then echo 'SEM_BANCO'; exit 0; fi
PROF="--profile public"
grep -qE '^\s*SITE_DOMAIN\s*=\s*\S' .env && PROF="`$PROF --profile dominio"
docker compose `$PROF up -d --build
sleep 8
curl -fsS -m 10 http://localhost:8000/api/health >/dev/null && echo 'SERVIDOR_OK' || echo 'SERVIDOR_AINDA_SUBINDO'
"@
# Vai em base64 no argumento: pelo "pipe", o PowerShell 5.1 manda um caractere invisível (BOM) na 1ª linha
$b64 = [Convert]::ToBase64String((New-Object System.Text.UTF8Encoding($false)).GetBytes(($remoto -replace "`r", "")))
$saida = & ssh $VmHost "echo $b64 | base64 -d | bash"
$saida | ForEach-Object { Write-Host $_ }

if ($saida -match "FALTA_DOCKER") {
    Write-Host "`nA VM ainda não tem Docker. Entre nela e rode:  bash ~/$Pasta/deploy/instalar-vm.sh" -ForegroundColor Yellow
    Write-Host "Depois rode este script de novo (sem -Migrar se a pasta data já foi enviada)." -ForegroundColor Yellow
} elseif ($saida -match "SEM_BANCO") {
    Write-Host "`nCódigo enviado. O servidor não foi ligado porque a VM ainda não tem o banco: rode com -Migrar." -ForegroundColor Yellow
} elseif ($saida -match "SERVIDOR_OK") {
    Write-Host "`nPronto: o servidor está no ar na VM." -ForegroundColor Green
} else {
    Write-Host "`nO servidor ainda está subindo. Confira em 1 minuto:  ssh $VmHost 'cd $Pasta && docker compose logs --tail 50'" -ForegroundColor Yellow
}
