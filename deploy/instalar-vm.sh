#!/usr/bin/env bash
# Prepara uma VM Ubuntu nova (Oracle Cloud "Always Free" ou outra) para rodar o 4rt3mi5.
# Roda UMA vez, na VM, como o usuário normal (ubuntu):   bash ~/4rt3mi5/deploy/instalar-vm.sh
#
# O que faz:
#   - atualiza o sistema e liga as atualizações de segurança automáticas
#   - cria memória swap se a máquina tiver menos de 2 GB de RAM
#   - instala o Docker (script oficial) e deixa o usuário usar sem sudo
#   - coloca o fuso horário de Brasília
#   - agenda o vigia (deploy/vigia.sh) a cada 5 minutos no cron
#   - agenda o deploy/manter-ativa.sh (evita a Oracle recolher a VM por ociosidade)
# Não abre porta nenhuma: o acesso de fora é pelo ngrok (conexão de saída). Só o SSH fica aberto.
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "== 4rt3mi5: preparando a VM (projeto em $PROJ)"

sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates unattended-upgrades sqlite3
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

sudo timedatectl set-timezone America/Sao_Paulo

# Swap: só nas máquinas pequenas (ex.: a VM.Standard.E2.1.Micro de 1 GB)
mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if [ "$mem_kb" -lt 2000000 ] && ! swapon --show | grep -q .; then
  echo "== Pouca memória: criando swap de 2 GB"
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "== Instalando o Docker"
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker

# Vigia a cada 5 minutos (substitui o vigia.bat do Windows)
chmod +x "$PROJ/deploy/"*.sh
linha="*/5 * * * * $PROJ/deploy/vigia.sh >/dev/null 2>&1"
# (crontab -l dá erro quando ainda não há agenda; o "|| true" evita que o set -e pare o script)
{ crontab -l 2>/dev/null | grep -v 'deploy/vigia.sh' || true; echo "$linha"; } | crontab -

# Relatório no celular (ntfy, precisa de NTFY_TOPIC no .env): resumo às 2h, 8h, 14h e 20h; alertas a cada 15 min
linha1="0 2,8,14,20 * * * $PROJ/deploy/relatorio.sh >/dev/null 2>&1"
linha2="*/15 * * * * $PROJ/deploy/relatorio.sh --alertas >/dev/null 2>&1"
{ crontab -l 2>/dev/null | grep -v 'deploy/relatorio.sh' || true; echo "$linha1"; echo "$linha2"; } | crontab -

# Mantém a VM "não ociosa" para a Oracle não recolher (~1 min de CPU a cada 10, prioridade mínima).
# 0.24.0: --aleatorio sorteia o atraso (0 a 4 min) e a duração (45 a 90 s) de cada rodada.
linha="*/10 * * * * $PROJ/deploy/manter-ativa.sh --aleatorio >/dev/null 2>&1"
{ crontab -l 2>/dev/null | grep -v 'deploy/manter-ativa.sh' || true; echo "$linha"; } | crontab -

echo
echo "== Pronto. Saia e entre de novo no SSH (para o grupo docker valer) e rode:"
echo "     cd $PROJ && docker compose --profile public up -d --build"
