#!/usr/bin/env bash
# Evita que a Oracle considere a VM grátis "ociosa" e a recolha (contas Free Tier, sem Pay As You Go).
# A Oracle recolhe quando, em 7 dias, o percentil 95 da CPU fica abaixo de 20% (e rede/memória também baixas).
# Este script ocupa 1 núcleo por 60 s; o cron roda a cada 10 min => ~10% do tempo com CPU alta,
# o que deixa o percentil 95 acima de 20%. Roda com a menor prioridade (nice 19): o site sempre passa na frente.
# Instalado no cron pelo deploy/instalar-vm.sh. Para desligar: crontab -e e apague a linha do manter-ativa.
exec nice -n 19 timeout 60 sh -c 'while :; do :; done'
