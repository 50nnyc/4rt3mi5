#!/usr/bin/env bash
# Relatório do 4rt3mi5 no celular (app grátis "ntfy"), complementando o deploy/vigia.sh.
#   relatorio.sh            -> resumo: no ar, versão, containers, disco, memória, backup, última queda
#   relatorio.sh --alertas  -> só avisa se algo passou do limite (disco cheio, backup atrasado, container parado)
# Instalado no cron pelo deploy/instalar-vm.sh: resumo às 2h, 8h, 14h e 20h; alertas a cada 15 minutos.
# Só manda status da máquina: nada de token, código de acesso, e-mail ou nome de usuário.
# Precisa de NTFY_TOPIC no .env (o tópico funciona como senha: nome longo e aleatório).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
FLAGS="$DATA/alertas"
LOG="$DATA/vigia.log"
cd "$ROOT" || exit 1
mkdir -p "$FLAGS"

DISCO_LIMITE=85        # % do disco usado
BACKUP_LIMITE_H=30     # horas sem backup novo
ESPERADOS=(artemis-server artemis-ngrok)

envval() { [ -f .env ] && grep -E "^\s*$1\s*=" .env | head -n1 | cut -d= -f2- | tr -d " \"'\r"; }
topic=$(envval NTFY_TOPIC)
[ -n "$(envval SITE_DOMAIN)" ] && ESPERADOS+=(artemis-caddy)
log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" >> "$LOG"; }

notify() {  # $1 = título (sem acento: vai em cabeçalho HTTP), $2 = prioridade, $3 = etiquetas, $4 = texto
  [ -n "$topic" ] || { echo "NTFY_TOPIC vazio no .env: nada enviado." >&2; return 1; }
  curl -fsS -m 15 -o /dev/null -H "Title: $1" -H "Priority: $2" -H "Tags: $3" --data-binary "$4" "https://ntfy.sh/$topic" \
    || { log "Não consegui mandar o relatório pelo ntfy."; return 1; }
}

# ---------- coleta ----------
disco=$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')
mem_livre=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
ligada=$(uptime -p | sed 's/^up //; s/weeks\?/sem/; s/days\?/d/; s/hours\?/h/; s/minutes\?/min/')
rodando=$(docker ps --format '{{.Names}}' 2>/dev/null)
faltando=()
for c in "${ESPERADOS[@]}"; do grep -qx "$c" <<<"$rodando" || faltando+=("$c"); done

ultimo_backup=$(ls -1t "$DATA"/backups/artemis-*.db 2>/dev/null | head -n1)
if [ -n "$ultimo_backup" ]; then
  idade_h=$(( ( $(date +%s) - $(stat -c %Y "$ultimo_backup") ) / 3600 ))
  backup_txt="$(date -r "$ultimo_backup" '+%d/%m %H:%M') (há ${idade_h} h)"
else
  idade_h=99999; backup_txt="nenhum encontrado"
fi

# ---------- alertas (só quando o estado muda, para não repetir a cada 15 min) ----------
alerta() {  # $1 = nome do alerta, $2 = está ruim? (1/0), $3 = título, $4 = texto ruim, $5 = texto resolvido
  local flag="$FLAGS/$1"
  if [ "$2" = 1 ] && [ ! -f "$flag" ]; then
    notify "$3" high warning "$4" && touch "$flag"; log "ALERTA: $4"
  elif [ "$2" = 0 ] && [ -f "$flag" ]; then
    notify "4rt3mi5: resolvido" default white_check_mark "$5" && rm -f "$flag"; log "Resolvido: $5"
  fi
}

if [ "${1:-}" = "--alertas" ]; then
  alerta disco "$([ "$disco" -ge "$DISCO_LIMITE" ] && echo 1 || echo 0)" "4rt3mi5: disco quase cheio" \
    "Disco da VM em ${disco}% (limite ${DISCO_LIMITE}%)." "Disco da VM voltou para ${disco}%."
  alerta backup "$([ "$idade_h" -ge "$BACKUP_LIMITE_H" ] && echo 1 || echo 0)" "4rt3mi5: backup atrasado" \
    "Último backup do banco: $backup_txt." "Backup em dia de novo: $backup_txt."
  alerta containers "$([ ${#faltando[@]} -gt 0 ] && echo 1 || echo 0)" "4rt3mi5: container parado" \
    "Parado: ${faltando[*]:-}. O vigia tenta religar a cada 5 minutos." "Todos os containers rodando de novo."
  # 0.21.0: lembrete do relatório mensal de visitas (programa de fansites da CipSoft: até o dia 3)
  mes_flag="$FLAGS/relatorio-$(date +%Y-%m)"
  if [ "$(date +%-d)" -le 3 ] && [ "$(date +%-H)" -ge 9 ] && [ ! -f "$mes_flag" ]; then
    notify "4rt3mi5: relatorio mensal" default memo \
      "Hora do relatório de visitas do mês passado: painel admin → Relatório mensal → Copiar relatório em inglês, e envie para fansites@tibia.com até o dia 3." \
      && touch "$mes_flag" && log "Lembrete do relatório mensal enviado."
    find "$FLAGS" -name 'relatorio-*' -mtime +70 -delete 2>/dev/null
  fi
  exit 0
fi

# ---------- resumo ----------
st="$DATA/vigia.json"
ok=false; grep -q '"ok": *true' "$st" 2>/dev/null && ok=true
versao=$(curl -fsS -m 10 http://localhost:8000/api/health 2>/dev/null | grep -oE '"version" *: *"[^"]+"' | cut -d'"' -f4)
queda=$(grep -E 'FORA DO AR' "$LOG" 2>/dev/null | tail -n1 | cut -c1-16)
[ -n "$queda" ] && queda="$(date -d "$queda" '+%d/%m %H:%M' 2>/dev/null || echo "$queda")" || queda="nenhuma registrada"

if [ "$ok" = true ] && [ ${#faltando[@]} -eq 0 ]; then
  titulo="4rt3mi5 no ar"; prio=low; tag=white_check_mark; cab="✅ Tudo certo"
else
  titulo="4rt3mi5 com problema"; prio=high; tag=warning
  cab="⚠️ $(grep -oE '"message": *"[^"]+"' "$st" 2>/dev/null | cut -d'"' -f4)"
fi
cont_txt="$(( ${#ESPERADOS[@]} - ${#faltando[@]} ))/${#ESPERADOS[@]} rodando"
[ ${#faltando[@]} -gt 0 ] && cont_txt="$cont_txt (parado: ${faltando[*]})"

texto="$cab · versão ${versao:-?}
Containers: $cont_txt
Disco: ${disco}% · Memória livre: ${mem_livre} MB
VM ligada há $ligada
Último backup: $backup_txt
Última queda: $queda"

notify "$titulo" "$prio" "$tag" "$texto"
