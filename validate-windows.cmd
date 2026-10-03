@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 2
py -3 validator\check_runner.py --project .
set "astra_runner_rc=%errorlevel%"
py -3 validator\validate_v1b.py --project . %*
set "astra_v1b_rc=%errorlevel%"
popd
if not "%astra_runner_rc%"=="0" exit /b %astra_runner_rc%
exit /b %astra_v1b_rc%
