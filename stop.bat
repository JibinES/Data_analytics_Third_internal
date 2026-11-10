@echo off
REM Stop PulseIQ. Your data stays in Docker for next time.
cd /d "%~dp0"
docker compose -f docker-compose.yml -f docker-compose.portable.yml down
pause
