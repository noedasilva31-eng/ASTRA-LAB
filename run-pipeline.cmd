@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 2
py -3 -B -m astra_pipeline %*
set "astra_pipeline_rc=%errorlevel%"
popd
exit /b %astra_pipeline_rc%
