@echo off
setlocal
for %%I in ("%~dp0..") do set REPO_ROOT=%%~fI
py -3 "%REPO_ROOT%\scripts\_sw\hook_launcher.py" %*
exit /b %ERRORLEVEL%
