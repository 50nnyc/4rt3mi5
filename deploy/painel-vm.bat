@echo off
rem Abre o painel de administracao do 4rt3mi5 que esta rodando na VM.
rem O painel so aceita acesso "local": este script cria um tunel SSH (porta 8000 deste PC -> porta 8000 da VM),
rem entao para o servidor e como se voce estivesse na propria VM. Feche esta janela para fechar o tunel.
cd /d "%~dp0.."
echo Senha do painel:
ssh artemis-vm "cd 4rt3mi5 && docker compose exec -T server python -m artemis.server admin-token"
if errorlevel 1 (
  echo Nao consegui entrar na VM. Confira o arquivo %%USERPROFILE%%\.ssh\config ^(deploy\GUIA-VM.md^).
  pause
  exit /b 1
)
echo.
echo Abrindo o tunel... ^(se der erro de porta 8000 em uso, desligue o servidor deste PC: docker compose down^)
start "" cmd /c "timeout /t 3 >nul & start http://localhost:8000/admin"
ssh -N -L 8000:localhost:8000 artemis-vm
pause
