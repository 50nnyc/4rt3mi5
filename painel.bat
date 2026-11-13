@echo off
REM Abre o painel de administracao do 4rt3mi5 (so funciona neste PC) e mostra a senha.
cd /d "%~dp0"
docker compose exec server python -m artemis.server admin-token
start "" http://localhost:8000/admin
pause
