@echo off
setlocal
if "%~1"=="" (
  echo Usage: run-v1b.cmd "C:\chemin\ASTRA-V1b" [--self-test]
  exit /b 2
)
py -3 "%~dp0validate_v1b.py" --project "%~1" %2 %3 %4 %5
exit /b %errorlevel%
