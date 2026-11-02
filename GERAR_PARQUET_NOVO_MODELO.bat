@echo off
cd /d "%~dp0"
python -m geradores.consolidar_vazoes_incrementais_e_lags %*
if errorlevel 1 pause
