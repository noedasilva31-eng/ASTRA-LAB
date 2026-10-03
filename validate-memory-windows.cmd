@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 2
py -3 validate_memory_all.py %*
set "astra_memory_rc=%errorlevel%"
popd
exit /b %astra_memory_rc%
