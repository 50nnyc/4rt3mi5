@echo off
rem Instala o vigia do 4rt3mi5 no Agendador de Tarefas do Windows.
rem Ele confere o site a cada 5 minutos, tenta religar sozinho e avisa com uma notificacao se sair do ar.
rem Para remover:  schtasks /Delete /TN "4rt3mi5 vigia" /F
set SCRIPT=%~dp0tools\vigia.ps1
schtasks /Create /F /SC MINUTE /MO 5 /TN "4rt3mi5 vigia" /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"%SCRIPT%\""
if errorlevel 1 (
  echo Nao foi possivel criar a tarefa.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Teste
echo.
echo Vigia instalado. Ele roda a cada 5 minutos; o resultado aparece no painel (painel.bat).
pause
