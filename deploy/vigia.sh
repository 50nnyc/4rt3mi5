#!/usr/bin/env bash
# Vigia do 4rt3mi5 na VM (Linux). Mesma ideia do tools/vigia.ps1 do Windows:
#  - servidor parado          -> "docker compose --profile public up -d"
#  - só o ngrok sem responder -> reinicia o container do ngrok
# Grava data/vigia.json (o painel /admin mostra) e o histórico em data/vigia.log.
# Instalado no cron pelo deploy/instalar-vm.sh (a cada 5 minutos).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
STATUS="$DATA/vigia.json"
LOG="$DATA/vigia.log"
mkdir -p "$DATA"
cd "$ROOT" || exit 1

log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" >> "$LOG"; }
ok_url() { curl -fsS -m 15 -H 'ngrok-skip-browser-warning: 1' -o /dev/null "$1"; }

domain=""
if [ -f .env ]; then
  domain=$(grep -E '^\s*NGROK_DOMAIN\s*=' .env | head -n1 | cut -d= -f2- | tr -d " \"'\r" | sed -E 's#^https?://##; s#/+$##')
fi
local_url="http://localhost:8000/api/health"
public_url=""
[ -n "$domain" ] && public_url="https://$domain/api/health"

local=false; public=null; fix=null
ok_url "$local_url" && local=true
if [ -n "$public_url" ]; then ok_url "$public_url" && public=true || public=false; fi

if [ "$local" = false ]; then
  fix='"servidor reiniciado"'
  log "Servidor local não respondeu: subindo os containers."
  docker compose --profile public up -d >/dev/null 2>&1; log "docker compose up -d -> código $?"
  sleep 45
  ok_url "$local_url" && local=true
  if [ -n "$public_url" ]; then ok_url "$public_url" && public=true || public=false; fi
elif [ "$public" = false ]; then
  fix='"ngrok reiniciado"'
  log "Site pela internet não respondeu: reiniciando o ngrok."
  docker compose --profile public restart ngrok >/dev/null 2>&1; log "docker compose restart ngrok -> código $?"
  sleep 25
  ok_url "$public_url" && public=true || public=false
fi

ok=false
if [ "$local" = true ] && [ "$public" != false ]; then ok=true; fi
if [ "$ok" = true ]; then msg="Tudo certo"
elif [ "$local" = false ]; then msg="O servidor na VM não responde (o Docker está rodando?)"
else msg="O servidor responde na VM, mas não pela internet (ngrok)"; fi

now=$(date '+%Y-%m-%dT%H:%M:%S%:z')
prev_ok=true; prev_down=""
if [ -f "$STATUS" ]; then
  grep -q '"ok": *false' "$STATUS" && prev_ok=false
  prev_down=$(grep -oE '"down_since": *"[^"]+"' "$STATUS" | cut -d'"' -f4)
fi
down=null
if [ "$ok" = false ]; then
  if [ "$prev_ok" = false ] && [ -n "$prev_down" ]; then down="\"$prev_down\""; else down="\"$now\""; fi
fi

cat > "$STATUS.tmp" <<EOF
{
  "checked_at": "$now",
  "ok": $ok,
  "local": $local,
  "public": $public,
  "message": "$msg",
  "down_since": $down,
  "last_fix": $fix
}
EOF
mv "$STATUS.tmp" "$STATUS"

if [ "$ok" = false ] && [ "$prev_ok" = true ]; then log "FORA DO AR: $msg"
elif [ "$ok" = true ] && [ "$prev_ok" = false ]; then log "Voltou ao ar."
elif [ "$fix" != null ] && [ "$ok" = true ]; then log "Estava fora do ar e voltou depois de: ${fix//\"/}."; fi
