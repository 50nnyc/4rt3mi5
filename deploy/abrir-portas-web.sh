#!/usr/bin/env bash
# Libera as portas 80 (HTTP, usada pelo Let's Encrypt) e 443 (HTTPS) no firewall interno do Ubuntu da Oracle,
# que vem bloqueando tudo menos o SSH. Só é preciso para o domínio próprio (Caddy). Pode rodar mais de uma vez.
# Também é preciso abrir as mesmas portas na "Security List" da Oracle (deploy/GUIA-VM.md, passo 10).
set -euo pipefail
for porta in 80 443; do
  if ! sudo iptables -C INPUT -p tcp -m state --state NEW -m tcp --dport "$porta" -j ACCEPT 2>/dev/null; then
    # entra logo antes da regra REJECT do fim
    linha=$(sudo iptables -L INPUT --line-numbers -n | awk '/REJECT/ {print $1; exit}')
    sudo iptables -I INPUT "${linha:-1}" -p tcp -m state --state NEW -m tcp --dport "$porta" -j ACCEPT
    echo "Porta $porta liberada."
  else
    echo "Porta $porta já estava liberada."
  fi
done
sudo netfilter-persistent save >/dev/null   # mantém depois de reiniciar
