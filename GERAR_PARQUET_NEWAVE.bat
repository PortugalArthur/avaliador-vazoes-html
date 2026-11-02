@echo off
cd /d "%~dp0"
python -m geradores.converter_qincr_newave %*
if errorlevel 1 pause
