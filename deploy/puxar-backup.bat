@echo off
rem Agenda a copia diaria do backup da VM para este PC (todo dia as 12:00; se o PC estiver desligado, roda quando ligar).
rem Para remover:  schtasks /Delete /TN "4rt3mi5 backup da VM" /F
set SCRIPT=%~dp0puxar-backup.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"%SCRIPT%\"';" ^
  "$t = New-ScheduledTaskTrigger -Daily -At 12:00;" ^
  "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;" ^
  "Register-ScheduledTask -TaskName '4rt3mi5 backup da VM' -Action $a -Trigger $t -Settings $s -Force | Out-Null"
if errorlevel 1 (
  echo Nao foi possivel criar a tarefa.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
echo.
echo Copia diaria agendada. Os backups ficam na pasta backup-vm deste projeto.
pause
