@echo off
REM PulseIQ first-time setup. Needs Docker Desktop running.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
pause
