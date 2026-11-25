@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0" || exit /b 1

set "INFRA=infraestrutura"
if exist "programa\infraestrutura\iniciar.py" set "INFRA=programa\infraestrutura"
set "PYTHON_EXE=%CD%\_python\python.exe"
if exist "%PYTHON_EXE%" goto executar

set "PYTHON_EXE="
for /f "delims=" %%I in ('""%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "%INFRA%\localizar_python.ps1""') do set "PYTHON_EXE=%%I"
if defined PYTHON_EXE goto executar

echo Python 3.10 ou mais recente, de 64 bits e com Tcl/Tk, nao foi encontrado.
echo Baixe AVALIADOR_VAZOES_HTML_WINDOWS_X64.zip em:
echo https://github.com/PortugalArthur/avaliador-vazoes-html/releases
echo Extraia todo o ZIP e mantenha a pasta _python junto aos atalhos.
set "CODIGO=1"
goto encerrar

:executar
"%PYTHON_EXE%" -E -s -X utf8 "%INFRA%\iniciar.py" %*
set "CODIGO=%ERRORLEVEL%"

:encerrar
popd
if not "%CODIGO%"=="0" pause
exit /b %CODIGO%
