@echo off
REM Inicia o servidor/site do 4rt3mi5 (deixe esta janela aberta).
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m artemis.server
) else (
  python -m artemis.server
)
pause
