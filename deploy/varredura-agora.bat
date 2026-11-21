@echo off
rem Botão: roda a varredura de highscores agora, dentro da VM (sem esperar as 09h).
rem Dê dois cliques. Pode levar até ~40 minutos; deixe a janela aberta até aparecer a resposta.
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "deploy\varredura-agora.ps1"
if errorlevel 1 (
  echo.
  echo A varredura nao terminou. Veja a mensagem acima.
)
pause
