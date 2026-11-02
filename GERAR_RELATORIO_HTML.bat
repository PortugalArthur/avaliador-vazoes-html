@echo off
cd /d "%~dp0"
python -m aplicacao.executar %*
if errorlevel 1 pause
