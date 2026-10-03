@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 2
py -3 -B validate_all_current.py %*
set "astra_validation_rc=%errorlevel%"
popd
exit /b %astra_validation_rc%
