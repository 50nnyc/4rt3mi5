#!/usr/bin/env bash
# Evita que a Oracle considere a VM grátis "ociosa" e a recolha (contas Free Tier, sem Pay As You Go).
# A Oracle recolhe quando, em 7 dias, o percentil 95 da CPU fica abaixo de 20% (e rede/memória também baixas).
# Este script ocupa 1 núcleo por um tempo; o cron roda a cada 10 min => ~10% do tempo com CPU alta,
# o que deixa o percentil 95 acima de 20%. Roda com a menor prioridade (nice 19): o site sempre passa na frente.
#
# 0.24.0: horário e duração aleatórios (o gráfico não fica com picos em horário fixo):
#   manter-ativa.sh              -> 45 a 90 s de CPU, já
#   manter-ativa.sh --aleatorio  -> espera 0 a 4 min antes (é assim que o cron chama)
#   manter-ativa.sh --extra      -> rodada extra pedida pelo PC (deploy\manter-ativa-vm.bat): 30 a 75 s, em segundo plano
# Uma trava (flock) impede duas rodadas ao mesmo tempo: se já tem uma rodando, a nova desiste.
# Instalado no cron pelo deploy/instalar-vm.sh. Para desligar: crontab -e e apague a linha do manter-ativa.
set -u
modo="${1:-}"
LOCK=/tmp/artemis-manter-ativa.lock
LOG="$(cd "$(dirname "$0")/.." && pwd)/data/manter-ativa.log"

sorteio() { echo $(( $1 + RANDOM % ($2 - $1 + 1) )); }

rodar() {
    local espera=$1 dur=$2
    [ "$espera" -gt 0 ] && sleep "$espera"
    exec 9>"$LOCK"
    flock -n 9 || exit 0  # já tem uma rodada em andamento
    echo "$(date '+%F %T')  ${modo:-manual}: ${dur}s de CPU (esperou ${espera}s)" >> "$LOG" 2>/dev/null || true
    # mantém só as últimas 500 linhas do log
    if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 600 ]; then tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi
    nice -n 19 timeout "$dur" sh -c 'while :; do :; done'
}

case "$modo" in
    --aleatorio) rodar "$(sorteio 0 240)" "$(sorteio 45 90)" ;;
    --extra)     # volta na hora para o SSH do PC não ficar preso; a CPU roda sozinha na VM
                 nohup "$0" --extra-agora >/dev/null 2>&1 &
                 echo "ok" ;;
    --extra-agora) modo="--extra"; rodar 0 "$(sorteio 30 75)" ;;
    *)           rodar 0 "$(sorteio 45 90)" ;;
esac
