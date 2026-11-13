@echo off
REM Administracao dos codigos de acesso do 4rt3mi5
REM   admin.bat create "Nome da pessoa"     cria codigo de 30 dias
REM   admin.bat create "Nome" 7             cria codigo de 7 dias
REM   admin.bat list                        lista codigos validos, main e personagens
REM   admin.bat renew ART-XXXX-XXXX         renova por 30 dias (mantem personagens)
REM   admin.bat reset ART-XXXX-XXXX         desvincula o dono (verifica de novo)
REM   admin.bat revoke ART-XXXX-XXXX        apaga o codigo
REM Com Docker, use:  docker compose exec server python -m artemis.server keys list
cd /d "%~dp0"
set PY=python
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python.exe
if /I "%1"=="create" (
  if "%~3"=="" ( %PY% -m artemis.server keys create --label "%~2" ) else ( %PY% -m artemis.server keys create --label "%~2" --days %3 )
  goto :eof
)
if /I "%1"=="list" ( %PY% -m artemis.server keys list & goto :eof )
if /I "%1"=="renew" ( %PY% -m artemis.server keys renew %2 & goto :eof )
if /I "%1"=="reset" ( %PY% -m artemis.server keys reset %2 & goto :eof )
if /I "%1"=="revoke" ( %PY% -m artemis.server keys revoke %2 & goto :eof )
echo Uso: admin.bat create "Nome" [dias] ^| list ^| renew CODIGO ^| reset CODIGO ^| revoke CODIGO
