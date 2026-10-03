@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 2
py -3 validate_all.py %*
set "astra_all_rc=%errorlevel%"
popd
exit /b %astra_all_rc%
