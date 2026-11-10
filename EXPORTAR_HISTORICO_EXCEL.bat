@echo off
cd /d "%~dp0"
python -m aplicacao.exportar_historico_csv
if errorlevel 1 pause
