@echo off
REM Start PulseIQ after setup has run once.
cd /d "%~dp0"
docker compose -f docker-compose.yml -f docker-compose.portable.yml up -d
if errorlevel 1 (
    echo Could not start. Is Docker Desktop running?
    pause
    exit /b 1
)
timeout /t 8 /nobreak >nul
start http://localhost:8501
