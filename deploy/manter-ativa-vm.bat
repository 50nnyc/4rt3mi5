@echo off
rem Agenda, neste PC, rodadas EXTRAS do "manter a VM ativa" em horarios sorteados (alem do cron da VM).
rem De hora em hora o script sorteia se roda (3 em cada 4) e quanto espera (0 a 40 min) antes de pedir a VM.
rem Se o PC estiver desligado, nada acontece: o cron da VM continua sozinho (tambem com horario sorteado).
rem Para remover:  schtasks /Delete /TN "4rt3mi5 manter VM ativa" /F
set SCRIPT=%~dp0manter-ativa-vm.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"%SCRIPT%\"';" ^
  "$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes((Get-Random -Minimum 5 -Maximum 55)) -RepetitionInterval (New-TimeSpan -Hours 1);" ^
  "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 50);" ^
  "Register-ScheduledTask -TaskName '4rt3mi5 manter VM ativa' -Action $a -Trigger $t -Settings $s -Force | Out-Null"
if errorlevel 1 (
  echo Nao foi possivel criar a tarefa.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Agora
echo.
echo Rodadas extras agendadas (de hora em hora, em minuto sorteado). Historico: data\manter-ativa-vm.log
pause
