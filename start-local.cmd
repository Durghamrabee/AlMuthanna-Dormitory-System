@echo off
setlocal
call "%~dp0legacy\django\start-local.cmd" %*
exit /b %errorlevel%
