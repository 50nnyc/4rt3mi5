@echo off
rem Botão de atualização: envia a versão atual deste PC para a VM e reinicia o servidor lá.
rem Dê dois cliques neste arquivo. Não migra o banco (só o código); a migração é feita uma vez, à parte.
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "deploy\enviar-para-vm.ps1"
if errorlevel 1 (
  echo.
  echo A atualizacao nao terminou. Veja a mensagem acima.
) else (
  echo.
  echo Atualizacao concluida. Confira: https://artemishunt.com.br/api/health
)
pause
