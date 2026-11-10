@echo off
cd /d "%~dp0"
python -m aplicacao.exportar_csv
if errorlevel 1 pause
