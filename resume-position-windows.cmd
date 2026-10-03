@echo off
setlocal
pushd "%~dp0"
py -3 -B -m astra_watch --live %*
set "rc=%errorlevel%"
popd
exit /b %rc%
